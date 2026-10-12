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

    Rend `'écrit'`, ou `SWITCHED_OFF` si `settings.MANIFEST_CORPUS_SYNC` est faux. Lève comme
    la commande : l'appelant garde sa politique d'échec (le corpus est un miroir, il se rattrape
    au prochain export complet)."""
    if not getattr(settings, 'MANIFEST_CORPUS_SYNC', True):
        return SWITCHED_OFF
    from django.core.management import call_command
    call_command('manifest_export', key, kind=kind, verbosity=0)
    return 'écrit'
