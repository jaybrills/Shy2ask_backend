"""
Censor API: text and image censoring endpoints.
POST /censor/text — censor plain text
POST /censor/image — upload image, OCR + censor extracted text
"""
from typing import Optional

from ninja import File, Router, Schema, UploadedFile

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
    Censor plain text. Uses DB terms (any language) + built-in lists + optional AI.
    Returns censored text, blocked flag, detected terms, and categories.
    """
    result = censor_text_full(
        payload.text or "",
        use_db_terms=True,
        use_ai_censor=True,
        log_source="api",
    )
    return 200, {
        "censored_text": result.censored_text,
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
