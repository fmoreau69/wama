"""
Vérifie la cohérence du catalogue AIModel vs la réalité du disque, SANS rien modifier.

Compare l'état découvert (filesystem, via ModelRegistry) à l'état stocké en base et
signale les écarts : faux positifs (catalogue dit téléchargé, disque non), faux négatifs
(disque téléchargé, catalogue non), entrées orphelines (en base, plus découvertes).

Usage :
    python manage.py verify_models          # rapport
    python manage.py verify_models --json    # sortie JSON
"""

import json
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Rapport d'écarts catalogue (AIModel) ↔ disque, sans modification (dry-run)."

    def add_arguments(self, parser):
        parser.add_argument('--json', action='store_true', help="Sortie JSON brute.")

    def handle(self, *args, **options):
        from wama.model_manager.services.model_registry import ModelRegistry
        from wama.model_manager.models import AIModel

        # État découvert (réalité disque)
        registry = ModelRegistry()
        discovered = registry.discover_all_models()

        # État stocké (catalogue)
        stored = {m.model_key: m for m in AIModel.objects.all()}

        false_positive = []  # catalogue=téléchargé, disque=non
        false_negative = []  # disque=téléchargé, catalogue=non
        orphan = []          # en base, plus découvert
        missing = []         # découvert, absent du catalogue

        for key, m in stored.items():
            mi = discovered.get(key)
            if mi is None:
                orphan.append(key)
                continue
            if m.is_downloaded and not mi.is_downloaded:
                false_positive.append(key)
            elif mi.is_downloaded and not m.is_downloaded:
                false_negative.append(key)

        for key in discovered:
            if key not in stored:
                missing.append(key)

        report = {
            'stored_total': len(stored),
            'discovered_total': len(discovered),
            'false_positive': sorted(false_positive),
            'false_negative': sorted(false_negative),
            'orphan': sorted(orphan),
            'missing_from_catalog': sorted(missing),
        }

        if options['json']:
            self.stdout.write(json.dumps(report, indent=2, ensure_ascii=False))
            return

        self.stdout.write(f"Catalogue : {report['stored_total']} entrées | "
                          f"Découvert : {report['discovered_total']}")
        nb = (len(false_positive) + len(false_negative) + len(orphan) + len(missing))

        def _section(title, items, hint):
            if not items:
                return
            self.stdout.write(self.style.WARNING(f"\n{title} ({len(items)}) — {hint}"))
            for k in items:
                self.stdout.write(f"  - {k}")

        _section("FAUX POSITIFS", false_positive,
                 "catalogue dit téléchargé, ABSENT du disque (trompe l'utilisateur)")
        _section("FAUX NÉGATIFS", false_negative,
                 "présent sur disque, catalogue dit non-téléchargé (sous-estime)")
        _section("ORPHELINS", orphan,
                 "en base mais plus découverts (supprimés du disque ?)")
        _section("ABSENTS DU CATALOGUE", missing,
                 "découverts mais pas en base (lancer sync_models)")

        if nb == 0:
            self.stdout.write(self.style.SUCCESS("\n✓ Catalogue cohérent avec le disque."))
        else:
            self.stdout.write(self.style.ERROR(
                f"\n✗ {nb} écart(s). Corriger via : python manage.py sync_models"))
