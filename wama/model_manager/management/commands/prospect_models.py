"""
Prospection DÉTERMINISTE de modèles (HF Hub API officielle) — socle du système de veille.
Liste les modèles notables d'une tâche et signale ceux que WAMA possède déjà. Dry-run :
aucune installation, aucune écriture. La couche multi-agents viendra par-dessus.

  python manage.py prospect_models --app imager
  python manage.py prospect_models --task automatic-speech-recognition --limit 20
  python manage.py prospect_models --app describer --new-only --json
"""
import json

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Prospection deterministe de modeles via HuggingFace Hub (dry-run, rien n'est installe)."

    def add_arguments(self, parser):
        parser.add_argument('--app', help="App WAMA (imager, video, transcriber, synthesizer, describer, anonymizer, enhancer).")
        parser.add_argument('--task', help="Tache HF brute (prioritaire sur --app).")
        parser.add_argument('--limit', type=int, default=15)
        parser.add_argument('--min-downloads', type=int, default=0)
        parser.add_argument('--library', help="Filtre de librairie HF (ex: diffusers, transformers).")
        parser.add_argument('--new-only', action='store_true', help="Masquer ce que WAMA possede deja.")
        parser.add_argument('--json', action='store_true')

    def handle(self, *args, **options):
        from wama.model_manager.services.prospector import prospect_hf, APP_TASKS

        task = options.get('task')
        if not task:
            app = options.get('app')
            if not app:
                raise CommandError("Preciser --task ou --app.")
            task = APP_TASKS.get(app)
            if not task:
                raise CommandError(f"App inconnue '{app}'. Connues : {', '.join(APP_TASKS)}.")

        res = prospect_hf(task, limit=options['limit'],
                          library=options.get('library'),
                          min_downloads=options['min_downloads'])
        if not res.get('ok'):
            self.stderr.write(self.style.ERROR(f"✗ {res.get('error')}"))
            return

        cands = res['candidates']
        if options['new_only']:
            cands = [c for c in cands if not c['have']]

        if options['json']:
            self.stdout.write(json.dumps({**res, 'candidates': cands}, indent=2, ensure_ascii=False))
            return

        self.stdout.write(f"Prospection HF — tache « {res['task']} » — {len(cands)} candidat(s) :")
        for c in cands:
            mark = '✓ déjà' if c['have'] else '★ NOUVEAU'
            dl = c['downloads']
            dls = f"{dl/1e6:.1f}M" if dl >= 1e6 else (f"{dl/1e3:.0f}k" if dl >= 1e3 else str(dl))
            self.stdout.write(f"  [{mark:9s}] {c['hf_id']:55s} ⬇{dls:>6s}  ♥{c['likes']}")
        self.stdout.write(self.style.NOTICE(
            "\nSignal déterministe (popularité). La confrontation benchmarks/avis (agents) viendra "
            "par-dessus ; toute integration reste soumise a acceptation admin."))
