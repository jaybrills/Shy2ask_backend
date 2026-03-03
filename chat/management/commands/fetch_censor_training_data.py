"""
Fetch training data from internet AI (Google Perspective API) and save to CensorTrainingExample.
Then run: python manage.py train_censor_model
"""
import time

from django.conf import settings
from django.core.management.base import BaseCommand


def _builtin_sample_texts():
    """Built-in sample texts (toxic + safe) to fetch from internet AI and save for training."""
    return [
        "I will kill you",
        "Hello, how are you?",
        "You are stupid and worthless",
        "Thanks for your help today",
        "I hate you and hope you die",
        "Can we meet tomorrow at 5pm?",
        "Buy drugs here",
        "The weather is nice today",
        "Sell your girl to me",
        "Have a great weekend",
        "I want to buy your woman",
        "What time does the store open?",
        "You are a terrible person",
        "Please send the report by Friday",
        "Kill yourself",
        "Looking forward to the meeting",
        "Ransom or I will leak your data",
        "Let me know if you need anything",
        "Underage girl for sale",
        "The project deadline is next week",
        "I will bomb the building",
        "Good morning everyone",
        "Wire money or else",
        "Thanks for the update",
        "Nigerian prince inheritance",
        "See you tomorrow",
    ]


def _google_api_score(text: str) -> tuple[bool, float]:
    """Call Google Perspective API. Returns (is_toxic, score)."""
    api_key = getattr(settings, "PERSPECTIVE_API_KEY", None) or getattr(settings, "CENSOR_AI_API_KEY", None)
    if not api_key:
        return None, None
    threshold = float(getattr(settings, "CENSOR_AI_THRESHOLD", 0.7))
    try:
        import requests
        url = "https://commentanalyzer.googleapis.com/v1alpha1/comments:analyze"
        payload = {
            "comment": {"text": (text or "")[:20480]},
            "languages": ["en", "ar", "hi", "es", "fr", "de", "pt", "ru", "zh", "ja"],
            "requestedAttributes": {
                "TOXICITY": {},
                "SEVERE_TOXICITY": {},
                "THREAT": {},
                "IDENTITY_ATTACK": {},
            },
        }
        r = requests.post(url, params={"key": api_key}, json=payload, timeout=10)
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
        return None, None


class Command(BaseCommand):
    help = "Fetch training data from Google Perspective API (internet AI) and save to CensorTrainingExample. Then run train_censor_model."

    def add_arguments(self, parser):
        parser.add_argument(
            "file",
            nargs="?",
            type=str,
            help="Text file: one text per line. API is called for each line and result saved.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=0,
            help="Max number of lines to process (0 = all).",
        )
        parser.add_argument(
            "--delay",
            type=float,
            default=0.5,
            help="Seconds between API calls to avoid rate limit. Default 0.5.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Only print what would be saved, do not write to DB.",
        )
        parser.add_argument(
            "--samples",
            action="store_true",
            help="Use built-in sample texts (toxic + safe) instead of a file.",
        )

    def handle(self, *args, **options):
        api_key = getattr(settings, "PERSPECTIVE_API_KEY", None) or getattr(settings, "CENSOR_AI_API_KEY", None)
        if not api_key:
            self.stderr.write(self.style.ERROR("Set PERSPECTIVE_API_KEY in env to use Google API."))
            return

        file_path = options.get("file")
        use_samples = options.get("samples", False)

        if use_samples:
            lines = _builtin_sample_texts()
            self.stdout.write(f"Using {len(lines)} built-in sample texts.")
        elif file_path:
            from pathlib import Path
            path = Path(file_path)
            if not path.is_file():
                self.stderr.write(self.style.ERROR(f"File not found: {path}"))
                return
            lines = path.read_text(encoding="utf-8", errors="ignore").strip().splitlines()
            lines = [ln.strip() for ln in lines if ln.strip()]
        else:
            self.stdout.write(
                "Usage:\n"
                "  python manage.py fetch_censor_training_data <file.txt>   # one text per line\n"
                "  python manage.py fetch_censor_training_data --samples    # use built-in samples\n"
                "Then run: python manage.py train_censor_model"
            )
            return

        from chat.models import CensorTrainingExample
        limit = options["limit"] or len(lines)
        if not use_samples:
            lines = [ln.strip() for ln in lines if ln.strip()][:limit]
        else:
            lines = lines[:limit] if limit else lines
        delay = max(0.1, float(options["delay"]))
        dry_run = options["dry_run"]

        saved = 0
        for i, text in enumerate(lines):
            if not text or len(text) < 3:
                continue
            is_toxic, score = _google_api_score(text)
            if is_toxic is None:
                self.stdout.write(self.style.WARNING(f"  Skip (API error): {text[:50]}..."))
                continue
            if not dry_run:
                CensorTrainingExample.objects.create(
                    text=text[:2000],
                    is_toxic=is_toxic,
                    source="google_api",
                    score=score,
                )
                saved += 1
            else:
                self.stdout.write(f"  [{i+1}] toxic={is_toxic} score={score:.2f} | {text[:60]}...")
                saved += 1
            time.sleep(delay)

        self.stdout.write(
            self.style.SUCCESS(
                f"Saved {saved} examples from internet AI (Google API). Run: python manage.py train_censor_model"
            )
        )
