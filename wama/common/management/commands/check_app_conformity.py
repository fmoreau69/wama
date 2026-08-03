"""check_app_conformity — mesure RÉELLE de la conformité des apps génériques.

Usage :
    python manage.py check_app_conformity              # les 10 apps, écrit le rapport JSON
    python manage.py check_app_conformity --app reader # une seule app, détail complet
    python manage.py check_app_conformity --no-write   # dry-run (pas de rapport écrit)

Le rapport (logs/conformity_report.json) est fusionné automatiquement par
`get_conformity_summary()` : les valeurs MESURÉES écrasent les booléens déclarés
de `_conv(...)` sur `/apps/` et dans l'inspecteur d'app.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from wama.common.app_registry import APP_CATALOG
from wama.common.services.conformity_checker import CRITERIA, run_checks

REPORT_PATH = Path(settings.BASE_DIR) / 'logs' / 'conformity_report.json'

STATE_FMT = {True: '✅', 'partial': '🔶', False: '❌'}


class Command(BaseCommand):
    help = "Vérifie la conformité des apps par analyse du code réel (facettes F1-F8) et met à jour la grille."

    def add_arguments(self, parser):
        parser.add_argument('--app', help='Limiter à une app (ex. reader)')
        parser.add_argument('--no-write', action='store_true', help='Ne pas écrire le rapport JSON')
        parser.add_argument('--verbose-ok', action='store_true', help='Afficher aussi les critères conformes')

    def handle(self, *args, **opts):
        apps = [opts['app']] if opts.get('app') else sorted(APP_CATALOG.keys())
        # Run COMPLET avec écriture → brique commune (partagée avec le bouton /apps/) ;
        # run partiel ou --no-write → mesure seule, la photo globale est préservée.
        if not opts.get('app') and not opts.get('no_write'):
            from wama.common.app_registry import measure_and_write_conformity
            report = measure_and_write_conformity()
        else:
            report = run_checks(apps)
            report['generated_at'] = datetime.now(timezone.utc).isoformat(timespec='seconds')

        for app in apps:
            data = report['apps'][app]
            self.stdout.write(self.style.MIGRATE_HEADING(
                f"\n{app.upper()} — {data['score']}✅ / {data['partial']}🔶 / "
                f"{data['total'] - data['score'] - data['partial']}❌ sur {data['total']} → {data['pct']} %"))
            for c in CRITERIA:
                state = data['conv'].get(c.key)
                if state is None:
                    continue
                if state is True and not opts.get('verbose_ok'):
                    continue
                ev = data['evidence'].get(c.key) or ''
                self.stdout.write(f"  {STATE_FMT[state]} [{c.facette}] {c.key:24s} {c.label}"
                                  + (f"\n       ↳ {ev}" if ev else ''))

        if not opts.get('no_write'):
            # Rapport COMPLET seulement (les 10 apps) — un run partiel ne doit pas
            # écraser la photo globale consommée par /apps/.
            if opts.get('app'):
                self.stdout.write(self.style.WARNING(
                    "\nRun partiel (--app) : rapport JSON NON écrit (photo globale préservée)."))
            else:
                # écriture déjà faite par la brique measure_and_write_conformity
                self.stdout.write(self.style.SUCCESS(f"\nRapport écrit → {REPORT_PATH}"))
