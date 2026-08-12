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
        orphan = []          # en base, DIT téléchargé, plus découvert → vrai écart
        candidates = []      # en base, NON téléchargé, plus découvert → mémoire VOULUE
        missing = []         # découvert, absent du catalogue

        for key, m in stored.items():
            mi = discovered.get(key)
            if mi is None:
                # Mémoire de catalogue VOULUE (décision Fabien 2026-08-12) : les
                # propositions de prospection (`proposed:*`, jamais sur disque par
                # nature) et les candidats conservés pour une future installation
                # (ex. TTS retirés) ne sont PAS une dérive tant qu'ils ne prétendent
                # pas être téléchargés. Seul « dit téléchargé ET plus découvert »
                # reste un écart réel.
                (candidates if not m.is_downloaded else orphan).append(key)
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
            'candidates_kept': sorted(candidates),
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
                 "dit téléchargé mais plus découvert (supprimé du disque ?)")
        _section("ABSENTS DU CATALOGUE", missing,
                 "découverts mais pas en base (lancer sync_models)")
        if candidates:
            self.stdout.write(
                f"\n(info) CATALOGUE SEUL — mémoire voulue, pas une dérive "
                f"({len(candidates)}) : propositions de prospection et candidats à "
                f"installer.\n  ⚠ un sync_models --clean les PURGERAIT — ne pas le "
                f"lancer pour « corriger » cette section.")

        if nb == 0:
            self.stdout.write(self.style.SUCCESS("\n✓ Catalogue cohérent avec le disque."))
        else:
            self.stdout.write(self.style.ERROR(
                f"\n✗ {nb} écart(s). Corriger via : python manage.py sync_models"))
