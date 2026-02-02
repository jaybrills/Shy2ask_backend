"""
Text censoring: delegates to censor_engine so chat messages use the same rules as the API.
"""
from .censor_engine import ABUSIVE_WORDS, BLOCKED_ILLEGAL, censor_text_full

# Re-export for code that still references these
BLOCKED_WORDS = BLOCKED_ILLEGAL


def replace_case_insensitive(text: str, target: str, replacement: str):
    import re
    return re.sub(re.escape(target), replacement, text, flags=re.IGNORECASE)


def censor_text(text: str):
    """Return (clean_text, blocked) for use in Message.save() etc."""
    if not text:
        return text, False
    result = censor_text_full(text)
    return result.censored_text, result.blocked

