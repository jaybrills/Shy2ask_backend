"""Seed default censor categories so admins can add offensive terms (any language)."""
from django.core.management.base import BaseCommand

from chat.models import CensorCategory


DEFAULT_CATEGORIES = [
    ("abusive", "Abusive / Profanity", "Profanity, slurs, hate speech"),
    ("illegal", "Illegal", "Illegal activity, terrorism, hitman"),
    ("human_trafficking", "Human Trafficking", "Buy/sell people, trafficking"),
    ("sexual_exploitation", "Sexual Exploitation", "Underage, child abuse"),
    ("weapons", "Weapons", "Guns, explosives, ammo"),
    ("drugs", "Drugs", "Drug names, drug dealing"),
    ("violence", "Violence / Threats", "Threats, kill, bomb"),
    ("demands", "Demands / Extortion", "Ransom, blackmail, extortion"),
    ("scam_fraud", "Scam / Fraud", "Scam phrases, fraud"),
    ("self_harm", "Self-Harm", "Suicide, self-harm (safety)"),
    ("prohibited_products", "Prohibited Products", "Stolen goods, counterfeit"),
    ("hate", "Hate Speech", "Hate speech, any language"),
]


class Command(BaseCommand):
    help = "Create default CensorCategory records so you can add OffensiveTerm in any language."

    def handle(self, *args, **options):
        created = 0
        for slug, name, desc in DEFAULT_CATEGORIES:
            _, was_created = CensorCategory.objects.get_or_create(
                slug=slug,
                defaults={"name": name, "description": desc, "is_blocking": True},
            )
            if was_created:
                created += 1
        self.stdout.write(self.style.SUCCESS(f"Seeded censor categories. Created {created} new."))
