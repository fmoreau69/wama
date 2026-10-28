"""
Mesure APRÈS COUP les résultats déjà produits — les mesures sans référence que les process
déclarent (`ProcessSpec.checks`), jouées par la même route qu'au lancement (`run_checks`).

POURQUOI (2026-10-28, décision de Fabien). Les mesures n'existent que depuis le 2026-10-22 et ne se
jouent qu'à la fin d'un lancement : les résultats d'avant n'en portent aucune — mesuré ce jour-là,
AUCUNE ligne d'exécution n'en gardait. Or c'est sur elles que la qualité se compare : un modèle pris
en défaut sur un audio qu'un autre a bien couvert est PROPOSÉ à un administrateur
(`model_quality.propose_defect`). Sans ces mesures, il n'y aurait pas de preuve à proposer.

Générique : toute app dont le pipeline déclare des mesures, tout process qui en déclare. Rien de
propre au transcriber.

Sans `--apply`, rien n'est écrit : la commande compte ce qu'elle mesurerait. Avec `--apply`, chaque
élément passe par `run_checks` — la mesure est gardée sur SA ligne, et un résultat sous le seuil
peut déposer une proposition (jamais un grisage : un administrateur décide).
"""
from django.apps import apps as django_apps
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Joue les mesures sans référence déclarées sur les résultats déjà produits (amorce des preuves de qualité)."

    def add_arguments(self, parser):
        parser.add_argument('--app', action='append', default=[],
                            help="app à mesurer (répétable) ; toutes celles qui déclarent des mesures sinon")
        parser.add_argument('--remeasure', action='store_true',
                            help="remesurer aussi les lignes qui portent déjà leurs mesures")
        parser.add_argument('--limit', type=int, default=0, help="au plus N éléments par app")
        parser.add_argument('--apply', action='store_true', help="mesurer et garder (sinon : compter)")

    def handle(self, *args, **opts):
        from wama.common.models import JOB_SUCCESS, ProcessRun
        from wama.common.services.process_pipeline import app_pipeline
        from wama.common.services.result_evaluation import run_checks

        labels = opts['app'] or [c.label for c in django_apps.get_app_configs()]
        total = 0
        for app in labels:
            pipeline = app_pipeline(app)
            nodes = [s.key for s in (pipeline.specs if pipeline else ()) if s.checks]
            if not nodes:
                continue
            lines = ProcessRun.objects.filter(app=app, node_id__in=nodes, status=JOB_SUCCESS)
            if not opts['remeasure']:
                lines = lines.exclude(output_summary__has_key='checks')
            targets = sorted({(t, i) for t, i in lines.values_list('object_type', 'object_id')})
            if opts['limit']:
                targets = targets[:opts['limit']]
            measured = 0
            for object_type, object_id in targets:
                if not opts['apply']:
                    continue
                try:
                    model = django_apps.get_model(app, object_type)
                    item = model._base_manager.filter(pk=object_id).first()
                except (LookupError, ValueError):
                    continue
                if item is not None and run_checks(app, item):
                    measured += 1
            total += len(targets)
            verb = f"{measured} mesuré(s)" if opts['apply'] else "à mesurer (--apply pour le faire)"
            self.stdout.write(f"{app} [{', '.join(nodes)}] : {len(targets)} élément(s), {verb}")
        if not total:
            self.stdout.write("Rien à mesurer.")
