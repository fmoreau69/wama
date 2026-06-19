"""
Détecteur déterministe de mises à jour de modèles — SANS LLM ni scraping de registre.
N'utilise que des API officielles : Ollama `/api/tags` (local) + huggingface_hub `last_modified`.

  python manage.py check_model_updates                  # rapport (dry-run)
  python manage.py check_model_updates --apply           # + écrit extra_info.update_check
  python manage.py check_model_updates --json
  python manage.py check_model_updates --age-days 90 --no-hf
"""
import json

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = ("Détecteur déterministe de MAJ de modèles (Ollama âge + HF last_modified). "
            "Dry-run par défaut ; --apply pour persister les drapeaux.")

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true',
                            help="Écrire les drapeaux dans extra_info.update_check.")
        parser.add_argument('--json', action='store_true', help="Sortie JSON brute.")
        parser.add_argument('--age-days', type=int, default=120,
                            help="Seuil d'âge Ollama pour 'candidat à revue' (défaut 120).")
        parser.add_argument('--no-hf', action='store_true',
                            help="Ne pas interroger HuggingFace (Ollama local seul).")

    def handle(self, *args, **options):
        from wama.model_manager.services.update_checker import check_updates, apply_flags

        report = check_updates(age_days_threshold=options['age_days'], do_hf=not options['no_hf'])

        if options['json']:
            self.stdout.write(json.dumps(report, indent=2, ensure_ascii=False))
        else:
            self.stdout.write(f"Vérifié : {report['total']} modèle(s)  |  {report['checked_at']}")
            rev, upd = report['ollama_review'], report['hf_updates']
            if rev:
                self.stdout.write(self.style.WARNING(f"\nOLLAMA — candidats à revue ({len(rev)}) :"))
                for r in rev:
                    self.stdout.write(f"  - {r['model_key']} — {r['reason']}")
            if upd:
                self.stdout.write(self.style.WARNING(f"\nHF — mise à jour disponible ({len(upd)}) :"))
                for r in upd:
                    self.stdout.write(f"  - {r['model_key']} — {r['reason']}")
            if not rev and not upd:
                self.stdout.write(self.style.SUCCESS("\n✓ Aucun candidat de MAJ détecté (signal déterministe)."))
            self.stdout.write(self.style.NOTICE(
                "\nNB : signal déterministe uniquement. La prospection/benchmark (agents) viendra "
                "valider ; toute MAJ reste soumise à acceptation admin."))

        if options['apply']:
            n = apply_flags(report)
            self.stdout.write(self.style.SUCCESS(
                f"\n✓ Drapeaux écrits sur {n} modèle(s) (extra_info.update_check)."))
