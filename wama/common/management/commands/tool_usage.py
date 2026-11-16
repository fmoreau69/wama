"""
`manage.py tool_usage` — ce que les fils de l'assistant disent de ses OUTILS : appels, échecs, durée
médiane, et les erreurs les plus fréquentes (`WAMA_HARNESS §9`, chantier 3 ; `tool_trace.usage`).

Le relevé de l'AUTO-DIAGNOSTIC : par où l'assistant passe, où il bute, et ce que dit l'erreur qui
l'arrête. Lancé à la main, par la page « Exploitation » ou par l'assistant
(`dev_run_operation('tool_usage')`). Lecture seule.

    manage.py tool_usage                 # tout l'historique, outils en échec d'abord
    manage.py tool_usage --days 7        # la dernière semaine
    manage.py tool_usage --family development
    manage.py tool_usage --json
"""
import json

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Appels, échecs et durées des outils de l'assistant, lus dans les fils persistés."

    def add_arguments(self, parser):
        parser.add_argument('--days', type=int, default=None,
                            help="les N derniers jours (tout l'historique sinon)")
        parser.add_argument('--family', default='',
                            help="une famille seule : development, delegation, unknown, "
                                 "transverse, ou l'app qui garde l'outil")
        parser.add_argument('--json', action='store_true', help='sortie machine')

    def handle(self, *args, **options):
        from wama.common.services.tool_trace import FAMILIES, usage

        report = usage(days=options['days'])
        wanted = (options['family'] or '').strip()
        if wanted:
            report['tools'] = [r for r in report['tools'] if r['family'] == wanted]
        if options['json']:
            self.stdout.write(json.dumps(report, ensure_ascii=False, indent=1, default=str))
            return

        span = f"les {options['days']} derniers jours" if options['days'] else 'tout l\'historique'
        self.stdout.write(f"Outils de l'assistant — {span} (depuis {report['since']}) : "
                          f"{report['calls']} appels dans {report['turns']} tours, "
                          f"{report['failures']} en échec.")
        self.stdout.write('')
        self.stdout.write('Par famille :')
        for key, total in sorted(report['families'].items(), key=lambda kv: -kv[1]['calls']):
            self.stdout.write(f"  {FAMILIES.get(key, key):18} {total['tools']:3} outils "
                              f"{total['calls']:5} appels {total['failures']:4} échecs")
        self.stdout.write('')
        self.stdout.write(f"{'outil':34} {'famille':14} {'appels':>6} {'échecs':>6} "
                          f"{'médiane':>8} {'dernier':>10}")
        for row in report['tools']:
            median = f"{row['median_seconds']} s" if row['median_seconds'] is not None else '—'
            self.stdout.write(f"{row['tool']:34} {FAMILIES.get(row['family'], row['family']):14} "
                              f"{row['calls']:6} {row['failures']:6} {median:>8} {row['last']:>10}")
        failing = [r for r in report['tools'] if r['failures']]
        if failing:
            self.stdout.write('')
            self.stdout.write('Ce que disent les échecs (les plus fréquents par outil) :')
            for row in failing:
                for message, count in row['errors']:
                    self.stdout.write(f"  {row['tool']:30} ×{count:<3} {message}")
        self.stdout.write('')
        self.stdout.write(f"Jamais appelés ({len(report['never_called'])}) : "
                          f"{', '.join(report['never_called'])}")
