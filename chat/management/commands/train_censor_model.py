"""
Train our own censor model from CensorTrainingExample (and optional OffensiveTerm).
Saves model to CENSOR_MODEL_PATH (joblib). Use our model first; when it misses, Google API detects and we save → retrain.
"""
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Train censor model from DB (CensorTrainingExample + optional OffensiveTerm). Saves to CENSOR_MODEL_PATH."

    def add_arguments(self, parser):
        parser.add_argument(
            "--min-examples",
            type=int,
            default=50,
            help="Minimum examples (toxic + safe) to train. Default 50.",
        )
        parser.add_argument(
            "--add-offensive-terms",
            action="store_true",
            help="Add OffensiveTerm phrases as synthetic toxic examples.",
        )

    def handle(self, *args, **options):
        try:
            import joblib
            from sklearn.feature_extraction.text import TfidfVectorizer
            from sklearn.linear_model import LogisticRegression
            from sklearn.pipeline import Pipeline
        except ImportError:
            self.stderr.write(self.style.ERROR("Install scikit-learn: pip install scikit-learn"))
            return

        from chat.models import CensorTrainingExample, OffensiveTerm

        qs = CensorTrainingExample.objects.all().order_by("-created_at")
        texts = []
        labels = []
        for ex in qs:
            if ex.text and ex.text.strip():
                texts.append(ex.text.strip()[:2000])
                labels.append(1 if ex.is_toxic else 0)

        if options["add_offensive_terms"]:
            for ot in OffensiveTerm.objects.filter(is_active=True).select_related("category")[:500]:
                t = ot.term.strip()
                if t and len(t) > 2:
                    texts.append(t)
                    labels.append(1)

        if len(texts) < options["min_examples"]:
            self.stdout.write(
                self.style.WARNING(
                    f"Need at least {options['min_examples']} examples, have {len(texts)}. "
                    "Use Google API fallback; when it detects toxic content, examples are saved. Then run train again."
                )
            )
            return

        # Balance: ensure we have both classes
        n_toxic = sum(labels)
        n_safe = len(labels) - n_toxic
        if n_toxic < 5 or n_safe < 5:
            self.stdout.write(
                self.style.WARNING(
                    f"Need both toxic ({n_toxic}) and safe ({n_safe}) examples (min 5 each)."
                )
            )
            return

        pipeline = Pipeline([
            ("tfidf", TfidfVectorizer(max_features=50000, ngram_range=(1, 2), min_df=1)),
            ("clf", LogisticRegression(max_iter=500, class_weight="balanced")),
        ])
        pipeline.fit(texts, labels)

        model_path = getattr(settings, "CENSOR_MODEL_PATH", None)
        if not model_path:
            base = getattr(settings, "MEDIA_ROOT", None) or Path(settings.BASE_DIR) / "media"
            model_path = Path(base) / "censor_model.joblib"
        model_path = Path(model_path)
        model_path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(pipeline, model_path)

        self.stdout.write(
            self.style.SUCCESS(
                f"Trained on {len(texts)} examples (toxic={n_toxic}, safe={n_safe}). Model saved to {model_path}"
            )
        )
