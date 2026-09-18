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
from urllib.parse import unquote

#: Candidats relus par élément quand une requête en rend plusieurs (un même nom de fichier
#: peut apparaître dans le JSON de N générations) — borne, jamais un balayage de la table.
_CANDIDATS_MAX = 20


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


def _requete_candidats(model, chemin: str):
    """La requête qui SÉLECTIONNE les candidats sans connaître l'app : un `FileField` égal au
    chemin (9 apps sur 10 rangent leur sortie ainsi), ou un `JSONField` qui CONTIENT le nom du
    fichier (l'imager garde ses images en JSON, sous forme de chemins absolus). `None` si le
    modèle ne porte aucun des deux — il n'a alors pas de sortie fichier à retrouver."""
    from django.db.models import FileField, JSONField, Q

    nom = PurePosixPath(chemin).name
    q = None
    for f in model._meta.get_fields():
        if isinstance(f, FileField):
            clause = Q(**{f.name: chemin})
        elif isinstance(f, JSONField) and nom:
            clause = Q(**{f'{f.name}__icontains': nom})
        else:
            continue
        q = clause if q is None else (q | clause)
    return q


def item_for_output_path(user, chemin: str):
    """L'élément dont `chemin` (relatif à `media/`) est une SORTIE déclarée — `(surface,
    instance)`, ou `(None, None)`.

    L'INVERSE de `sorties_de`, pour l'arbre de fichiers (2026-09-18, demande de Fabien : les
    gestes du menu « … » — partager, ranger en médiathèque, ajouter au RAG — sur un fichier de
    l'arbre). Ces gestes sont définis sur un ÉLÉMENT, jamais sur un chemin : un fichier de
    l'arbre ne les obtient donc qu'en remontant à l'élément qui l'a produit, et c'est alors
    EXACTEMENT le menu de sa card qui s'ouvre — mêmes endpoints, mêmes refus.

    Deux temps, et c'est le second qui fait foi :
      ① CANDIDATS par requête (`_requete_candidats`), sans connaissance d'app ;
      ② CONFIRMATION par `sorties_de` — l'adapter de détail, la seule source qui dise ce qu'un
         élément DÉCLARE comme sortie. Un fichier qui n'est qu'une ENTRÉE d'élément (même
         référencé par un `FileField`) n'est pas rendu : partager « ce fichier » ouvrirait alors
         le partage d'un élément dont il n'est pas le résultat.

    ⚠ Périmètre de l'UTILISATEUR : on ne cherche que parmi SES éléments (un modèle sans champ
    `user` est ignoré — il n'a pas de propriétaire à qui offrir le geste). Un chemin étranger
    rend donc `(None, None)`, comme `api_partage` rend 404 et non 403.
    ⚠ Une surface n'est rendue que si les DEUX registres la connaissent (détail ET preview) :
    ce sont les coordonnées qu'une card porte (`data-preview-url`), celles que partage,
    médiathèque et RAG consomment. `sorties_de` rend des URL DÉCODÉES ici (`unquote`) : le
    chemin de l'arbre est brut, l'URL d'un `FieldFile` est percent-encodée.
    """
    from wama.common.utils.detail_registry import DetailRegistry
    from wama.common.utils.preview_registry import PreviewRegistry

    chemin = (chemin or '').replace('\\', '/').lstrip('/')
    if not chemin or user is None or not getattr(user, 'is_authenticated', False):
        return None, None

    for surface in DetailRegistry.registered_apps():
        entree = DetailRegistry.get(surface) or {}
        model = entree.get('model')
        if model is None or PreviewRegistry.get_model(surface) is not model:
            continue
        try:
            model._meta.get_field('user')
        except Exception:
            continue
        q = _requete_candidats(model, chemin)
        if q is None:
            continue
        try:
            candidats = list(model._default_manager.filter(q, user=user)
                             .order_by('-pk')[:_CANDIDATS_MAX])
        except Exception:
            continue
        for instance in candidats:
            if chemin in {unquote(s) for s in sorties_de(surface, instance)}:
                return surface, instance
    return None, None


def _apps_receveuses(user):
    """`(app, spec)` des apps que CET utilisateur peut remplir : ① un IMPORTEUR existe
    (`importer_for` — il couvre aussi les jumelles de bac à sable, qui dérivent celui de leur
    source) et ③ il a ACCÈS à l'app (`accessible`) — le menu ne va jamais un cran plus loin que le
    portier de la page. La condition ② (extensions) dépend de ce qu'on envoie : aux appelants."""
    from wama.accounts.permissions import accessible
    from wama.common.app_registry import APP_CATALOG
    from wama.filemanager.views import importer_for, receivable_apps

    for app in receivable_apps(user):
        if importer_for(app) is None:
            continue
        if not accessible(user, 'app', app):
            continue
        yield app, (APP_CATALOG.get(app) or {})


def _destination(app, spec, **extra) -> dict:
    return {'app': app, 'libelle': spec.get('label') or spec.get('name') or app,
            'icone': spec.get('icon') or 'fas fa-cube', **extra}


def destinations(user, chemins, partiel: bool = False) -> list:
    """Apps qui savent RECEVOIR ces fichiers. Trois conditions, toutes nécessaires.

    ① un IMPORTEUR existe et ③ l'utilisateur a ACCÈS à l'app (`_apps_receveuses`) ;
    ② l'extension est DÉCLARÉE acceptée (`APP_CATALOG.input_extensions`) — la même source que
       la validation de dossier de l'import.

    Chaque destination porte `acceptes` : les chemins qu'elle prend.
    `partiel=False` (une SORTIE de card) : une app n'est offerte que si elle prend TOUT — un envoi
    partiel silencieux ferait croire le résultat entier transmis. `partiel=True` (une SÉLECTION
    de l'arbre de fichiers, 2026-09-14) : une app qui en prend une partie est offerte, et le menu
    DIT combien — un envoi partiel ANNONCÉ n'est plus silencieux.

    Rien n'est offert pour une extension qu'aucune app ne prend : la liste vide est une réponse,
    et l'UI doit la dire au lieu d'ouvrir un sous-menu creux.
    """
    avec_extension = [c for c in (chemins or []) if c and PurePosixPath(c).suffix]
    if not avec_extension:
        return []

    sortie = []
    for app, spec in _apps_receveuses(user):
        acceptees = {e.lower() if e.startswith('.') else '.' + e.lower()
                     for e in (spec.get('input_extensions') or ())}
        acceptes = [c for c in avec_extension if PurePosixPath(c).suffix.lower() in acceptees]
        if not acceptes:
            continue
        if not partiel and len(acceptes) < len(avec_extension):
            continue
        sortie.append(_destination(app, spec, acceptes=acceptes))
    return sortie


def destinations_dossier(user) -> list:
    """Apps qui savent recevoir un DOSSIER entier : importeur + accès (`_apps_receveuses`).

    L'extension d'un fichier précis ne se juge PAS ici : l'import étend le dossier et filtre par
    `input_extensions` côté serveur, puis DIT « aucun fichier compatible ». Parcourir récursivement
    un dossier — un montage réseau, parfois — pour construire un menu coûterait plus que le geste.

    ⚠ Mais une app qui ne DÉCLARE aucune extension n'est pas offerte : son import ne retiendrait
    jamais rien. Mesuré à la sonde du 2026-09-14 — `cam_analyzer` et `face_analyzer` (importeur,
    aucune `input_extensions`) apparaissaient au sous-menu, sous leur nom brut.
    """
    return [_destination(app, spec) for app, spec in _apps_receveuses(user)
            if spec.get('input_extensions')]
