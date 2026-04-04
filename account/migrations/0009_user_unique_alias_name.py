import re
import secrets
from difflib import SequenceMatcher

from django.db import migrations, models
from django.db.models.functions import Lower


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


def normalize_name_for_comparison(value):
    return re.sub(r"[^a-z0-9]+", "", (value or "").lower())


def tokenize_name(value):
    return [part for part in re.split(r"[^a-z0-9]+", (value or "").lower()) if part]


def ratio(left, right):
    return int(SequenceMatcher(None, left, right).ratio() * 100)


def partial_ratio(left, right):
    if not left or not right:
        return 0

    shorter, longer = (left, right) if len(left) <= len(right) else (right, left)
    if shorter == longer:
        return 100

    window = len(shorter)
    best = 0
    for start in range(0, len(longer) - window + 1):
        best = max(best, ratio(shorter, longer[start : start + window]))
        if best == 100:
            return best
    return best


def token_sort_ratio(left, right):
    left_tokens = " ".join(sorted(tokenize_name(left)))
    right_tokens = " ".join(sorted(tokenize_name(right)))
    return ratio(left_tokens, right_tokens)


def is_strict_name_match(alias, candidate):
    if not alias or not candidate:
        return False
    if alias == candidate:
        return True
    if len(alias) >= 4 and alias in candidate:
        return True
    if len(candidate) >= 4 and candidate in alias:
        return True
    return (
        ratio(alias, candidate) >= 80
        or partial_ratio(alias, candidate) >= 90
        or token_sort_ratio(alias, candidate) >= 85
    )


def tokens_match_real_name(alias_tokens, name_tokens):
    if not alias_tokens or not name_tokens or len(alias_tokens) > len(name_tokens):
        return False

    matched = 0
    for alias_token, name_token in zip(alias_tokens, name_tokens):
        if alias_token == name_token:
            matched += 1
            continue
        if len(alias_token) == 1 and name_token.startswith(alias_token):
            matched += 1
            continue
        if len(alias_token) >= 3 and name_token.startswith(alias_token):
            matched += 1
            continue
        if is_strict_name_match(alias_token, name_token):
            matched += 1

    return matched == len(alias_tokens)


def compact_alias_matches_token_sequence(alias, name_tokens):
    if not alias or len(name_tokens) < 2:
        return False

    normalized_tokens = [normalize_name_for_comparison(token) for token in name_tokens if token]
    if len(normalized_tokens) < 2:
        return False

    min_prefix_len = 3

    def search(start_index, token_index, has_substantial_piece):
        current_token = normalized_tokens[token_index]
        remaining_tokens = len(normalized_tokens) - token_index - 1

        if start_index >= len(alias):
            return False

        max_end = len(alias) - remaining_tokens
        piece_lengths = []
        if alias[start_index] == current_token[0]:
            piece_lengths.append(1)

        min_end = start_index + min_prefix_len
        for end_index in range(min_end, max_end + 1):
            piece = alias[start_index:end_index]
            if current_token.startswith(piece) or is_strict_name_match(piece, current_token):
                piece_lengths.append(len(piece))

        for piece_length in sorted(set(piece_lengths)):
            next_index = start_index + piece_length
            next_has_substantial_piece = has_substantial_piece or piece_length >= min_prefix_len
            if token_index == len(normalized_tokens) - 1:
                if next_index == len(alias) and next_has_substantial_piece:
                    return True
                continue
            if search(next_index, token_index + 1, next_has_substantial_piece):
                return True
        return False

    return search(0, 0, False)


def compact_alias_matches_name_tokens(alias, name_tokens):
    if not alias or len(name_tokens) < 2:
        return False

    sequences = [name_tokens]
    reversed_tokens = list(reversed(name_tokens))
    if reversed_tokens != list(name_tokens):
        sequences.append(reversed_tokens)
    return any(compact_alias_matches_token_sequence(alias, sequence) for sequence in sequences)


def alias_matches_real_name(alias_name, first_name, last_name):
    raw_alias = normalize_alias_name(alias_name)
    alias = normalize_name_for_comparison(raw_alias)
    if not alias:
        return False

    candidates = {
        normalize_name_for_comparison(first_name),
        normalize_name_for_comparison(last_name),
        normalize_name_for_comparison(f"{first_name} {last_name}"),
    }
    candidates.discard("")

    for candidate in candidates:
        if is_strict_name_match(alias, candidate):
            return True

    alias_tokens = tokenize_name(raw_alias)
    token_candidates = [
        tokenize_name(first_name),
        tokenize_name(last_name),
        tokenize_name(f"{first_name} {last_name}"),
    ]
    return any(
        tokens_match_real_name(alias_tokens, tokens)
        or compact_alias_matches_name_tokens(alias, tokens)
        for tokens in token_candidates
    )


def build_random_alias():
    adjective = ADJECTIVES[secrets.randbelow(len(ADJECTIVES))]
    noun = NOUNS[secrets.randbelow(len(NOUNS))]
    suffix = 1000 + secrets.randbelow(9000)
    return f"{adjective}{noun}{suffix}"


def generate_unique_alias(user_model, user, reserved_aliases):
    for _ in range(256):
        candidate = build_random_alias()
        candidate_key = candidate.casefold()
        if candidate_key in reserved_aliases:
            continue
        if alias_matches_real_name(candidate, user.first_name, user.last_name):
            continue
        if user_model.objects.filter(alias_name__iexact=candidate).exclude(pk=user.pk).exists():
            continue
        return candidate
    raise RuntimeError("Unable to generate a unique alias name during migration.")


def backfill_unique_aliases(apps, schema_editor):
    User = apps.get_model("account", "User")
    reserved_aliases = set()

    for user in User.objects.all().order_by("id"):
        current_alias = normalize_alias_name(user.alias_name)
        alias_key = current_alias.casefold() if current_alias else ""
        should_regenerate = (
            not current_alias
            or alias_key in reserved_aliases
            or alias_matches_real_name(current_alias, user.first_name, user.last_name)
        )

        if should_regenerate:
            current_alias = generate_unique_alias(User, user, reserved_aliases)

        reserved_aliases.add(current_alias.casefold())
        if user.alias_name != current_alias:
            User.objects.filter(pk=user.pk).update(alias_name=current_alias)


class Migration(migrations.Migration):

    dependencies = [
        ("account", "0008_activeuser_pendingverificationuser"),
    ]

    operations = [
        migrations.RunPython(backfill_unique_aliases, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="user",
            name="alias_name",
            field=models.CharField(
                help_text="Unique display name or nickname. Auto-generated when omitted.",
                max_length=150,
                verbose_name="alias name",
            ),
        ),
        migrations.AddConstraint(
            model_name="user",
            constraint=models.UniqueConstraint(Lower("alias_name"), name="account_user_alias_name_ci_unique"),
        ),
    ]
