"""Le corpus de manifestes SUIT le registre à chaud — une seule porte (2026-10-12).

Trois gestes réécrivent un manifeste du corpus (`manifests/`, VERSIONNÉ) pendant que WAMA tourne :
l'installation (`provenance.apply_identity`), la validation d'une proposition de rôle
(`proposals.apply`) et la désinstallation (`model_installer.forget_in_corpus`). Chacun appelait
`manifest_export` à sa façon ; une base de TEST les rejoue sur des clés qui existent au vrai
corpus (`synthesizer:bark`) et aurait réécrit ou effacé un fichier versionné. Le runner de tests
coupe la porte (`MANIFEST_CORPUS_SYNC = False`, `wama/common/runners.py`), comme il redirige
`MEDIA_ROOT` : la protection appartient au HARNAIS, pas à la mémoire de chaque test.

On passe par la commande plutôt que de réécrire la règle de nommage du corpus (`_nom_fichier`) :
une seconde graphie rendrait le glob inverse faux. La commande décide aussi du RETRAIT (modèle
désinstallé ou hors catalogue, `_gone_model_keys`).
"""
from django.conf import settings

#: Ce que rend la porte quand le harnais l'a coupée.
SWITCHED_OFF = 'coupé'


def follow(key: str, kind: str = 'model') -> str:
    """Réexporte `key` au corpus — l'écrit, le réécrit ou le retire selon le registre.

    Un MODÈLE entraîne les apps concernées (2026-11-02, Fabien : « c'est en double sens, une
    correction des applications doit être projetée dans le manifeste aussi ») : celles dont le
    manifeste le cite ou doit le citer (`follow_apps`). Jusque-là, désinstaller olmOCR v1
    retirait son manifeste et laissait celui du Reader le requérir. En TÂCHE DE FOND, après la
    validation de la transaction : le bouton de désinstallation attend sa réponse, et relire les
    apps prend une dizaine de secondes (mesuré : 8,7 s pour les trouver, plus une minute à froid
    pour la première extraction) — le motif de `cloud_models.refresh_key`.

    Rend `'écrit'`, ou `SWITCHED_OFF` si `settings.MANIFEST_CORPUS_SYNC` est faux. Lève comme
    la commande : l'appelant garde sa politique d'échec (le corpus est un miroir, il se rattrape
    au prochain export complet)."""
    if not getattr(settings, 'MANIFEST_CORPUS_SYNC', True):
        return SWITCHED_OFF
    from django.core.management import call_command
    call_command('manifest_export', key, kind=kind, verbosity=0)
    if kind == 'model':
        from django.db import transaction
        from wama.model_manager.tasks import follow_apps_in_corpus_task
        transaction.on_commit(lambda: follow_apps_in_corpus_task.delay(key))
    return 'écrit'


def follow_apps(model_key: str) -> list:
    """Réexporte les manifestes des apps concernées par `model_key` (`apps_concerned`) ; rend
    leurs identifiants. La porte reste celle-ci : coupée par le harnais de tests comme `follow`."""
    if not getattr(settings, 'MANIFEST_CORPUS_SYNC', True):
        return []
    from django.core.management import call_command
    apps = apps_concerned(model_key)
    for app_id in apps:
        call_command('manifest_export', app_id, kind='app', verbosity=0)
    return apps


def apps_concerned(model_key: str) -> list:
    """Les apps RÉELLES dont le manifeste cite `model_key` au corpus (il faut l'en retirer) ou le
    citerait à l'extraction (il faut l'y ajouter) — la facette `models`, `builtin.app._models`.
    Une jumelle du bac à sable n'entre jamais au corpus (`manifest_export`)."""
    import json
    from pathlib import Path

    from wama.common.app_registry import APP_CATALOG
    from wama.common.management.commands.manifest_export import DOSSIERS, _nom_fichier
    from wama.common.manifests.builtin.app import _models
    from wama.common.sandbox import non_sandbox_apps

    folder = Path(settings.BASE_DIR) / DOSSIERS['app']
    out = []
    for app_id in non_sandbox_apps(APP_CATALOG):
        path = folder / f"{_nom_fichier(app_id)}.json"
        try:
            cited = {r.get('key') for r in json.loads(path.read_text(encoding='utf-8'))
                     .get('requires') or [] if isinstance(r, dict) and r.get('kind') == 'model'}
        except (OSError, ValueError):
            cited = set()
        if model_key in cited or model_key in ((_models(app_id) or {}).get('catalog_keys') or []):
            out.append(app_id)
    return out
