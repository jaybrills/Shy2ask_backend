"""
Load offensive terms from DB (with cache) and AI censor.
Flow: Our model first → OpenAI (if key set) → Google API fallback.
Text: OpenAI Moderation API (40+ languages, incl. European). Image: OCR + text censor + OpenAI Vision (any language).
European languages: Included in PERSPECTIVE_LANGUAGES (en, de, fr, es, it, pt, nl, pl, ru, uk, cs, sk, hu, ro, bg, sr, hr, sl, el, sv, no, da, fi, et, lv, lt, ga, cy, ca, mt, is).
"""
import base64
import json
import logging
import re
from typing import Optional, Tuple

from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

CACHE_KEY_TERMS = "censor_engine_db_terms"
CACHE_TIMEOUT = 60  # seconds


def get_offensive_terms_from_db():
    """
    Load active OffensiveTerm from DB, grouped by category slug.
    Returns: {
        "slug": [{"term": str, "term_type": "word"|"phrase", "is_blocking": bool}, ...],
        ...
    }
    """
    cached = cache.get(CACHE_KEY_TERMS)
    if cached is not None:
        return cached
    try:
        from .models import CensorCategory, OffensiveTerm
        qs = OffensiveTerm.objects.filter(is_active=True).select_related("category")
        by_category = {}
        for ot in qs:
            slug = ot.category.slug
            if slug not in by_category:
                by_category[slug] = []
            by_category[slug].append({
                "term": ot.term.strip(),
                "term_type": ot.term_type,
                "is_blocking": ot.is_blocking,
            })
        for slug in by_category:
            phrases = [x for x in by_category[slug] if x["term_type"] == "phrase"]
            words = [x for x in by_category[slug] if x["term_type"] == "word"]
            phrases.sort(key=lambda x: len(x["term"]), reverse=True)
            by_category[slug] = phrases + words
        cache.set(CACHE_KEY_TERMS, by_category, CACHE_TIMEOUT)
        return by_category
    except Exception as e:
        logger.warning("censor_loader: failed to load DB terms: %s", e)
        return {}


def invalidate_censor_cache():
    """Call after saving/editing OffensiveTerm or CensorCategory."""
    cache.delete(CACHE_KEY_TERMS)


def our_model_predict(text: str) -> tuple[bool, float]:
    """
    Run our own trained model. Returns (is_toxic, score).
    If no model file or error, returns (False, 0.0).
    """
    if not text or not text.strip():
        return False, 0.0
    model_path = getattr(settings, "CENSOR_MODEL_PATH", None)
    if not model_path or not __import__("os").path.isfile(model_path):
        return False, 0.0
    try:
        import joblib
        pipeline = joblib.load(model_path)
        X = [text[:20480]]
        # We train with labels: 0=safe, 1=toxic → proba[1] = P(toxic)
        score = float(pipeline.predict_proba(X)[0][1])
        threshold = float(getattr(settings, "CENSOR_OUR_MODEL_THRESHOLD", 0.6))
        is_toxic = score >= threshold
        return is_toxic, score
    except Exception as e:
        logger.warning("our_model_predict failed: %s", e)
        return False, 0.0


# Google Perspective: European languages first (required), then rest of world
PERSPECTIVE_LANGUAGES = [
    # European (EU / Europe)
    "en", "de", "fr", "es", "it", "pt", "nl", "pl", "ru", "uk", "cs", "sk", "hu", "ro", "bg",
    "sr", "hr", "sl", "el", "sv", "no", "da", "fi", "et", "lv", "lt", "ga", "cy", "ca", "mt", "is",
    # Other
    "ar", "hi", "zh", "zh-TW", "zh-CN", "ja", "ko", "th", "vi", "id", "ms", "tl",
    "bn", "ta", "te", "mr", "gu", "kn", "pa", "ur", "fa", "tr", "sw", "am", "he",
]

def _google_api_check(text: str) -> tuple[bool, float]:
    """Call Google Perspective API. Returns (is_toxic, score). Supports many languages via PERSPECTIVE_LANGUAGES."""
    api_key = getattr(settings, "PERSPECTIVE_API_KEY", None) or getattr(settings, "CENSOR_AI_API_KEY", None)
    if not api_key:
        return False, 0.0
    threshold = float(getattr(settings, "CENSOR_AI_THRESHOLD", 0.5))
    try:
        import requests
        url = "https://commentanalyzer.googleapis.com/v1alpha1/comments:analyze"
        payload = {
            "comment": {"text": text[:20480]},
            "languages": getattr(settings, "CENSOR_PERSPECTIVE_LANGUAGES", None) or PERSPECTIVE_LANGUAGES,
            "requestedAttributes": {
                "TOXICITY": {},
                "SEVERE_TOXICITY": {},
                "THREAT": {},
                "IDENTITY_ATTACK": {},
            },
        }
        r = requests.post(url, params={"key": api_key}, json=payload, timeout=5)
        r.raise_for_status()
        data = r.json()
        attr = data.get("attributeScores", {})
        tox = attr.get("TOXICITY", {}).get("summaryScore", {}).get("value", 0)
        severe = attr.get("SEVERE_TOXICITY", {}).get("summaryScore", {}).get("value", 0)
        threat = attr.get("THREAT", {}).get("summaryScore", {}).get("value", 0)
        identity = attr.get("IDENTITY_ATTACK", {}).get("summaryScore", {}).get("value", 0)
        score = max(tox, severe, threat, identity)
        is_toxic = score >= threshold
        return is_toxic, score
    except Exception as e:
        logger.warning("Google API check failed: %s", e)
        return False, 0.0


def _openai_text_check(text: str) -> Tuple[bool, float]:
    """OpenAI Moderation API – supports 40+ languages. Returns (is_toxic, score). On error (False, 0.0)."""
    api_key = getattr(settings, "OPENAI_API_KEY", None)
    if not api_key:
        return False, 0.0
    threshold = float(getattr(settings, "CENSOR_AI_THRESHOLD", 0.5))
    model = (getattr(settings, "CENSOR_OPENAI_MODERATION_MODEL", None) or "").strip()
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        kwargs = {"input": text[:20480]}
        if model:
            kwargs["model"] = model
        r = client.moderations.create(**kwargs)
        res = r.results[0]
        flagged = res.flagged
        scores = _category_scores_to_dict(getattr(res, "category_scores", None))
        score = max((float(v) for v in scores.values()), default=0.0)
        return (flagged or (score >= threshold)), score
    except Exception as e:
        if model:
            try:
                from openai import OpenAI
                client = OpenAI(api_key=api_key)
                r = client.moderations.create(input=text[:20480])
                res = r.results[0]
                flagged = res.flagged
                scores = _category_scores_to_dict(getattr(res, "category_scores", None))
                score = max((float(v) for v in scores.values()), default=0.0)
                return (flagged or (score >= threshold)), score
            except Exception:
                pass
        logger.warning("OpenAI Moderation check failed: %s", e)
        return False, 0.0


def _category_scores_to_dict(scores_obj) -> dict:
    """Normalize OpenAI category_scores object to plain dict for robust parsing."""
    if not scores_obj:
        return {}
    if isinstance(scores_obj, dict):
        return scores_obj
    try:
        dump = scores_obj.model_dump()
        if isinstance(dump, dict):
            return dump
    except Exception:
        pass
    try:
        d = dict(scores_obj)
        if isinstance(d, dict):
            return d
    except Exception:
        pass
    out = {}
    for name in dir(scores_obj):
        if name.startswith("_"):
            continue
        try:
            value = getattr(scores_obj, name)
        except Exception:
            continue
        if callable(value):
            continue
        if isinstance(value, (int, float, bool)):
            out[name] = float(value)
    return out


def ai_illegal_intent_check(text: str) -> tuple[bool, float, list[str]]:
    """
    OpenAI classifier for illegal-intent talk not always covered by toxicity moderation.
    Returns (blocked, score, categories).
    """
    if not text or not text.strip():
        return False, 0.0, []
    api_key = getattr(settings, "OPENAI_API_KEY", None)
    if not api_key:
        return False, 0.0, []
    try:
        from openai import OpenAI

        client = OpenAI(api_key=api_key)
        prompt = (
            "Classify whether the message is requesting, planning, offering, selling, buying, or facilitating illegal activity. "
            "Focus on drugs, weapons/arms, human trafficking, sexual exploitation (especially minors), fraud/scams, "
            "money laundering, extortion/blackmail, violent crime, terrorism, kidnapping, counterfeit documents. "
            "Return ONLY JSON: "
            "{\"blocked\": true|false, \"score\": 0..1, \"categories\": ["
            "\"drugs\",\"weapons\",\"human_trafficking\",\"sexual_exploitation\",\"fraud_scam\","
            "\"money_laundering\",\"extortion\",\"violent_crime\",\"terrorism\",\"kidnapping\",\"counterfeit\","
            "\"illegal_other\"]}"
        )
        r = client.chat.completions.create(
            model=getattr(settings, "CENSOR_OPENAI_POLICY_MODEL", "gpt-4o-mini"),
            messages=[
                {"role": "system", "content": "You are a strict safety classifier. Output valid JSON only."},
                {"role": "user", "content": f"{prompt}\n\nMESSAGE:\n{text[:8000]}"},
            ],
            temperature=0,
            max_tokens=220,
        )
        raw = (r.choices[0].message.content or "").strip()
        start = raw.find("{")
        if start == -1:
            return False, 0.0, []
        depth, end = 0, start
        for i, c in enumerate(raw[start:], start):
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        data = json.loads(raw[start : end + 1])
        blocked = bool(data.get("blocked"))
        score = float(data.get("score", 0.0))
        categories = data.get("categories") or []
        if not isinstance(categories, list):
            categories = []
        categories = [str(x).strip() for x in categories if str(x).strip()]
        threshold = float(getattr(settings, "CENSOR_AI_THRESHOLD", 0.5))
        return blocked or score >= threshold, score, categories
    except Exception as e:
        logger.warning("OpenAI illegal intent check failed: %s", e)
        return False, 0.0, []


def _openai_image_check(image_bytes: bytes, content_type: Optional[str] = None) -> Tuple[bool, float]:
    """OpenAI Vision: classify image as safe/unsafe (any language). Returns (is_toxic, score). On error (False, 0.0)."""
    api_key = getattr(settings, "OPENAI_API_KEY", None)
    if not api_key:
        return False, 0.0
    threshold = float(getattr(settings, "CENSOR_AI_THRESHOLD", 0.5))
    content_type = content_type or "image/jpeg"
    if "/" not in content_type:
        content_type = "image/jpeg"
    try:
        from openai import OpenAI
        b64 = base64.standard_b64encode(image_bytes).decode("ascii")
        data_uri = f"data:{content_type};base64,{b64}"
        client = OpenAI(api_key=api_key)
        prompt = (
            "Is this image safe for a general audience? Consider text and imagery in ANY language. "
            "Does it show violence, adult/sexual content, drugs, weapons, illegal activity, or hate symbols? "
            "Reply ONLY with a single JSON object, no other text: {\"safe\": true or false, \"score\": 0.0 to 1.0} "
            "where score is how unsafe (1=very unsafe)."
        )
        msg = [
            {"type": "image_url", "image_url": {"url": data_uri}},
            {"type": "text", "text": prompt},
        ]
        resp = client.chat.completions.create(
            model=getattr(settings, "CENSOR_OPENAI_VISION_MODEL", "gpt-4o-mini"),
            messages=[{"role": "user", "content": msg}],
            max_tokens=150,
        )
        raw = (resp.choices[0].message.content or "").strip()
        # Extract JSON (handle markdown code block or extra text)
        start = raw.find("{")
        if start == -1:
            return False, 0.0
        depth, end = 0, start
        for i, c in enumerate(raw[start:], start):
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        try:
            data = json.loads(raw[start : end + 1])
        except json.JSONDecodeError:
            return False, 0.0
        safe = data.get("safe", True)
        score = float(data.get("score", 0.0))
        is_toxic = (not safe) or (score >= threshold)
        return is_toxic, score
    except Exception as e:
        logger.warning("OpenAI Vision check failed: %s", e)
        return False, 0.0


def _save_training_example(text: str, is_toxic: bool, source: str, score: Optional[float] = None):
    """Save example for retraining our model."""
    try:
        from .models import CensorTrainingExample
        CensorTrainingExample.objects.create(
            text=(text or "")[:2000],
            is_toxic=is_toxic,
            source=source,
            score=score,
        )
    except Exception as e:
        logger.warning("save_training_example failed: %s", e)


def ai_censor_check(text: str) -> tuple[bool, float, Optional[str]]:
    """
    Our model first; then OpenAI (if key set); then Google API.
    Saves internet AI responses to CensorTrainingExample for training.
    Returns (is_toxic, score, provider_used).
    """
    if not text or not text.strip():
        return False, 0.0, None

    use_our_first = getattr(settings, "CENSOR_USE_OUR_MODEL_FIRST", True)

    # 1. Our model
    if use_our_first:
        is_toxic, score = our_model_predict(text)
        if is_toxic and score > 0:
            return True, score, "our_model"

    # 2. OpenAI Moderation (if key set) – always return provider + score for API response
    if getattr(settings, "OPENAI_API_KEY", None):
        is_toxic_o, score_o = _openai_text_check(text)
        _save_training_example(text, is_toxic=is_toxic_o, source="openai_moderation", score=score_o)
        # Return score and provider even when safe, so API shows ai_provider / ai_toxic_score
        return (True, score_o, "openai") if is_toxic_o else (False, score_o, "openai")

    # 3. Fallback: Google API
    api_key = getattr(settings, "PERSPECTIVE_API_KEY", None) or getattr(settings, "CENSOR_AI_API_KEY", None)
    if not api_key:
        return False, 0.0, None

    is_toxic_google, score_google = _google_api_check(text)
    _save_training_example(text, is_toxic=is_toxic_google, source="google_api", score=score_google)
    if is_toxic_google:
        return True, score_google, "perspective"
    return False, score_google, "perspective"


def ai_censor_check_image(
    image_bytes: bytes,
    content_type: Optional[str] = None,
) -> Tuple[bool, float, Optional[str]]:
    """
    OpenAI Vision: classify image content as safe/unsafe.
    Returns (is_toxic, score, "openai" or None).
    """
    if not image_bytes:
        return False, 0.0, None
    if not getattr(settings, "OPENAI_API_KEY", None):
        return False, 0.0, None
    is_toxic, score = _openai_image_check(image_bytes, content_type)
    return is_toxic, score, "openai" if is_toxic else None


def log_censor_block(source: str, categories: list, detected_terms: list, text_preview: str = "", blocked: bool = True):
    """Create CensorLog when content is blocked."""
    try:
        from .models import CensorLog
        CensorLog.objects.create(
            source=source,
            categories=categories,
            detected_terms=detected_terms,
            blocked=blocked,
            text_preview=(text_preview or "")[:500],
        )
    except Exception as e:
        logger.warning("CensorLog create failed: %s", e)
