ABUSIVE_WORDS = [
    "fuck",
    "bitch",
    "shit",
    "bastard",
    "asshole",
    "threat",
    "kill",
    "murder",
    "rape",
]

BLOCKED_WORDS = {"kill", "murder", "rape"}


def censor_text(text: str):
    """Return (clean_text, blocked) with simple word masking."""
    if not text:
        return text, False
    lowered = text.lower()
    blocked = any(word in lowered for word in BLOCKED_WORDS)
    clean = text
    for word in ABUSIVE_WORDS:
        if word in lowered:
            replacement = word[0] + "***"
            clean = replace_case_insensitive(clean, word, replacement)
    return clean, blocked


def replace_case_insensitive(text: str, target: str, replacement: str):
    import re

    return re.sub(re.escape(target), replacement, text, flags=re.IGNORECASE)

