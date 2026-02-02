"""
Censor engine for text and images.
- Loads offensive terms from DB (CensorCategory, OffensiveTerm) with cache.
- Built-in lists (any language patterns).
- Optional AI censor (Perspective API) for multilingual toxicity.
- Logs blocks to CensorLog.
"""
import re
from dataclasses import dataclass, field
from typing import Optional

# Categories
CATEGORY_ABUSIVE = "abusive"
CATEGORY_ILLEGAL = "illegal"
CATEGORY_PROHIBITED_PRODUCTS = "prohibited_products"
CATEGORY_DEMANDS = "demands"
CATEGORY_HUMAN_TRADFFICKING = "human_trafficking"
CATEGORY_WEAPONS = "weapons"
CATEGORY_DRUGS = "drugs"
CATEGORY_SEXUAL_EXPLOITATION = "sexual_exploitation"
CATEGORY_VIOLENCE = "violence"
CATEGORY_SCAM_FRAUD = "scam_fraud"
CATEGORY_SELF_HARM = "self_harm"
CATEGORY_HATE = "hate"


def _normalize_for_match(text: str) -> str:
    """Collapse spaces, basic leet to letter for matching evasive spelling."""
    if not text:
        return ""
    t = text.lower().strip()
    t = re.sub(r"\s+", " ", t)
    # Leet/symbol -> letter (for substring match only)
    for a, b in [("0", "o"), ("1", "i"), ("3", "e"), ("4", "a"), ("5", "s"), ("@", "a"), ("$", "s"), ("7", "t"), ("8", "b")]:
        t = t.replace(a, b)
    return t


def _normalize_evasive(text: str) -> tuple[str, list[int]]:
    """
    Remove dots, dashes, underscores so 'd.r.u.g.s' and 'd-r-u-g-s' match 'drugs'.
    Returns (normalized_string, norm_to_orig) where norm_to_orig[i] = original index of i-th char.
    """
    if not text:
        return "", []
    lowered = text.lower()
    norm_chars = []
    norm_to_orig = []
    for i, c in enumerate(lowered):
        if c in ".-_\u00a0":
            continue
        norm_chars.append(c)
        norm_to_orig.append(i)
    normalized = "".join(norm_chars)
    return normalized, norm_to_orig


def _evasive_word_boundary_pattern(word: str) -> re.Pattern:
    """Match word with optional . - _ between any letters (e.g. d.r.u.g.s, d-r-u-g-s)."""
    if not word:
        return re.compile(r"(?!)")  # never match
    inner = r"[.\-\_]*".join(re.escape(c) for c in word)
    return re.compile(r"\b" + inner + r"\b", re.IGNORECASE)


def _evasive_phrase_pattern(phrase: str) -> re.Pattern:
    """Match phrase with optional . - _ and spaces between/inside words (e.g. b.u.y your g.i.r.l)."""
    words = phrase.split()
    if not words:
        return re.compile(r"(?!)")
    parts = [
        r"\b" + r"[.\-\_]*".join(re.escape(c) for c in w) + r"\b"
        for w in words
    ]
    return re.compile(r"[.\-\_\s]*".join(parts), re.IGNORECASE)


# ----- ABUSIVE -----
ABUSIVE_WORDS = [
    "fuck", "fucking", "fucker", "fucked", "fck", "fuk", "fuc", "fcking",
    "bitch", "btch", "biatch", "shit", "sht", "bastard", "asshole", "dick", "dickhead",
    "threat", "threaten", "kill", "murder", "rape", "rapist", "abuse", "abuser",
    "cunt", "whore", "slut", "pedophile", "paedophile", "molest", "molestor",
    "nigger", "nigga", "faggot", "fag", "retard", "retarded", "tranny",
]

# ----- ILLEGAL (single words) -----
BLOCKED_ILLEGAL = {
    "kill", "murder", "rape", "bomb", "terror", "explosive", "bomber",
    "child porn", "cp ", "human trafficking", "hitman", "assassinate", "assassination",
    "contract kill", "hire killer", "order hit", "hit list",
    "pedophile", "paedophile", "child abuse", "minor abuse",
    "terrorist", "terrorism", "isis", "taliban", "extremist",
    "kidnap", "kidnapping", "hostage", "hijack",
    "launder money", "money laundering", "fraud",
}

# ----- HUMAN TRAFFICKING / BUY-SELL PEOPLE (phrases, longest first) -----
BLOCKED_PHRASES = [
    # Long phrases first
    "want to buy your girl", "want to buy your woman", "want to buy your boy", "want to buy your child",
    "want to sell your girl", "want to sell your woman", "want to sell your boy", "want to sell your child",
    "looking to buy a girl", "looking to buy a woman", "looking to buy a boy", "looking to buy a child",
    "looking to sell a girl", "looking to sell a woman", "looking to sell a boy", "looking to sell a child",
    "i want to buy your girl", "i want to buy your woman", "i want to buy your boy", "i want to buy your child",
    "i want to sell your girl", "i want to sell your woman", "i want to sell your boy", "i want to sell your child",
    "can i buy your girl", "can i buy your woman", "can i buy your boy", "can i buy your child",
    "will buy your girl", "will buy your woman", "will buy your boy", "will buy your child",
    "for sale girl", "for sale woman", "for sale boy", "for sale child", "for sale kid", "for sale man",
    "girl for sale", "woman for sale", "boy for sale", "child for sale", "kid for sale",
    "buy your girl", "buy your woman", "buy your boy", "buy your child", "buy your kid", "buy your man",
    "sell your girl", "sell your woman", "sell your boy", "sell your child", "sell your kid", "sell your man",
    "buy your daughter", "sell your daughter", "buy your son", "sell your son",
    "buy a girl", "buy a woman", "buy a boy", "buy a child", "buy a kid", "buy a man",
    "sell a girl", "sell a woman", "sell a boy", "sell a child", "sell a kid", "sell a man",
    "buy girl", "buy woman", "buy boy", "buy child", "buy kid", "buy person", "buy human",
    "sell girl", "sell woman", "sell boy", "sell child", "sell kid", "sell person", "sell human",
    "purchase girl", "purchase woman", "purchase boy", "purchase child", "purchase kid", "purchase person",
    "selling girl", "selling woman", "selling boy", "selling child", "selling kid",
    "buying girl", "buying woman", "buying boy", "buying child", "buying kid",
    "buy daughter", "sell daughter", "buy son", "sell son",
    "order girl", "order woman", "order boy", "order child",
    "girl for sale", "woman for sale", "boy for sale", "child for sale",
    "sell wife", "buy wife", "sell husband", "buy husband",
    "trafficking girl", "trafficking woman", "trafficking boy", "trafficking child",
    "human for sale", "person for sale",
    # Evasive / slang
    "buy your grl", "sell your grl", "buy grl", "sell grl", "grl for sale",
    "buy your gurl", "sell your gurl", "buy gurl", "sell gurl",
    "buy wmn", "sell wmn", "buy your wmn", "sell your wmn",
    "buy y0ur girl", "sell y0ur girl", "buy your g1rl", "sell your g1rl",
]
BLOCKED_PHRASES.sort(key=len, reverse=True)

# ----- SEXUAL EXPLOITATION / MINORS (phrases) -----
EXPLOITATION_PHRASES = [
    "underage girl", "underage boy", "underage child", "underage sex",
    "minor girl", "minor boy", "minor sex", "sex with minor",
    "young girl for", "young boy for", "young child for",
    "sell underage", "buy underage", "underage for sale",
    "child sex", "child porn", "child pornography", "cp porn",
    "lolita", "preteen", "pre teen",
]
EXPLOITATION_PHRASES.sort(key=len, reverse=True)

# ----- WEAPONS -----
WEAPON_WORDS = [
    "gun for sale", "guns for sale", "buy gun", "sell gun", "purchase gun",
    "firearm for sale", "buy firearm", "sell firearm",
    "ammo for sale", "buy ammo", "sell ammo", "ammunition for sale",
    "silencer for sale", "buy silencer", "suppressor for sale",
    "assault rifle", "ak-47", "ar-15", "glock", "handgun", "rifle for sale",
    "explosive for sale", "buy explosive", "c4", "dynamite", "grenade",
    "weapon for sale", "buy weapon", "sell weapon", "illegal weapon",
]
WEAPON_WORDS.sort(key=len, reverse=True)

# ----- DRUGS (names + slang) -----
DRUG_WORDS = [
    "cocaine", "coke", "crack", "heroin", "H ", "meth", "methamphetamine", "crystal meth", "ice",
    "weed", "cannabis", "marijuana", "ganja", "hash", "cannabis for sale",
    "LSD", "acid", "ecstasy", "mdma", "molly", "ketamine", "ket",
    "fentanyl", "oxy", "oxycodone", "xanax", "valium", "pills for sale",
    "drugs for sale", "buy drugs", "sell drugs", "purchase drugs",
    "stolen goods", "counterfeit", "fake id", "fake passport",
    "laundering", "money laundering",
]
DRUG_WORDS.sort(key=len, reverse=True)

# ----- PROHIBITED PRODUCTS (legacy single words) -----
PROHIBITED_PRODUCTS = [
    "cocaine", "heroin", "meth", "weed", "cannabis", "drugs",
    "weapon", "gun", "firearm", "ammo", "explosive",
    "stolen goods", "counterfeit", "fake id",
]

# ----- DEMANDS / EXTORTION / BLACKMAIL -----
DEMANDS = [
    "ransom", "extortion", "blackmail", "pay or", "pay or else", "pay or i will",
    "wire money", "bitcoin or", "transfer or", "or i will", "or else i will",
    "send bitcoin", "send money or", "pay ransom", "pay me or",
    "i will leak", "i will release", "i will expose", "unless you pay",
    "urgent wire", "wire transfer now", "pay now or",
    "kill you if", "hurt you if", "hurt your family if",
]

# ----- SCAM / FRAUD -----
SCAM_PHRASES = [
    "nigerian prince", "inheritance", "lottery winner", "claim your prize",
    "urgent wire transfer", "send bitcoin to", "western union urgent",
    "verify your account", "suspended account", "click here to verify",
    "password reset", "urgent action required", "act now",
    "congratulations you won", "you have been selected",
]
SCAM_PHRASES.sort(key=len, reverse=True)

# ----- VIOLENCE / THREATS -----
VIOLENCE_PHRASES = [
    "i will kill you", "i will murder you", "i will hurt you",
    "kill yourself", "go kill yourself", "kys", "k y s",
    "bomb the", "bomb threat", "place a bomb", "plant a bomb",
    "shoot you", "shoot them", "gun you down",
    "rape you", "rape them", "gonna rape",
]
VIOLENCE_PHRASES.sort(key=len, reverse=True)

# ----- SELF-HARM (safety flag) -----
SELF_HARM_PHRASES = [
    "how to kill myself", "how to commit suicide", "ways to die",
    "want to die", "want to kill myself", "end my life",
]
SELF_HARM_PHRASES.sort(key=len, reverse=True)


def _replace_case_insensitive(text: str, target: str, replacement: str) -> str:
    return re.sub(re.escape(target), replacement, text, flags=re.IGNORECASE)


def _word_boundary_pattern(word: str) -> re.Pattern:
    """Regex that matches word only as a whole word (not inside another word)."""
    return re.compile(r"\b" + re.escape(word) + r"\b", re.IGNORECASE)


def _replace_word_boundary_insensitive(text: str, target: str, replacement: str) -> str:
    """Replace target only when it appears as a whole word (avoids 'ice' in 'office')."""
    return _word_boundary_pattern(target).sub(replacement, text)


CATEGORY_AI_TOXIC = "ai_toxic"


@dataclass
class CensorResult:
    censored_text: str
    blocked: bool
    detected: list[dict] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)
    extracted_text: Optional[str] = None
    ocr_available: bool = False
    ai_toxic_score: Optional[float] = None
    ai_provider: Optional[str] = None


def _mask_word(word: str) -> str:
    if len(word) <= 2:
        return "**"
    return word[0] + "*" * (len(word) - 1)


def _mask_phrase(phrase: str) -> str:
    return "[REDACTED]"


def _check_phrases(
    text: str,
    lowered: str,
    phrases: list[str],
    category: str,
    use_normalized: bool = False,
) -> tuple[str, bool, list[dict]]:
    clean = text
    detected = []
    norm = _normalize_for_match(text) if use_normalized else lowered
    for phrase in phrases:
        # 1) Evasive: match b.u.y your g.i.r.l, buy-your-girl, etc.
        evasive_pat = _evasive_phrase_pattern(phrase)
        if evasive_pat.search(clean):
            detected.append({"term": phrase, "category": category})
            clean = evasive_pat.sub(_mask_phrase(phrase), clean)
            lowered = clean.lower()
            if use_normalized:
                norm = _normalize_for_match(clean)
            continue
        # 2) Plain substring
        check = _normalize_for_match(phrase) if use_normalized else phrase
        if check not in norm:
            continue
        detected.append({"term": phrase, "category": category})
        clean = _replace_case_insensitive(clean, phrase, _mask_phrase(phrase))
        lowered = clean.lower()
        if use_normalized:
            norm = _normalize_for_match(clean)
    return clean, bool(detected), detected


def _check_and_mask(
    text: str,
    lowered: str,
    word_list: list[str],
    category: str,
    block: bool,
) -> tuple[str, bool, list[dict]]:
    """Match whole words; allow . - _ between letters (d.r.u.g.s, d-r-u-g-s) so evasive spelling is caught."""
    clean = text
    blocked = False
    detected = []
    for word in word_list:
        evasive_pat = _evasive_word_boundary_pattern(word)
        if not evasive_pat.search(clean):
            continue
        detected.append({"term": word, "category": category})
        if block:
            blocked = True
        clean = evasive_pat.sub(_mask_word(word), clean)
    return clean, blocked, detected


def _check_words_and_phrases(
    text: str,
    lowered: str,
    mixed_list: list[str],
    category: str,
    block: bool,
) -> tuple[str, bool, list[dict]]:
    """Single words: word-boundary match. Multi-word phrases: substring match."""
    single_words = [w for w in mixed_list if " " not in w.strip()]
    phrases = [p for p in mixed_list if " " in p]
    clean, blocked, detected = text, False, []
    if single_words:
        clean, blocked, detected = _check_and_mask(clean, clean.lower(), single_words, category, block)
        lowered = clean.lower()
    if phrases:
        c, b, d = _check_phrases(clean, lowered, phrases, category)
        clean, blocked = c, blocked or b
        detected = detected + d
    return clean, blocked, detected


def censor_text_full(
    text: str,
    abusive_words: Optional[list[str]] = None,
    blocked_illegal: Optional[set[str]] = None,
    blocked_phrases: Optional[list[str]] = None,
    exploitation_phrases: Optional[list[str]] = None,
    weapon_words: Optional[list[str]] = None,
    drug_words: Optional[list[str]] = None,
    prohibited_products: Optional[list[str]] = None,
    demands: Optional[list[str]] = None,
    scam_phrases: Optional[list[str]] = None,
    violence_phrases: Optional[list[str]] = None,
    self_harm_phrases: Optional[list[str]] = None,
    use_db_terms: bool = True,
    use_ai_censor: bool = True,
    log_source: str = "",
) -> CensorResult:
    """
    Full censor: DB terms (any language) → built-in lists → AI check. Logs block if source given.
    """
    if not text or not text.strip():
        return CensorResult(censored_text=text or "", blocked=False)

    lowered = text.lower()
    clean = text
    blocked = False
    all_detected: list[dict] = []
    ai_score: Optional[float] = None
    ai_provider: Optional[str] = None

    # 0. DB terms (any language) – phrases then words per category
    if use_db_terms:
        try:
            from .censor_loader import get_offensive_terms_from_db
            db_terms = get_offensive_terms_from_db()
            for slug, term_list in db_terms.items():
                if not term_list:
                    continue
                phrases = [t["term"] for t in term_list if t["term_type"] == "phrase" and t["term"]]
                words = [t["term"] for t in term_list if t["term_type"] == "word" and t["term"]]
                block_cat = any(t.get("is_blocking", True) for t in term_list)
                if phrases:
                    c, b, d = _check_phrases(clean, lowered, phrases, slug, use_normalized=False)
                    clean, blocked = c, blocked or (b and block_cat)
                    all_detected.extend(d)
                    lowered = clean.lower()
                if words:
                    c, b, d = _check_and_mask(clean, lowered, words, slug, block=block_cat)
                    clean, blocked = c, blocked or b
                    all_detected.extend(d)
                    lowered = clean.lower()
        except Exception:
            pass

    blocked_phrases = blocked_phrases or BLOCKED_PHRASES
    exploitation_phrases = exploitation_phrases or EXPLOITATION_PHRASES
    weapon_words = weapon_words or WEAPON_WORDS
    drug_words = drug_words or DRUG_WORDS
    abusive_words = abusive_words or ABUSIVE_WORDS
    blocked_illegal = blocked_illegal or BLOCKED_ILLEGAL
    prohibited_products = prohibited_products or PROHIBITED_PRODUCTS
    demands = demands or DEMANDS
    scam_phrases = scam_phrases or SCAM_PHRASES
    violence_phrases = violence_phrases or VIOLENCE_PHRASES
    self_harm_phrases = self_harm_phrases or SELF_HARM_PHRASES

    # 1. Sexual exploitation first (underage, etc.)
    c, b, d = _check_phrases(clean, lowered, exploitation_phrases, CATEGORY_SEXUAL_EXPLOITATION, use_normalized=False)
    clean, blocked = c, blocked or b
    all_detected.extend(d)
    lowered = clean.lower()

    # 2. Human trafficking phrases (buy/sell people; evasive forms in list)
    c, b, d = _check_phrases(clean, lowered, blocked_phrases, CATEGORY_HUMAN_TRADFFICKING, use_normalized=False)
    clean, blocked = c, blocked or b
    all_detected.extend(d)
    lowered = clean.lower()

    # 3. Violence / threats
    c, b, d = _check_phrases(clean, lowered, violence_phrases, CATEGORY_VIOLENCE)
    clean, blocked = c, blocked or b
    all_detected.extend(d)
    lowered = clean.lower()

    # 4. Weapon phrases/words (single words: whole-word only)
    c, b, d = _check_words_and_phrases(clean, lowered, weapon_words, CATEGORY_WEAPONS, block=True)
    clean, blocked = c, blocked or b
    all_detected.extend(d)
    lowered = clean.lower()

    # 5. Drug phrases/words (single words: whole-word only, e.g. 'ice' not in 'office')
    c, b, d = _check_words_and_phrases(clean, lowered, drug_words, CATEGORY_DRUGS, block=True)
    clean, blocked = c, blocked or b
    all_detected.extend(d)
    lowered = clean.lower()

    # 6. Scam phrases
    c, b, d = _check_phrases(clean, lowered, scam_phrases, CATEGORY_SCAM_FRAUD)
    clean, blocked = c, blocked or b
    all_detected.extend(d)
    lowered = clean.lower()

    # 7. Self-harm (block for safety)
    c, b, d = _check_phrases(clean, lowered, self_harm_phrases, CATEGORY_SELF_HARM)
    clean, blocked = c, blocked or b
    all_detected.extend(d)
    lowered = clean.lower()

    # 8. Demands (extortion etc.)
    c, b, d = _check_and_mask(clean, lowered, demands, CATEGORY_DEMANDS, block=True)
    clean, blocked = c, blocked or b
    all_detected.extend(d)
    lowered = clean.lower()

    # 9. Abusive words (mask, block on severe)
    c, b, d = _check_and_mask(clean, lowered, abusive_words, CATEGORY_ABUSIVE, block=False)
    clean, all_detected = c, all_detected + d
    for x in d:
        if x["term"] in BLOCKED_ILLEGAL or x["term"] in ("kill", "murder", "rape", "pedophile", "paedophile"):
            blocked = True
    lowered = clean.lower()

    # 10. Illegal single terms (whole-word; evasive: k.i.l.l, k-i-l-l)
    for term in blocked_illegal:
        if " " in term:
            pat = _evasive_phrase_pattern(term)
        else:
            pat = _evasive_word_boundary_pattern(term)
        if pat.search(clean):
            all_detected.append({"term": term, "category": CATEGORY_ILLEGAL})
            blocked = True
            clean = pat.sub(_mask_phrase(term) if " " in term else _mask_word(term), clean)
    lowered = clean.lower()

    # 11. Prohibited products (single words)
    c, b, d = _check_and_mask(clean, lowered, prohibited_products, CATEGORY_PROHIBITED_PRODUCTS, block=True)
    clean, blocked = c, blocked or b
    all_detected.extend(d)

    # 12. AI censor (multilingual toxicity)
    if use_ai_censor:
        try:
            from django.conf import settings
            from .censor_loader import ai_censor_check
            if getattr(settings, "CENSOR_AI_ENABLED", True):
                is_toxic, score, provider = ai_censor_check(text)
                if is_toxic and score is not None:
                    ai_score = score
                    ai_provider = provider or "ai"
                    blocked = True
                    all_detected.append({"term": "[AI detected]", "category": CATEGORY_AI_TOXIC})
        except Exception:
            pass

    categories = list({x["category"] for x in all_detected})
    if blocked and log_source:
        try:
            from .censor_loader import log_censor_block
            log_censor_block(
                source=log_source,
                categories=categories,
                detected_terms=[x.get("term", "") for x in all_detected],
                text_preview=text[:500],
                blocked=True,
            )
        except Exception:
            pass

    return CensorResult(
        censored_text=clean,
        blocked=blocked,
        detected=all_detected,
        categories=categories,
        ai_toxic_score=ai_score,
        ai_provider=ai_provider,
    )


def censor_image(
    image_bytes: bytes,
    content_type: Optional[str] = None,
    use_db_terms: bool = True,
    use_ai_censor: bool = True,
    log_source: str = "",
) -> CensorResult:
    """OCR image → text censor on extracted text; if OPENAI_API_KEY set, also run OpenAI Vision on image."""
    extracted = ""
    try:
        import io
        import pytesseract
        from PIL import Image
        img = Image.open(io.BytesIO(image_bytes))
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        extracted = pytesseract.image_to_string(img).strip()
    except Exception:
        pass

    # 1. Text path: if we have OCR text, run full text censor (rules + AI on text)
    if extracted:
        result = censor_text_full(
            extracted,
            use_db_terms=use_db_terms,
            use_ai_censor=use_ai_censor,
            log_source=log_source,
        )
        result.extracted_text = extracted
        result.ocr_available = True
    else:
        result = CensorResult(
            censored_text="",
            blocked=False,
            extracted_text="",
            ocr_available=False,
            detected=[],
            categories=[],
        )

    # 2. OpenAI Vision: image content check (violence, adult, drugs, etc.) when key set
    if use_ai_censor and image_bytes:
        try:
            from django.conf import settings
            from .censor_loader import ai_censor_check_image
            if getattr(settings, "OPENAI_API_KEY", None):
                is_toxic, score, provider = ai_censor_check_image(image_bytes, content_type)
                if is_toxic and provider:
                    result.blocked = True
                    result.detected.append({"term": "[AI image]", "category": CATEGORY_AI_TOXIC})
                    result.categories = list({*result.categories, CATEGORY_AI_TOXIC})
                    result.ai_toxic_score = score
                    result.ai_provider = provider
                    if log_source:
                        from .censor_loader import log_censor_block
                        log_censor_block(
                            source=log_source,
                            categories=result.categories,
                            detected_terms=[x.get("term", "") for x in result.detected],
                            text_preview="[image]",
                            blocked=True,
                        )
        except Exception:
            pass

    return result
