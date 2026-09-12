"""
Le GESTE « ranger une sortie d'app dans ma médiathèque » — brique COMMUNE.

POURQUOI cette brique existe (mesuré le 2026-09-11). Le geste existait déjà, mais **écrit trois
fois** et seulement dans 2 apps sur 10 :
  • `composer/views.py:669` (`export_to_library`) et sa jumelle `composer_01` ;
  • `synthesizer/views.py:897` (création d'asset `voice` en ligne, encore autrement).
C'est exactement la duplication que la règle `common/` vise — et la conséquence est pire qu'une
redite : **huit apps n'ont pas le geste du tout**.

⭐ CE QUE CETTE BRIQUE FAIT MIEUX QUE LES TROIS COPIES : elle **ne construit aucun chemin**. La
version composer fabrique `media_library/<uid>/audio` à la main (`os.makedirs` + `shutil.copy2`),
donc elle fige la FORME du stockage dans une app. Ici on assigne un `File` et c'est
`UserAsset.file.upload_to` (`UploadToUserPath('media_library', 'assets')`) qui décide où il va.
Conséquence directe : le jour où le domicile utilisateur change — chiffrement des dossiers, par
exemple — cette brique suit sans une ligne, là où les copies devront être retrouvées une par une.

CE QU'ELLE NE DEVINE PAS. Le RÔLE d'un asset (`asset_type`) n'est pas dérivable du fichier :
`.mp3` peut être une voix, une musique ou un bruitage. La règle du pivot assistant s'applique
donc ici aussi — *le rôle est FOURNI, jamais deviné*. On ne tranche tout seul que lorsqu'un seul
rôle est admissible pour l'extension ; sinon on REND les candidats et on laisse choisir.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def candidate_asset_types(nom_fichier: str) -> list:
    """Rôles d'asset admissibles pour cette extension, dans l'ordre de `ASSET_TYPES`.

    Lu depuis `ALLOWED_EXTENSIONS` — la politique d'acceptation de la médiathèque, jamais une
    seconde table. Rend `[]` si aucune extension ne convient (le geste ne s'offre alors pas).
    """
    from .models import ALLOWED_EXTENSIONS, ASSET_TYPES

    ext = (nom_fichier or '').rsplit('.', 1)[-1].lower() if '.' in (nom_fichier or '') else ''
    if not ext:
        return []
    return [t for t, _ in ASSET_TYPES if ext in ALLOWED_EXTENSIONS.get(t, [])]


def _fichier_resultat(detail: dict):
    """Chemin réel du RÉSULTAT depuis le schéma canonique, confiné sous MEDIA_ROOT.

    Le contrat canonique rend `result_file` sous forme d'URL (`build_detail`). On la ramène en
    chemin relatif puis on passe par LA brique de confinement — jamais un `os.path.join` maison :
    c'est une entrée qui vient d'une donnée, donc une surface à garder.
    """
    from django.conf import settings

    from wama.common.utils.media_paths import OutsideMediaRoot, resolve_under_media_root

    url = (detail or {}).get('result_file') or ''
    if not url:
        return None, "cet élément n'a pas encore de résultat à ranger"
    prefixe = settings.MEDIA_URL or '/media/'
    rel = url[len(prefixe):] if url.startswith(prefixe) else url.lstrip('/')
    try:
        from urllib.parse import unquote
        chemin, _ = resolve_under_media_root(unquote(rel))
    except OutsideMediaRoot:
        return None, 'résultat hors de MEDIA_ROOT'
    except FileNotFoundError:
        return None, 'le fichier du résultat est introuvable sur le disque'
    return chemin, None


def export_item_to_library(user, app: str, pk: int, asset_type: str = '', name: str = '') -> dict:
    """
    Range le RÉSULTAT d'un élément d'app dans la médiathèque de son propriétaire.

    Générique par construction : la sortie est lue au **schéma canonique** de l'inspecteur
    (`detail_registry`), donc toute app qui déclare son adapter obtient le geste sans une ligne —
    y compris les apps à venir.

    Rend `{'asset_id', 'name', 'asset_type'}` ou `{'error': …}` (+ `'candidates'` quand le rôle
    est ambigu). Ne lève jamais : c'est une surface appelée par une vue ET par le pivot assistant.
    """
    if user is None or not getattr(user, 'is_authenticated', False):
        return {'error': "Médiathèque réservée aux utilisateurs identifiés."}

    from wama.common.utils.detail_registry import DetailRegistry

    entree = DetailRegistry.get(app)
    if not entree:
        return {'error': f"App inconnue au détail : '{app}'. "
                         f"Connues : {', '.join(DetailRegistry.registered_apps())}"}
    instance = entree['model'].objects.filter(pk=pk).first()
    if instance is None:
        return {'error': f"Élément #{pk} introuvable dans '{app}'."}

    # MÊME règle d'ownership que `unified_detail` et `get_item_detail` — trois portes, une règle.
    proprietaire = getattr(instance, 'user', None)
    if proprietaire is not None and proprietaire != user and not getattr(user, 'is_staff', False):
        return {'error': 'forbidden', 'detail': "Cet élément appartient à un autre utilisateur."}

    try:
        detail = entree['adapter'](instance)
    except Exception as e:
        logger.warning(f"[media_library] export {app}#{pk} : adapter en échec : {e}")
        return {'error': f"Détail indisponible pour {app}#{pk} : {e}"}

    chemin, souci = _fichier_resultat(detail)
    if souci:
        return {'error': souci}

    candidats = candidate_asset_types(chemin.name)
    if not candidats:
        return {'error': f"La médiathèque n'accepte pas les fichiers « {chemin.suffix} »."}
    if asset_type:
        if asset_type not in candidats:
            return {'error': f"Rôle '{asset_type}' non admis pour « {chemin.suffix} ».",
                    'candidates': candidats}
    elif len(candidats) == 1:
        asset_type = candidats[0]          # un seul rôle possible : rien à demander
    else:
        # ⚠ On ne tranche PAS à la place de l'utilisateur : un .mp3 peut être une voix, une
        # musique ou un bruitage, et le rôle décide de ce que la médiathèque proposera ensuite.
        return {'error': "Précisez le rôle de cet asset.", 'candidates': candidats}

    from django.core.files import File

    from .models import UserAsset

    nom = (name or '').strip() or chemin.stem
    if UserAsset.objects.filter(user=user, name=nom, asset_type=asset_type).exists():
        return {'error': f'Un asset « {nom} » de ce type existe déjà.'}

    # Traçabilité : d'où vient cet asset. `ia-généré` est la convention déjà posée par composer.
    etiquettes = [t for t in (app, 'ia-généré', (detail or {}).get('engine_effective')
                              or (detail or {}).get('engine')) if t]
    asset = UserAsset(user=user, name=nom, asset_type=asset_type, tags=','.join(map(str, etiquettes)))
    try:
        with open(chemin, 'rb') as f:
            # ⭐ AUCUN chemin construit ici : `upload_to` (UploadToUserPath) décide du domicile.
            asset.file.save(chemin.name, File(f), save=True)
    except Exception as e:
        logger.warning(f"[media_library] export {app}#{pk} : écriture impossible : {e}")
        return {'error': f"Impossible de ranger le fichier : {e}"}

    # Drapeau d'app, quand elle en a un (composer) — posé SANS l'exiger des autres.
    if hasattr(instance, 'exported_to_library') and not instance.exported_to_library:
        instance.exported_to_library = True
        instance.save(update_fields=['exported_to_library'])

    logger.info(f"[media_library] {app}#{pk} → asset #{asset.id} ({asset_type}) pour {user}")
    return {'asset_id': asset.id, 'name': asset.name, 'asset_type': asset.asset_type}
