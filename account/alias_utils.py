import re
import secrets


ADJECTIVES = (
    "Amber",
    "Atlas",
    "Bold",
    "Bright",
    "Calm",
    "Clever",
    "Cloud",
    "Coral",
    "Cosmic",
    "Crimson",
    "Echo",
    "Ember",
    "Golden",
    "Harbor",
    "Hidden",
    "Ivy",
    "Jade",
    "Kind",
    "Lively",
    "Lucky",
    "Maple",
    "Midnight",
    "Misty",
    "Nova",
    "Pixel",
    "Quiet",
    "Rapid",
    "Silver",
    "Solar",
    "Swift",
    "Velvet",
    "Wild",
)

NOUNS = (
    "Aurora",
    "Badger",
    "Bloom",
    "Canyon",
    "Comet",
    "Falcon",
    "Forest",
    "Glider",
    "Harbor",
    "Journey",
    "Lantern",
    "Leaf",
    "Meadow",
    "Meteor",
    "Moon",
    "Oak",
    "Ocean",
    "Panda",
    "Pebble",
    "Phoenix",
    "Pine",
    "River",
    "Robin",
    "Shadow",
    "Spark",
    "Spruce",
    "Star",
    "Stone",
    "Summit",
    "Trail",
    "Wave",
    "Willow",
)


def normalize_alias_name(value):
    return re.sub(r"\s+", " ", (value or "").strip())


def generate_unique_alias_name(
    *,
    alias_exists,
    is_invalid_alias=None,
    reserved_aliases=None,
    max_attempts=256,
):
    reserved_keys = {
        normalized.casefold()
        for alias in (reserved_aliases or [])
        if (normalized := normalize_alias_name(alias))
    }

    for _ in range(max_attempts):
        candidate = _build_random_alias()
        candidate_key = candidate.casefold()
        if candidate_key in reserved_keys or alias_exists(candidate):
            continue
        if is_invalid_alias and is_invalid_alias(candidate):
            continue
        return candidate

    raise RuntimeError("Unable to generate a unique alias name.")


def generate_alias_suggestions(count=3, **kwargs):
    suggestions = []
    reserved_aliases = list(kwargs.pop("reserved_aliases", []) or [])

    while len(suggestions) < count:
        candidate = generate_unique_alias_name(
            reserved_aliases=reserved_aliases,
            **kwargs,
        )
        suggestions.append(candidate)
        reserved_aliases.append(candidate)

    return suggestions


def _build_random_alias():
    adjective = ADJECTIVES[secrets.randbelow(len(ADJECTIVES))]
    noun = NOUNS[secrets.randbelow(len(NOUNS))]
    suffix = 1000 + secrets.randbelow(9000)
    return f"{adjective}{noun}{suffix}"
