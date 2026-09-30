"""
Le GESTE « ranger une sortie d'app dans ma médiathèque » — brique COMMUNE.

POURQUOI cette brique existe (mesuré le 2026-09-11). Le geste existait déjà, mais **écrit trois
fois** et seulement dans 2 apps sur 10 :
  • `composer/views.py` (`export_to_library`) et sa jumelle `composer_01` — route RETIRÉE le
    2026-09-18 (`REMOVAL_LEDGER R65`) : elle déléguait ici depuis le 12/09, son seul savoir
    (musique ou bruitage) est désormais DÉCLARÉ par l'app (`result_role`) ;
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


def enrich_asset_from_file(asset) -> None:
    """Ce que le FICHIER dit de l'asset — MIME, taille, et les `attributes` que la sonde commune
    sait lire (`media_probe.probe_media` : un objet 3D livre format / faces / rig / animations ;
    demain une voix sa durée). Posé à l'INGEST, quel que soit le chemin d'entrée (dépôt, rangement
    d'une sortie d'app, fournisseur) : c'est ce qui remplit la déclaration A′ sans formulaire.
    Fail-safe : une sonde qui échoue laisse l'asset tel quel. N'enregistre pas."""
    from wama.common.utils.media_probe import probe_media
    from wama.common.utils.mime_utils import guess_mime_type

    try:
        chemin = asset.file.path
    except Exception:
        return
    if not asset.mime_type:
        asset.mime_type = guess_mime_type(chemin) or ''
    try:
        asset.file_size = asset.file_size or asset.file.size
    except Exception:
        pass
    try:
        sonde = probe_media(chemin) or {}
    except Exception:
        sonde = {}
    lus = sonde.get('attributes') or {}
    if lus:
        asset.attributes = {**lus, **(asset.attributes or {})}   # ce que l'utilisateur a saisi prime
    if sonde.get('duration') and not asset.duration:
        asset.duration = sonde['duration']


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


class LibraryAddRefused(ValueError):
    """Ajout refusé (nature inconnue, format non admis, nom déjà pris, déplacement impossible) —
    le message est lisible tel quel par l'utilisateur ; `status` est le code HTTP qui le dit
    (409 pour un nom déjà pris, 400 sinon)."""

    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def add_file_to_library(user, asset_type: str, *, uploaded=None, source=None, name: str = '',
                        description: str = '', tags: str = ''):
    """Ajoute UN fichier à la médiathèque de `user`, comme asset de la nature `asset_type`.

    LE geste d'ajout (2026-09-29), partagé par la card d'entrée de la page médiathèque
    (`api_upload`) et l'outil de l'assistant (`tool_api.add_to_media_library`), qui l'écrivait
    seul. Deux provenances :
      • `uploaded` — un fichier TÉLÉVERSÉ depuis le poste : il est enregistré par le champ
        (`upload_to`), comme avant ;
      • `source`   — un fichier de l'ARBRE de l'utilisateur (temporaire, sortie d'app, glissé
        depuis l'explorateur) : il est DÉPLACÉ dans la médiathèque et ses porteurs le suivent
        (`move_into_library`, décision de Fabien du 2026-09-27 — D24). L'appelant a confiné le
        chemin ; déplacer le fichier d'un AUTRE (asset système, partagé) n'a pas de sens ici.
    La nature n'est JAMAIS devinée : elle est fournie (l'onglet ouvert, le rôle demandé). Le nom
    par défaut est celui du fichier. Rend l'asset ; lève `LibraryAddRefused` avec un motif."""
    from pathlib import Path

    from .models import ALLOWED_EXTENSIONS, ASSET_TYPES, UserAsset

    if asset_type not in dict(ASSET_TYPES):
        raise LibraryAddRefused(f"Type d'asset invalide : « {asset_type} ». "
                                f"Valides : {', '.join(dict(ASSET_TYPES))}")
    filename = uploaded.name if uploaded is not None else Path(str(source)).name
    ext = Path(filename).suffix.lstrip('.').lower()
    allowed = ALLOWED_EXTENSIONS.get(asset_type, [])
    if ext not in allowed:
        raise LibraryAddRefused(f"Extension .{ext} non admise pour « {asset_type} ». "
                                f"Formats : {', '.join(allowed)}")
    asset_name = (name or '').strip() or Path(filename).stem
    if UserAsset.objects.filter(user=user, name=asset_name, asset_type=asset_type).exists():
        raise LibraryAddRefused(f'Un asset « {asset_name} » de ce type existe déjà.', status=409)

    if uploaded is not None:
        asset = UserAsset.objects.create(user=user, name=asset_name, asset_type=asset_type,
                                         file=uploaded, description=description, tags=tags)
    else:
        asset = UserAsset.objects.create(user=user, name=asset_name, asset_type=asset_type,
                                         description=description, tags=tags)
        if move_into_library(asset, Path(str(source)), filename) is None:
            asset.delete()
            raise LibraryAddRefused("Ajout impossible : le fichier n'a pas pu rejoindre la médiathèque.")
    # MIME, taille et `attributes` lus du FICHIER (sonde commune), quel que soit le chemin d'entrée.
    enrich_asset_from_file(asset)
    asset.save(update_fields=['mime_type', 'file_size', 'attributes', 'duration'])
    return asset


def admissible_roles(detail: dict, nom_fichier: str) -> list:
    """Les rôles que le geste PROPOSE pour cette sortie — et donc les seuls qu'il accepte.

    Deux filtres, dans l'ordre (décision Fabien, 2026-09-18 : « filtrer par rôle, au commun,
    pour toutes les apps ») :
      ① l'EXTENSION : `candidate_asset_types` (la politique d'acceptation de la médiathèque) ;
      ② le RÔLE DÉCLARÉ par l'app dans son détail canonique (`result_role`) : s'il est admis
         pour l'extension, il est le SEUL proposé — le composer sait qu'une musique est une
         musique, l'utilisateur n'a pas à le redire. S'il n'est PAS admis (une déclaration
         périmée, un format inattendu), il est IGNORÉ et l'utilisateur choisit : le menu ne
         propose jamais ce que le POST refuserait, et une déclaration fausse ne bloque rien.
    Ne devine toujours pas : sans déclaration, tous les candidats de l'extension restent.
    """
    candidats = candidate_asset_types(nom_fichier)
    declare = (detail or {}).get('result_role') or ''
    if declare and declare in candidats:
        return [declare]
    return candidats


def _document_formats(app: str) -> list:
    """Formats de RENDU offerts par une app late-binding pour la médiathèque : ceux que son
    bouton ⬇ déclare (`export_formats`), restreints à ce que la nature `document` ACCEPTE
    (srt, vtt, json ne sont pas des documents de médiathèque). Ordre = celui du ⬇."""
    from wama.common.utils.export_formats import entries_for_app

    from .models import ALLOWED_EXTENSIONS
    admis = set(ALLOWED_EXTENSIONS.get('document', []))
    return [e['value'] for e in entries_for_app(app) if e['value'] in admis]


def export_choices(app: str, detail: dict) -> list:
    """Les CHOIX que le geste propose pour cette sortie — `[{key, label, asset_type, format}]`.

    DEUX archétypes d'app (`WAMA_APP_CONVENTIONS §6.4`), un seul geste :
      • **early-binding** (composer, imager, enhancer, anonymizer, converter…) : le fichier est
        DÉJÀ rendu (`apply_inline_conversion` l'a converti à la génération) ; le choix est le
        RÔLE — `admissible_roles` (extension, puis rôle déclaré par l'app) ; `format` vide ;
      • **late-binding** (transcriber, describer, reader) : le master est un TEXTE et le fichier
        n'existe qu'une fois rendu ; le choix est le FORMAT — ceux du bouton ⬇, rendus par le
        MÊME builder que lui (`export_builder_for`), et l'asset est toujours un `document`.
        Sans master (`result_text`) ni builder déclaré : rien à proposer.
    Mesuré le 2026-09-18 : sans cette branche le menu disait « rien à ranger » sur un
    transcript TERMINÉ — le geste était mort pour trois apps sur dix.
    """
    from wama.common.utils.export_formats import VOCABULARY, export_builder_for, is_late_binding

    from .models import ASSET_TYPES
    libelles = dict(ASSET_TYPES)
    detail = detail or {}

    if is_late_binding(app):
        if not detail.get('result_text') or export_builder_for(app) is None:
            return []
        return [{'key': fmt, 'asset_type': 'document', 'format': fmt,
                 'label': f"{libelles.get('document', 'Document')} · "
                          f"{(VOCABULARY.get(fmt) or {}).get('label', fmt.upper())}"}
                for fmt in _document_formats(app)]

    chemin, souci = _fichier_resultat(detail)
    if souci:
        return []
    return [{'key': role, 'asset_type': role, 'format': '', 'label': libelles.get(role, role)}
            for role in admissible_roles(detail, chemin.name)]


def _late_stem(app: str, pk: int, instance, detail: dict) -> str:
    """Souche du nom d'un rendu late-binding — la MÊME convention que le téléchargement
    (`compose_output_name`, tag de process + identifiant de card)."""
    from pathlib import Path

    from wama.common.utils.output_naming import compose_output_name
    source = getattr(instance, 'filename', '') or Path((detail or {}).get('source_file') or '').name
    try:
        return Path(compose_output_name(app=app, source_name=source or '', item_id=pk)).stem
    except Exception:
        return f'{app}_{pk}'


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


def export_item_to_library(user, app: str, pk: int, asset_type: str = '', name: str = '',
                           output_format: str = '') -> dict:
    """
    Range le RÉSULTAT d'un élément d'app dans la médiathèque de son propriétaire.

    Générique par construction : la sortie est lue au **schéma canonique** de l'inspecteur
    (`detail_registry`), donc toute app qui déclare son adapter obtient le geste sans une ligne —
    y compris les apps à venir. Les CHOIX offerts sont ceux d'`export_choices` (rôle pour une
    app early-binding, FORMAT rendu à la demande pour une app late-binding — `output_format`).

    Rend `{'asset_id', 'name', 'asset_type'}` ou `{'error': …}` (+ `'candidates'` quand le choix
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

    from django.core.files.base import ContentFile

    from wama.common.utils.export_formats import export_builder_for, is_late_binding

    from .models import UserAsset

    late = is_late_binding(app)
    if late:
        # LATE-BINDING : le fichier n'existe pas encore, on le REND — par le builder que les
        # téléchargements de l'app utilisent déjà. Le choix est le FORMAT ; le rôle est `document`.
        choix = export_choices(app, detail)
        formats = [c['key'] for c in choix]
        if not formats:
            return {'error': "cet élément n'a pas encore de résultat à ranger"}
        if asset_type and asset_type != 'document':
            return {'error': f"Rôle '{asset_type}' non admis : un rendu texte est un document.",
                    'candidates': formats}
        asset_type = 'document'
        fmt = (output_format or '').lower().lstrip('.')
        if fmt:
            if fmt not in formats:
                return {'error': f"Format '{fmt}' non offert pour cette sortie.", 'candidates': formats}
        elif len(formats) == 1:
            fmt = formats[0]
        else:
            return {'error': 'Précisez le format du document.', 'candidates': formats}
        rendu = None
        try:
            rendu = export_builder_for(app)(instance, fmt)
        except Exception as e:
            logger.warning(f"[media_library] export {app}#{pk} : rendu {fmt} en échec : {e}")
        if not rendu:
            return {'error': f"Le rendu « {fmt} » de cet élément n'est pas disponible."}
        ext, octets = rendu
        deja = assets_of_item(user, app, pk).filter(asset_type='document',
                                                    file__iendswith=f'.{ext}').first()
        if deja is not None:
            return {'error': f"Cet élément est déjà dans la médiathèque (« {deja.name} »).",
                    'asset_id': deja.id}
        souche = _late_stem(app, pk, instance, detail)
        nom_fichier, contenu = f'{souche}.{ext}', ContentFile(octets)
        nom = (name or '').strip() or f'{souche} ({ext.upper()})'
    else:
        chemin, souci = _fichier_resultat(detail)
        if souci:
            return {'error': souci}

        if not candidate_asset_types(chemin.name):
            return {'error': f"La médiathèque n'accepte pas les fichiers « {chemin.suffix} »."}
        # Extension PUIS rôle déclaré par l'app (2026-09-18) : ce que le menu propose est ce que
        # le geste accepte — un rôle hors de cette liste est refusé même s'il conviendrait à
        # l'extension.
        candidats = admissible_roles(detail, chemin.name)
        if asset_type:
            if asset_type not in candidats:
                return {'error': f"Rôle '{asset_type}' non admis pour cette sortie.",
                        'candidates': candidats}
        elif len(candidats) == 1:
            asset_type = candidats[0]      # un seul rôle possible (ou déclaré) : rien à demander
        else:
            # ⚠ On ne tranche PAS à la place de l'utilisateur : un .mp3 peut être une voix, une
            # musique ou un bruitage, et le rôle décide de ce que la médiathèque proposera ensuite.
            return {'error': "Précisez le rôle de cet asset.", 'candidates': candidats}

        # Déjà rangé depuis CET élément sous ce rôle ? La PROVENANCE tranche, pas le nom — sinon
        # un second clic créerait une copie sous un autre nom, et la coche du menu mentirait.
        deja = assets_of_item(user, app, pk).filter(asset_type=asset_type).first()
        if deja is not None:
            return {'error': f"Cet élément est déjà dans la médiathèque (« {deja.name} »).",
                    'asset_id': deja.id}
        nom_fichier, contenu = chemin.name, None
        nom = (name or '').strip() or chemin.stem

    if UserAsset.objects.filter(user=user, name=nom, asset_type=asset_type).exists():
        return {'error': f'Un asset « {nom} » de ce type existe déjà.'}

    # Traçabilité : d'où vient cet asset. `ia-généré` est la convention déjà posée par composer.
    etiquettes = [t for t in (app, 'ia-généré', (detail or {}).get('engine_effective')
                              or (detail or {}).get('engine')) if t]
    asset = UserAsset(user=user, name=nom, asset_type=asset_type, tags=','.join(map(str, etiquettes)),
                      source_app=app, source_pk=pk)
    try:
        if contenu is not None:
            # ⭐ AUCUN chemin construit ici non plus : `upload_to` décide, le rendu est un contenu.
            # (Late-binding : le fichier n'existait pas, il n'y a rien à déplacer.)
            asset.file.save(nom_fichier, contenu, save=False)
            enrich_asset_from_file(asset)
            asset.save()
        else:
            # ⭐ DÉPLACEMENT, plus une copie (décision de Fabien, 2026-09-27 : *« un fichier ajouté
            # à la médiathèque doit aller dans la médiathèque »*). Le fichier rejoint le domicile
            # de la médiathèque et **les porteurs suivent** : la card qui l'avait produit le DÉSIGNE
            # désormais là où il est. Avant, l'ajout laissait deux exemplaires des mêmes octets et
            # la médiathèque n'était qu'un dossier de copies.
            asset.save()                      # il faut un pk pour repointer proprement
            deplace = move_into_library(asset, chemin, nom_fichier)
            if deplace is None:
                asset.delete()
                return {'error': "Impossible de déplacer le fichier dans la médiathèque."}
            enrich_asset_from_file(asset)
            asset.save()
    except Exception as e:
        logger.warning(f"[media_library] export {app}#{pk} : écriture impossible : {e}")
        return {'error': f"Impossible de ranger le fichier : {e}"}

    # Drapeau d'app, quand elle en a un (composer) — posé SANS l'exiger des autres.
    if hasattr(instance, 'exported_to_library') and not instance.exported_to_library:
        instance.exported_to_library = True
        instance.save(update_fields=['exported_to_library'])

    logger.info(f"[media_library] {app}#{pk} → asset #{asset.id} ({asset_type}) pour {user}")
    return {'asset_id': asset.id, 'name': asset.name, 'asset_type': asset.asset_type}


def move_into_library(asset, source, nom_fichier: str):
    """DÉPLACE `source` dans le domicile de la médiathèque et fait SUIVRE tous ses porteurs.

    Décision de Fabien du 2026-09-27 : *« de manière générale, un source_file ajouté à la médiathèque
    doit aller dans la médiathèque »* — et les autres le POINTENT (suite du pointage du 23/09).

    Trois gestes, dans cet ordre, parce que l'ordre est ce qui rend l'opération sûre :
      1. la destination est décidée par le CHAMP (`upload_to`, jamais un chemin composé ici) et
         dé-collisionnée par le stockage ;
      2. le source_file est déplacé ;
      3. `file_references.repoint` réécrit **toutes** les lignes qui désignaient l'old_rel chemin —
         la card d'origin comprise. Sans ce 3ᵉ geste, ranger un résultat le ferait disparaître de
         sa card : c'est exactement la 3ᵉ route du disque (le NOM enregistré).

    ⚠ Le PARTAGE n'a rien à suivre : il sert `asset.file.url`, c'est-à-dire le chemin RÉEL de la
    line (mesuré le 2026-09-27, `_serialize_user_asset`) — jamais un emplacement d'origin.

    Rend le chemin relatif final, ou `None` si le déplacement a échoué (rien n'est alors perdu :
    le source_file est resté où il était).
    """
    import shutil
    from pathlib import Path

    from django.conf import settings
    from django.core.files.storage import default_storage

    from wama.common.utils.file_references import repoint

    try:
        source = Path(source)
        old_rel = source.resolve().relative_to(Path(settings.MEDIA_ROOT).resolve()).as_posix()
        target = default_storage.get_available_name(
            asset._meta.get_field('file').generate_filename(asset, nom_fichier))
        target_abs = Path(settings.MEDIA_ROOT) / target
        target_abs.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(target_abs))     # `move` et non `replace` : DrvFS ≠ ext4
        asset.file.name = target
        # D'OÙ il vient — pour que le RETRAIT soit l'inverse exact de l'ajout (le source_file retourne
        # chez sa card). Sans cette trace, le retrait devrait deviner un dossier de completed.
        attributes_ = dict(asset.attributes or {})
        attributes_['moved_from'] = old_rel
        asset.attributes = attributes_
        asset.save(update_fields=['file', 'attributes'])
        repoint(old_rel, target)                       # la card d'origin et tout autre porteur
        return target
    except Exception as exc:
        logger.warning('[media_library] déplacement vers la médiathèque impossible (%s) : %s',
                       source, exc)
        return None


def _move_back_to_origin(asset) -> bool:
    """Rend le source_file à l'endroit d'où l'ajout l'a pris, si une card le désigne encore.

    L'inverse de `move_into_library`, et rien de plus : même brique de repointage, même règle
    (aucun chemin inventé — on relit celui que l'ajout a noté). Rend `True` si le source_file a été
    rendu (l'appelant ne doit alors PAS le supprimer), `False` s'il n'y avait rien à rendre :
    pas d'origin notée (asset créé par un rendu, ou ajouté avant le 2026-09-27), source_file absent,
    ou plus aucun autre porteur — dans ce dernier cas il s'agit bien d'une suppression.
    """
    import shutil
    from pathlib import Path

    from django.conf import settings

    from wama.common.utils.file_references import is_referenced_elsewhere, repoint

    origin = (asset.attributes or {}).get('moved_from') if asset.attributes else None
    current = asset.file.name if asset.file else ''
    if not origin or not current:
        return False
    if not is_referenced_elsewhere(current, label=asset._meta.label, pk=asset.pk, field='file'):
        return False                      # plus personne ne le désigne : c'est une suppression
    try:
        source = Path(settings.MEDIA_ROOT) / current
        target = Path(settings.MEDIA_ROOT) / origin
        if not source.is_file():
            return False
        if target.exists():                # la place est reprise : on ne détruit rien, on laisse
            return True
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(target))
        repoint(current, origin)
        return True
    except Exception as exc:
        logger.warning('[media_library] retour du source_file à son origin impossible (%s) : %s',
                       current, exc)
        return True                       # on n'a pas rendu, mais on ne supprime pas à l'aveugle


def assets_of_item(user, app: str, pk: int):
    """Les assets de `user` rangés depuis l'élément `app#pk` — par la PROVENANCE, jamais par le nom
    (renommable, et deux éléments peuvent rendre un fichier de même nom)."""
    from .models import UserAsset
    return UserAsset.objects.filter(user=user, source_app=app, source_pk=pk)


def _release_app_flag(app: str, pk) -> None:
    """Drapeau d'app `exported_to_library` (composer) : remis à False quand PLUS AUCUN asset — de
    quelque compte que ce soit — n'est rangé depuis l'élément. Symétrique de la pose dans
    `export_item_to_library`, et sans l'exiger des autres apps."""
    from .models import UserAsset
    if not app or pk is None or UserAsset.objects.filter(source_app=app, source_pk=pk).exists():
        return
    from wama.common.utils.detail_registry import DetailRegistry
    entree = DetailRegistry.get(app)
    instance = entree['model'].objects.filter(pk=pk).first() if entree else None
    if instance is not None and getattr(instance, 'exported_to_library', False):
        instance.exported_to_library = False
        instance.save(update_fields=['exported_to_library'])


def delete_asset(asset) -> None:
    """Supprime un asset ET son fichier, puis libère le drapeau d'app si plus rien n'en provient.

    Pour un asset créé par `export_item_to_library`, le fichier est une COPIE (`upload_to` → nom
    unique) : la sortie de l'app n'est jamais touchée. ⚠ Certains assets ANCIENS pointent un fichier
    PARTAGÉ (migration 0002 — voix personnalisées) : le supprimer casse l'autre référent.
    ✅ **Traité le 2026-09-23** : la brique commune `delete_file_unless_shared` garde le fichier
    tant qu'une autre ligne le désigne, dans N'IMPORTE QUEL modèle (mesuré : `UserAsset #1` et
    `CustomVoice #1` partagent `Voix_Fab.wav`). L'asset part, le fichier attend son dernier porteur.

    ⭐ **Depuis le 2026-09-27, le retrait est l'INVERSE de l'ajout** : l'ajout DÉPLACE le fichier
    dans la médiathèque (décision de Fabien), donc le retrait le **rend à sa card** quand elle le
    désigne encore — le chemin d'origine est celui que l'ajout a noté (`attributes.moved_from`).
    Sans ce retour, les octets resteraient dans un dossier « médiathèque » que plus rien n'y range.
    Si plus aucun porteur ne le désigne, le fichier part avec l'asset, comme avant.

    ⚠ **Un `SystemAsset` n'entre pas ici, et c'est dit** (2026-09-27). Le modèle l'annonce déjà
    (« Non supprimable par les utilisateurs finaux », `models.py`) et la route le tient
    (`api_delete` n'interroge que `UserAsset`) — mais cette fonction, elle, lisait `source_app`
    sans rien vérifier : passé un asset système, elle levait `AttributeError`. *Une protection
    par accident n'en est pas une* : le jour où un appelant lui passerait un `SystemAsset`, le
    message ne dirait pas ce qui est interdit, il dirait qu'un champ manque.
    """
    from wama.common.utils.queue_duplication import delete_file_unless_shared
    from wama.media_library.models import UserAsset

    if not isinstance(asset, UserAsset):
        raise TypeError(
            f"{type(asset).__name__} : seul un UserAsset se supprime ici. Une voix ou un avatar "
            "INTÉGRÉ (SystemAsset) est commun à tous les comptes — on le DÉSACTIVE "
            "(`is_active=False`), on ne le supprime pas : des lignes en base le désignent par "
            "son nom ou son `sa_<id>`, et elles retomberaient en silence sur la voix par défaut."
        )

    source_app, source_pk = asset.source_app, asset.source_pk
    if not _move_back_to_origin(asset):
        delete_file_unless_shared(asset, 'file')
    asset.delete()
    # Que la suppression parte du menu d'une card OU de la page médiathèque, le drapeau suit
    # (audit du 14/09 : supprimé depuis la page, le composer répondait « Déjà exporté » à vie).
    _release_app_flag(source_app, source_pk)


def in_library_by_choice(user, app: str, pk: int) -> dict:
    """Ce qui est DÉJÀ rangé depuis `app#pk`, indexé par la CLÉ de choix du menu — le rôle
    (early), ou le format rendu (late : suffixe du fichier de l'asset). C'est la coche du
    sous-menu, et ce que son clic retire."""
    from pathlib import Path

    from wama.common.utils.export_formats import is_late_binding
    late = is_late_binding(app)
    deja = {}
    for a in assets_of_item(user, app, pk):
        cle = Path(a.file.name or '').suffix.lstrip('.').lower() if late else a.asset_type
        if cle:
            deja[cle] = {'asset_id': a.id, 'name': a.name}
    return deja


def remove_item_from_library(user, app: str, pk: int, asset_type: str = '',
                             output_format: str = '') -> dict:
    """Retire de la médiathèque ce qui a été rangé depuis `app#pk` (un rôle, un format, ou tout).

    Le geste inverse d'`export_item_to_library`, pour le menu « … » (2026-09-14). Ne touche QUE
    les assets de `user` : même avec le pk d'un élément étranger, on n'atteint pas la médiathèque
    d'autrui. Rend `{'removed': n}` ou `{'error': …}` ; ne lève jamais.
    """
    if user is None or not getattr(user, 'is_authenticated', False):
        return {'error': "Médiathèque réservée aux utilisateurs identifiés."}
    cibles = assets_of_item(user, app, pk)
    if asset_type:
        cibles = cibles.filter(asset_type=asset_type)
    if output_format:
        cibles = cibles.filter(file__iendswith='.' + output_format.lower().lstrip('.'))
    retires = 0
    for asset in list(cibles):
        try:
            delete_asset(asset)
            retires += 1
        except Exception as e:
            logger.warning(f"[media_library] retrait {app}#{pk} asset #{asset.pk} : {e}")
    if not retires:
        return {'error': "Rien de cet élément n'est dans la médiathèque."}

    # Drapeau d'app (composer) : plus rien de rangé depuis cet élément → il redevient exportable.
    # Symétrique de la pose dans `export_item_to_library`, et SANS l'exiger des autres apps.
    if not assets_of_item(user, app, pk).exists():
        from wama.common.utils.detail_registry import DetailRegistry
        entree = DetailRegistry.get(app)
        instance = entree['model'].objects.filter(pk=pk).first() if entree else None
        if instance is not None and getattr(instance, 'exported_to_library', False):
            instance.exported_to_library = False
            instance.save(update_fields=['exported_to_library'])

    logger.info(f"[media_library] {app}#{pk} : {retires} asset(s) retiré(s) pour {user}")
    return {'removed': retires}


# ── Galerie d'avatars PARTAGÉE — domicile unique d'une ressource d'application ──────────
#
# ⚠ POURQUOI ICI, ET PAS DANS L'AVATARIZER. La galerie était un DOSSIER parcouru à la main par
# TROIS sites Python (`avatarizer.views._gallery_images`, `avatarizer.workers`, `studio.views`)
# et DEUX gabarits qui composaient l'URL (`{{ media_url }}avatarizer/gallery/{{ nom }}`). Six
# endroits pour neuf images, et aucun droit : la galerie était lisible et servie à tous sans que
# personne ne l'ait décidé.
#
# `SystemAsset` est le modèle EXACT de ce qu'elle est — « asset générique partagé par tous les
# utilisateurs, géré par les admins, non supprimable par les utilisateurs finaux ». Il existait
# depuis le début ; la galerie l'ignorait. L'y verser donne les droits fins, un domicile unique,
# et supprime les six compositions de chemin.
#
# ⚠ LA CLÉ RESTE LE NOM DE FICHIER. `AvatarJob.avatar_gallery_name` STOCKE ce nom : c'est la
# frontière des DONNÉES, elle ne se renomme pas. `SystemAsset.name` porte donc le même nom, et
# les lignes déjà en base continuent de résoudre — le stockage change, pas le contrat.

def gallery_assets():
    """Les avatars de la galerie partagée, actifs, dans l'ordre d'affichage."""
    from .models import SystemAsset
    return SystemAsset.objects.filter(asset_type='avatar', is_active=True).order_by('name')


def gallery_entries() -> list:
    """`[{'name', 'url'}]` — ce dont les gabarits ont besoin, sans composer d'URL.

    Rendre l'URL ICI est tout l'intérêt : le jour où le domicile des assets bouge (chiffrement),
    les gabarits suivent sans être touchés. C'est la même règle que `app_media_dir` pour les
    chemins — *un seul endroit décide de la forme*.
    """
    return [{'name': a.name, 'url': a.file.url} for a in gallery_assets() if a.file]


def gallery_path(name: str):
    """Chemin ABSOLU de l'avatar nommé, ou `None` s'il n'existe pas (le worker en a besoin).

    Rend `None` plutôt que de lever : l'appelant sait dire « avatar introuvable » avec le nom,
    ce qui est plus utile qu'une trace d'exception sur un chemin composé.
    """
    if not name:
        return None
    a = gallery_assets().filter(name=name).first()
    return a.file.path if (a and a.file) else None


# ── Un asset désigné par son NOM, parmi ce que l'utilisateur VOIT (2026-09-29) ────────────────
# Un fichier de lot (`-r avatar1.png`), un nœud du Studio ou l'assistant désignent un asset par
# son NOM. Ce nom ne se cherchait que dans la galerie système : les avatars de l'utilisateur et
# ceux qu'on lui partage étaient introuvables par ces voies, alors que la card les propose. Une
# règle, trois provenances, dans l'ordre de confiance : les siens, les partagés, le système.

def _named(queryset, name):
    from django.db.models import Q
    return queryset.filter(Q(name=name) | Q(file__endswith='/' + name))


def resolve_visible_asset(user, asset_type: str, name: str) -> str:
    """Chemin (relatif à MEDIA_ROOT) de l'asset `name` de cette nature que `user` voit, ou ''.

    Le nom se compare au nom de l'asset ET à celui de son fichier (un lot écrit le fichier).
    Les siens priment, puis ceux qu'on lui partage (`listable_by`), puis le système."""
    from .models import SystemAsset, UserAsset
    from wama.common.utils.scoping import listable_by
    name = (name or '').strip()
    if not name:
        return ''
    candidates = []
    if user is not None and getattr(user, 'id', None):
        visible = listable_by(UserAsset.objects.filter(asset_type=asset_type), user)
        candidates += [_named(visible.filter(user=user), name).order_by('-id'),
                       _named(visible.exclude(user=user), name).order_by('name')]
    candidates.append(_named(SystemAsset.objects.filter(asset_type=asset_type, is_active=True),
                             name).order_by('name'))
    for qs in candidates:
        a = qs.first()
        if a and a.file:
            return a.file.name
    return ''


def visible_asset_names(user, asset_type: str, attributes: dict | None = None) -> list:
    """Les NOMS des assets de cette nature que `user` voit (siens, partagés, système), sans doublon
    — la liste d'un sélecteur qui désigne par nom (Studio).

    `attributes` (2026-09-30) : ne garder que les assets qui PORTENT ces attributs (mesurés à
    l'ingest, nature A′) — un avatar parlant est un `object3d` au visage ARKit, pas n'importe quel
    maillage."""
    from .models import SystemAsset, UserAsset
    from wama.common.utils.scoping import listable_by
    wanted = {'attributes__contains': attributes} if attributes else {}
    names = []
    if user is not None and getattr(user, 'id', None):
        names += list(listable_by(UserAsset.objects.filter(asset_type=asset_type, **wanted), user)
                      .order_by('name').values_list('name', flat=True))
    names += list(SystemAsset.objects.filter(asset_type=asset_type, is_active=True, **wanted)
                  .order_by('name').values_list('name', flat=True))
    return list(dict.fromkeys(names))


# ── RENDRE un asset système à son auteur (2026-09-29, MEDIA_STORAGE_TIERING §8.6 D27) ──────────
# Le versement de la galerie (12/09) a fait des photos PERSONNELLES d'un utilisateur des assets
# SYSTÈME : sans propriétaire, leur auteur ne pouvait plus ni les supprimer ni les ranger. Le geste
# inverse d'un versement : l'asset redevient un `UserAsset` PRIVÉ de l'utilisateur, son fichier
# rejoint la médiathèque de celui-ci (`move_into_library` : domicile décidé par `upload_to`,
# références par CHEMIN repointées), la ligne système disparaît.
#
# Les références par NOM ne se voient pas par le chemin (l'avatarizer stocke le NOM d'un avatar de
# galerie, `AvatarJob.avatar_gallery_name`). Chaque app qui en tient les DÉCLARE ici — le registre
# ne connaît jamais ses producteurs, même règle que `function_catalog` (`AGENTS.md`, mondes).

_SYSTEM_ASSET_NAME_HOLDERS = []


class SystemAssetStillNamed(RuntimeError):
    """Un AUTRE utilisateur cite encore l'asset par son nom : le rendre à un seul casserait ses
    travaux. Rien n'est fait ; le message dit qui cite, et combien."""


def register_system_asset_name_holder(asset_type: str, holder) -> None:
    """Déclare une référence PAR NOM à un asset système d'une nature donnée.

    `holder(name, user, new_path, apply) -> {'label', 'mine', 'others'}` : `mine` = références de
    `user` (repointées vers `new_path` quand `apply`), `others` = références d'autres utilisateurs
    (jamais touchées). Appelé une première fois SANS `apply` pour le plan. Idempotent : un
    `ready()` rejoué n'inscrit pas deux fois le même holder (ses comptes seraient doublés)."""
    if (asset_type, holder) not in _SYSTEM_ASSET_NAME_HOLDERS:
        _SYSTEM_ASSET_NAME_HOLDERS.append((asset_type, holder))


def return_system_asset(asset, user, *, apply: bool = False) -> dict:
    """Rend l'asset système `asset` à `user` : un `UserAsset` privé, fichier déplacé chez lui.

    Sans `apply`, rend le PLAN seul (rien n'est écrit). Lève `SystemAssetStillNamed` si un autre
    utilisateur le cite par son nom, `ValueError` si `user` a déjà un asset de ce nom et de cette
    nature. Le fichier est remis en place si une étape après le déplacement échoue."""
    import shutil
    from pathlib import Path

    from django.conf import settings
    from django.db import transaction

    from .models import UserAsset

    holders = [h for kind, h in _SYSTEM_ASSET_NAME_HOLDERS if kind == asset.asset_type]
    references = [h(asset.name, user, None, False) for h in holders]
    plan = {'asset': asset.name, 'asset_type': asset.asset_type, 'from': asset.file.name,
            'to_user': user.username, 'references': references}
    others = sum(r.get('others', 0) for r in references)
    if others:
        raise SystemAssetStillNamed(
            f"« {asset.name} » est encore cité par son nom par {others} élément(s) d'autres "
            f"utilisateurs : {references}")
    if UserAsset.objects.filter(user=user, name=asset.name, asset_type=asset.asset_type).exists():
        raise ValueError(f"{user.username} a déjà un asset « {asset.name} » de cette nature")
    if not apply:
        return plan

    source = Path(asset.file.path)
    with transaction.atomic():
        returned = UserAsset.objects.create(
            user=user, name=asset.name, asset_type=asset.asset_type,
            attributes=dict(asset.attributes or {}), mime_type=asset.mime_type,
            file_size=asset.file_size, duration=asset.duration, description=asset.description,
            tags=asset.tags, license=asset.license, author=asset.author,
            source_url=asset.source_url)
        target = move_into_library(returned, source, source.name)
        if target is None:
            raise RuntimeError(f"déplacement impossible : {source}")
        try:
            # Un RETOUR n'est pas un rangement : pas d'origine où « rendre » le fichier plus tard
            # (`_move_back_to_origin` le renverrait dans la zone système, sans ligne pour l'offrir).
            attributes = dict(returned.attributes or {})
            attributes.pop('moved_from', None)
            returned.attributes = attributes
            returned.save(update_fields=['attributes'])
            for h in holders:
                h(asset.name, user, target, True)
            asset.delete()
        except Exception:
            shutil.move(str(Path(settings.MEDIA_ROOT) / target), str(source))
            raise
    plan['to'] = target
    plan['user_asset_id'] = returned.id
    return plan
