"""
Censor API: text and image censoring endpoints.
POST /censor/text — censor plain text
POST /censor/image — upload image, OCR + censor extracted text
"""
from typing import Optional

from ninja import File, Router, Schema, UploadedFile
from django.conf import settings

from .censor_engine import censor_image, censor_text_full

censor_router = Router(tags=["Censor"])


class TextCensorIn(Schema):
    text: str


class TextCensorOut(Schema):
    censored_text: str
    blocked: bool
    detected: list[dict]
    categories: list[str]
    ai_toxic_score: Optional[float] = None
    ai_provider: Optional[str] = None


class ImageCensorOut(Schema):
    censored_text: str
    blocked: bool
    detected: list[dict]
    categories: list[str]
    extracted_text: Optional[str] = None
    ocr_available: bool
    ai_toxic_score: Optional[float] = None
    ai_provider: Optional[str] = None


@censor_router.post("/text", response={200: TextCensorOut})
def censor_text_endpoint(request, payload: TextCensorIn):
    """
    Censor plain text with OpenAI-first moderation + strict illegal-intent policy checks.
    Returns censored text, blocked flag, detected terms, and categories.
    """
    if not getattr(settings, "OPENAI_API_KEY", None):
        return 200, {
            "censored_text": "[BLOCKED]",
            "blocked": True,
            "detected": [{"term": "[system]", "category": "moderation_unavailable"}],
            "categories": ["moderation_unavailable"],
            "ai_toxic_score": None,
            "ai_provider": None,
        }

    result = censor_text_full(
        payload.text or "",
        # API endpoint is OpenAI policy-first (user requested), no offline lists for this path.
        use_db_terms=False,
        use_builtin_rules=False,
        use_ai_censor=True,
        log_source="api",
    )
    return 200, {
        "censored_text": "[BLOCKED]" if result.blocked else result.censored_text,
        "blocked": result.blocked,
        "detected": result.detected,
        "categories": result.categories,
        "ai_toxic_score": getattr(result, "ai_toxic_score", None),
        "ai_provider": getattr(result, "ai_provider", None),
    }


@censor_router.post("/image", response={200: ImageCensorOut, 400: dict})
def censor_image_endpoint(request, image: UploadedFile = File(...)):
    """
    Upload an image; engine runs OCR to extract text, then censors it.
    Returns censored extracted text, blocked flag, and detected terms.
    Requires Tesseract OCR installed (and pytesseract, Pillow) for OCR; otherwise returns ocr_available=False.
    """
    if not image:
        return 400, {"detail": "No image file provided."}
    content = image.read()
    if not content:
        return 400, {"detail": "Empty image file."}
    result = censor_image(
        content,
        content_type=getattr(image, "content_type", None),
        log_source="api",
    )
    return 200, {
        "censored_text": result.censored_text,
        "blocked": result.blocked,
        "detected": result.detected,
        "categories": result.categories,
        "extracted_text": result.extracted_text,
        "ocr_available": result.ocr_available,
        "ai_toxic_score": getattr(result, "ai_toxic_score", None),
        "ai_provider": getattr(result, "ai_provider", None),
    }
