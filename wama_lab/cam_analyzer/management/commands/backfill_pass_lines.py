"""Recopie l'historique des passes du Lab (`AnalysisPass`) vers les lignes d'exécution communes
(`common.ProcessRun`) — étape 2a du passage aux lignes communes (ROUTE §10.6 4.1, 2026-10-04).

Non destructif et rejouable : une passe qui a déjà sa ligne commune n'est pas touchée, rien n'est
effacé. À jouer AVANT de basculer les lecteurs sur les lignes communes, sinon les passes jouées avant
l'écriture en double s'afficheraient « jamais lancées ».
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Crée la ligne d'exécution commune de chaque passe du Lab qui n'en a pas encore."

    def add_arguments(self, parser):
        parser.add_argument('--session', action='append', default=None,
                            help='Identifiant de session (répétable) ; toutes par défaut.')

    def handle(self, *args, **options):
        from wama_lab.cam_analyzer.models import AnalysisPass, AnalysisSession
        from wama_lab.cam_analyzer.utils.pass_tracking import backfill_common_lines
        sessions = (AnalysisSession.objects.filter(pk__in=options['session'])
                    if options['session'] else None)
        before = AnalysisPass.objects.count()
        created = backfill_common_lines(sessions)
        self.stdout.write(f"{created} ligne(s) commune(s) créée(s) pour {before} passe(s) du Lab.")
