"""Comble les DESCRIPTIONS du catalogue qui ne sont qu'un remplissage de la découverte — la fiche du
modèle (README du Hub), sinon une recherche web, résumée en français par le LLM local par défaut
(`services/model_descriptions.py`). Sans `--apply`, montre ce qui serait écrit et n'écrit rien.

Le résumé charge un modèle sur l'Ollama de l'hôte : une commande lancée à la demande, jamais une
tâche déclenchée par chaque installation (la montée de VRAM a déjà fait tomber la machine,
`tasks.sync_benchmarks_task`).

    python manage.py describe_models --limit 5
    python manage.py describe_models --keys huggingface:allenai/olmOCR-2-7B-1025 --apply
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Comble les descriptions de remplissage depuis la fiche du modèle ou le web."

    def add_arguments(self, parser):
        parser.add_argument('--keys', nargs='*', help='clés de catalogue (défaut : toutes à combler)')
        parser.add_argument('--limit', type=int, default=0, help='au plus N lignes')
        parser.add_argument('--no-web', action='store_true', help='la fiche seule, pas de recherche web')
        parser.add_argument('--user', default='', help='compte dont le moteur de recherche est employé')
        parser.add_argument('--apply', action='store_true', help='écrire (sinon : montrer)')

    def handle(self, *args, **opts):
        from django.contrib.auth import get_user_model

        from wama.model_manager.services.model_descriptions import describe_rows
        user = (get_user_model().objects.filter(username=opts['user']).first()
                if opts['user'] else None)
        results = describe_rows(opts['keys'] or None, apply=opts['apply'],
                                limit=opts['limit'] or None, user=user, web=not opts['no_web'])
        done = 0
        for r in results:
            if r.get('skipped'):
                self.stdout.write(f"  - {r['key']} : {r['skipped']}")
                continue
            done += 1
            self.stdout.write(f"  + {r['key']} [{r['origin']}] {r['short']}\n      {r['long']}")
        mode = 'écrites' if opts['apply'] else 'à blanc, rien écrit'
        self.stdout.write(f"\n{done} description(s) sur {len(results)} ({mode}).")
