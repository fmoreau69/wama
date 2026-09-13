"""
Scénario nocturne `output` du studio — un pipeline RÉEL de bout en bout.

Né du smoke du 2026-08-03 : l'interblocage runner↔converter (même file `default` en pool
solo) n'était détectable QUE par une exécution réelle — ce scénario l'aurait attrapé la
nuit de sa naissance. Chaîne exercée : media_import → converter (execute_tool, file
`default`) → studio_output (médiathèque), orchestrée par run_pipeline_task (file `studio`).

CPU seul (ffmpeg) ; l'entrée est un wav de 1 s généré sur place. Nettoyage par IDs précis
(règle de la charpente) : run, job converter et asset créés sont supprimés en `finally`.
"""
import os

from wama.common.services.nightly_tests import SkipScenario, register

#: La fixture vit CHEZ LE COMPTE DE TEST (`users/<uid>/temp/`), nommée en témoin
#: (`wama_temoin_*`) : c'est la zone que le balayage `sweep_test_witnesses` couvre, et la seule
#: où un test a le droit d'écrire dans `media/` — le nocturne passe par le serveur VIVANT, donc
#: par le vrai `MEDIA_ROOT` (le nœud `media_import` confine `asset_path` sous cette racine).
#: Jusqu'au 2026-09-13 elle vivait à `media/nightly_tests/` : un dossier de test à la RACINE du
#: média de production, signalé « égaré » par `check_media_integrity` et exclu à la main par
#: `migrate_media_to_user_home` — deux exceptions pour un fichier de 1 s.
_ENTREE_NOM = 'wama_temoin_studio_sine_1s.wav'


def _entree(media_root, user):
    """Wav sinus 1 s, généré via le ffmpeg CENTRALISÉ (ffmpeg_utils) ; rend le chemin RELATIF."""
    rel = f'users/{user.pk}/temp/{_ENTREE_NOM}'
    abs_path = os.path.join(media_root, rel)
    if not os.path.exists(abs_path):
        import subprocess
        from wama.common.utils.ffmpeg_utils import get_ffmpeg_exe
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        subprocess.run([get_ffmpeg_exe(), '-y', '-f', 'lavfi', '-i',
                        'sine=frequency=440:duration=1', abs_path],
                       check=True, capture_output=True, timeout=60)
    return rel


def _worker_default_present():
    from celery import current_app
    try:
        reponses = current_app.control.ping(timeout=3) or []
    except Exception:
        return False
    return any(str(list(r)[0]).startswith('default@') for r in reponses)


def _run_pipeline_end_to_end(ctx):
    from django.conf import settings
    from wama.media_library.models import UserAsset
    from wama.studio.models import StudioRun
    from wama.studio.tasks import run_pipeline_task

    user = ctx['user']
    if not _worker_default_present():
        raise SkipScenario('aucun worker sur la file default (converter) — pile arrêtée ?')

    rel = _entree(settings.MEDIA_ROOT, user)
    nom_sortie = f'nightly-studio-{user.pk}'
    graph = {
        'nodes': [
            {'id': 'n1', 'app': 'media_import',
             'params': {'asset_path': rel, 'asset_category': 'audio'}},
            {'id': 'n2', 'app': 'converter',
             'params': {'output_format': 'mp3', 'channels': '1'}},
            {'id': 'n3', 'app': 'studio_output',
             'params': {'asset_type': 'audio', 'asset_name': nom_sortie}},
        ],
        'links': [{'from': 'n1', 'to': 'n2'}, {'from': 'n2', 'to': 'n3'}],
    }
    run = StudioRun.objects.create(user=user, graph=graph)
    try:
        # Appel DIRECT (in-process) : l'orchestration s'exécute ici, la tâche converter
        # part réellement en file `default` — c'est elle que le scénario surveille.
        run_pipeline_task(run.pk)
        run.refresh_from_db()
        if run.status != 'SUCCESS':
            return False, f"run #{run.pk} {run.status} — {(run.error_message or '')[:200]}"
        asset = UserAsset.objects.filter(user=user, name__startswith=nom_sortie).first()
        if not asset or not os.path.exists(asset.file.path):
            return False, f"run #{run.pk} SUCCESS mais asset de sortie introuvable"
        return True, (f"run #{run.pk} SUCCESS en {run.processing_seconds or 0:.1f}s, "
                      f"sortie {os.path.basename(asset.file.name)}")
    finally:
        # Nettoyage par IDs précis : uniquement ce que CE run a créé.
        from wama.converter.models import ConversionJob
        etats = run.node_states or {}
        job_id = (etats.get('n2') or {}).get('item_id')
        if job_id:
            for job in ConversionJob.objects.filter(pk=job_id, user=user):
                try:
                    job.output_file and job.output_file.delete(save=False)
                    job.original_file and job.original_file.delete(save=False)
                except Exception:
                    pass
                job.delete()
        for asset in UserAsset.objects.filter(user=user, name__startswith=nom_sortie):
            try:
                asset.file.delete(save=False)
            except Exception:
                pass
            asset.delete()
        run.delete()


def register_scenarios():
    register(id='studio.pipeline.converter', app='studio', stage='output',
             description='Pipeline réel media_import → converter → médiathèque '
                         '(orchestration file studio, tâche app file default)',
             run=_run_pipeline_end_to_end, timeout_s=300)
