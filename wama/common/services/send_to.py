"""ENVOYER VERS — la sortie d'une card devient l'entrée d'une autre app.

Cadré avec Fabien le 2026-09-08 : « la sortie qu'on envoie en entrée d'une autre app, dans l'idée
de faire du chaînage progressif, sans forcément devoir passer par le studio ». Oui — et les trois
pièces existaient déjà, séparément :

  * la SORTIE      : clé canonique `result_file` (+ `result_files`) du schéma de détail
                     (`detail_registry`), déclarée par chaque app ;
  * les DESTINATIONS : registre `IMPORTERS` du gestionnaire de fichiers, qui EST le dispatch ET
                     la source de son menu ;
  * la RÉCEPTION   : l'endpoint `filemanager:api_import`, critère de grille `filemanager_import`
                     **10/10**, tenu par le scénario nocturne `<app>.send_to`.

CE MODULE NE FAIT QUE LES RELIER. Il ne réimplémente NI l'import NI ses gardes : c'est le client
qui POSTe sur l'endpoint existant, lequel revalide `is_path_allowed` et l'accès à l'app. Écrire
un second chemin d'import aurait été la duplication que ce dépôt combat — et la garde de chemin,
recopiée, aurait divergé.

⚠ LA LEÇON DU GESTE 14 EST LE CŒUR DE CE MODULE. Le menu « Envoyer vers… » du gestionnaire de
fichiers a offert pendant des semaines trois apps que le serveur REFUSAIT, avec un critère de
grille vert au-dessus. On ne LISTE donc jamais des apps : on les DÉRIVE de trois conditions qui
doivent toutes tenir — un importeur existe, l'extension est déclarée acceptée, et l'utilisateur a
accès à l'app. Ce qu'on n'offre pas ne peut pas décevoir.
"""
from pathlib import PurePosixPath


def sorties_de(surface: str, instance) -> list:
    """Chemins RELATIFS à `media/` des sorties DÉCLARÉES de cet élément.

    On passe par l'adapter de détail — le même que l'endpoint `unified_detail` — et non par un
    nom de champ : les apps à spec déclarent `result_file`, celles à adapter code ne déclarent
    que leur sortie CANONIQUE. L'adapter est donc le seul accesseur qui les couvre toutes, et
    c'est déjà celui que l'inspecteur consomme.

    ⚠ Il rend des URL (`/media/…`) ; l'endpoint d'import attend des chemins relatifs à
    `MEDIA_ROOT`. On retire donc `MEDIA_URL`, et on ÉCARTE ce qui n'en relève pas (une sortie
    servie par une autre route ne serait pas importable, et un chemin fabriqué à la main
    tomberait de toute façon sur `is_path_allowed`).

    `result_files` (collection) est inclus : l'imager rend N images pour une génération, et
    l'endpoint d'import accepte déjà une LISTE de chemins. Le chaînage porte donc tout le
    résultat, pas son premier fichier.
    """
    from django.conf import settings
    from wama.common.utils.detail_registry import DetailRegistry

    entree = DetailRegistry.get(surface)
    if not entree or not entree.get('adapter'):
        return []
    try:
        detail = entree['adapter'](instance) or {}
    except Exception:
        return []

    prefixe = (settings.MEDIA_URL or '/media/')
    brutes = []
    if detail.get('result_file'):
        brutes.append(detail['result_file'])
    brutes.extend(detail.get('result_files') or [])

    chemins, vus = [], set()
    for url in brutes:
        url = str(url).split('?')[0]
        if not url.startswith(prefixe):
            continue
        rel = url[len(prefixe):].lstrip('/')
        if not rel or rel in vus:
            continue
        vus.add(rel)
        chemins.append(rel)
    return chemins


def destinations(user, chemins) -> list:
    """Apps qui savent RECEVOIR ces fichiers. Trois conditions, toutes nécessaires.

    ① un IMPORTEUR existe (`importer_for` — il couvre aussi les jumelles de bac à sable, qui
       dérivent celui de leur source) ;
    ② l'extension est DÉCLARÉE acceptée (`APP_CATALOG.input_extensions`) — la même source que
       le menu du gestionnaire de fichiers et que sa validation de dossier ;
    ③ l'utilisateur a ACCÈS à l'app (`accessible`) — le menu ne va jamais un cran plus loin que
       le portier de la page.

    Rien n'est offert pour une extension qu'aucune app ne prend : la liste vide est une réponse,
    et l'UI doit la dire au lieu d'ouvrir un sous-menu creux.
    """
    from wama.accounts.permissions import accessible
    from wama.common.app_registry import APP_CATALOG
    from wama.filemanager.views import importer_for, receivable_apps

    extensions = {PurePosixPath(c).suffix.lower() for c in (chemins or []) if c}
    extensions.discard('')
    if not extensions:
        return []

    sortie = []
    for app in receivable_apps(user):
        if importer_for(app) is None:
            continue
        spec = APP_CATALOG.get(app) or {}
        acceptees = {e.lower() if e.startswith('.') else '.' + e.lower()
                     for e in (spec.get('input_extensions') or ())}
        if not acceptees or not extensions <= acceptees:
            # `<=` et non une intersection : on n'offre une app que si elle prend TOUT ce qu'on
            # envoie. Une app qui n'en prendrait qu'une partie produirait un envoi partiel
            # silencieux — l'utilisateur croirait avoir transmis son résultat entier.
            continue
        if not accessible(user, 'app', app):
            continue
        sortie.append({'app': app, 'libelle': spec.get('label') or spec.get('name') or app,
                       'icone': spec.get('icon') or 'fas fa-cube'})
    return sortie
