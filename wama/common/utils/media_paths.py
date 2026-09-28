"""
WAMA Common - Media Path Utilities

Centralized utilities for generating user-specific media paths across all applications.
Structure: media/{app_name}/{user_id}/{subfolder}/

This ensures:
- User isolation: each user sees only their files
- Consistent structure across all apps
- Easy migration path for existing apps
"""

import os
import uuid
from pathlib import Path
from typing import Union, Optional
from django.conf import settings


def get_app_media_path(app_name: str, user_id: Union[int, str], subfolder: str = 'input') -> Path:
    """
    Get the absolute path for an app's user-specific media folder.

    Args:
        app_name: Application name (e.g., 'anonymizer', 'enhancer')
        user_id: User ID
        subfolder: Subfolder name (e.g., 'input', 'output')

    Returns:
        Path object for: MEDIA_ROOT/{app_name}/{user_id}/{subfolder}/

    Example:
        get_app_media_path('anonymizer', 1, 'input')
        -> Path('/media/anonymizer/1/input/')
    """
    # DÉRIVÉ de `app_media_dir` : la forme absolue et la forme relative ne doivent pas
    # pouvoir diverger. Elles l'ont fait tant qu'elles étaient écrites deux fois.
    return Path(settings.MEDIA_ROOT) / app_media_dir(app_name, user_id, subfolder)


class OutsideMediaRoot(ValueError):
    """Le chemin demandé sort de MEDIA_ROOT (traversée `..`, dossier frère, absolu étranger)."""


def resolve_under_media_root(candidate, *, must_exist: bool = True):
    """Résout un chemin — absolu, ou RELATIF à MEDIA_ROOT — et GARANTIT qu'il y reste.

    Rend ``(abs_path, rel_posix)`` ; lève `OutsideMediaRoot` sinon, `FileNotFoundError` si
    ``must_exist`` et que le fichier manque.

    LA garde de confinement du dépôt (2026-09-05, `MEDIA_STORAGE_TIERING §8.6` D1-D3) —
    posée UNE fois, adoptée par tous les sites qui reçoivent un chemin de l'utilisateur
    (`server_path` d'un import filemanager, `-i` d'un fichier de lot, liste de chemins).
    Avant elle, six sites la réécrivaient chacun à sa façon et **deux étaient faux** :
      - `synthesizer/views.py` faisait ``Path(MEDIA_ROOT) / server_path`` sans `resolve()`
        ni contrôle — un ``../../…`` lisait n'importe quel fichier du serveur (🔴) ;
      - converter, avatarizer et le gabarit généré contrôlaient par
        ``str(abs).startswith(str(root))`` — un dossier FRÈRE (``media_backup/``) passait.
    Le contrôle juste est une FRONTIÈRE DE CHEMIN (`relative_to`), après résolution des
    liens et des ``..`` — c'est ce que `converter.quick_convert` faisait déjà seul.
    """
    root = Path(settings.MEDIA_ROOT).resolve()
    cand = Path(str(candidate))
    abs_path = (cand if cand.is_absolute() else root / cand).resolve()
    try:
        rel = abs_path.relative_to(root)
    except ValueError:
        raise OutsideMediaRoot(f"Chemin hors de MEDIA_ROOT : {candidate}")
    if must_exist and not abs_path.exists():
        raise FileNotFoundError(f"Fichier introuvable : {candidate}")
    return abs_path, rel.as_posix()


def get_app_media_url(app_name: str, user_id: Union[int, str], subfolder: str = 'input') -> str:
    """
    Get the URL path for an app's user-specific media folder.

    Args:
        app_name: Application name (e.g., 'anonymizer', 'enhancer')
        user_id: User ID
        subfolder: Subfolder name (e.g., 'input', 'output')

    ⚠ DÉRIVÉ de `app_media_dir`, comme la forme absolue et la forme relative. Cette fonction
    composait la chaîne à la main jusqu'au 2026-09-12 — donc elle a survécu au portage des 61
    littéraux (elle EST une brique, on ne l'a pas cherchée comme un littéral) et elle serait
    restée seule à pointer vers l'ancien domicile après la bascule : des aperçus morts, sans
    la moindre erreur. *Une brique qui compose ce qu'une autre brique compose déjà est un
    littéral déguisé.*

    Returns:
        URL string: /media/users/{user_id}/{app_name}/{subfolder}/
    """
    return f"{settings.MEDIA_URL}{app_media_dir(app_name, user_id, subfolder)}/"


def ensure_app_media_dirs(app_name: str, user_id: Union[int, str]) -> dict:
    """
    Ensure input and output directories exist for an app/user.

    Args:
        app_name: Application name
        user_id: User ID

    Returns:
        Dict with 'input' and 'output' Path objects
    """
    input_path = get_app_media_path(app_name, user_id, 'input')
    output_path = get_app_media_path(app_name, user_id, 'output')

    input_path.mkdir(parents=True, exist_ok=True)
    output_path.mkdir(parents=True, exist_ok=True)

    return {
        'input': input_path,
        'output': output_path,
    }


def get_unique_filename(folder: Union[str, Path], filename: str) -> str:
    """
    Generate a unique filename in a folder.
    If 'file.mp4' exists, generates 'file_<uuid>.mp4'.

    Args:
        folder: Directory path
        filename: Original filename

    Returns:
        Unique filename (not full path)
    """
    folder = Path(folder)
    base, ext = os.path.splitext(filename)
    candidate = filename
    full_path = folder / candidate

    while full_path.exists():
        candidate = f"{base}_{uuid.uuid4().hex[:8]}{ext}"
        full_path = folder / candidate

    return candidate


def app_media_dir(app_name: str, user_id: Union[int, str], subfolder: str = 'input') -> str:
    """Dossier média d'une app, RELATIF à `MEDIA_ROOT` — la FORME du chemin, en un seul endroit.

    ⚠ L'INTÉRÊT EST QU'ELLE SOIT SEULE. Mesuré le 2026-09-11 : **61 sites** fabriquaient cette
    chaîne à la main (`f'anonymizer/{user_id}/input'`), concentrés sur 4 fichiers — dont une
    table déclarative de 43 entrées dans l'arbre du gestionnaire de fichiers. Tant qu'ils
    existent, DÉPLACER le domicile des fichiers est impossible : chaque littéral oublié devient
    un dossier vide dans l'arbre, une preview morte ou un import qui écrit à l'ancien endroit —
    et rien ne le signale.

    ✅ LA BASCULE EST FAITE — 2026-09-12. Demande de Fabien (2026-09-11) : *« que tous les
    fichiers importés d'un utilisateur, quelle que soit la manière, aillent dans le dossier de
    l'utilisateur »*, condition d'un chiffrement PAR UTILISATEUR (ses octets doivent vivre dans
    UN sous-arbre). Cette fonction est le point de bascule : tout ce qui écrit un chemin média
    en dérive, donc changer cette seule ligne déplace le domicile de TOUTES les apps à la fois.
    Le parc existant a été déplacé par `manage.py migrate_media_to_user_home`.

    ⚠ L'ORDRE DES DEUX GESTES N'EST PAS INDIFFÉRENT, et c'est ce qui a rendu la bascule sûre :
    le portage des 61 sites s'est fait à forme CONSTANTE (la fonction rendait alors la forme
    historique), et le déplacement du parc n'a suivi qu'après. Les mélanger aurait rendu
    indébogable le moindre écart — on n'aurait pas su si un fichier manquait parce qu'un
    littéral avait été oublié ou parce qu'un rename avait échoué.

    ⚠ UNE PREMIÈRE TENTATIVE A ÉCHOUÉ EN VOL le 2026-09-11 (413 lignes / 30 fichiers à
    réparer). Ses deux causes — `max_length=100`, et les fichiers PARTAGÉS par
    `duplicate_instance` — sont désormais traitées DANS la commande de migration, qui porte le
    détail des quatre corrections (pré-vol bloquant, raisonnement par fichier, base écrite
    dans la transaction du rename, unités atomiques indépendantes). Elles ne sont plus décrites
    ici : ce sont des propriétés de la MIGRATION, pas de la forme du chemin.

    ⚠ CE QUI N'A PAS BOUGÉ, et qu'il ne faut pas croire fait : les fichiers ORPHELINS (~290 au
    12/09, aucune ligne de base ne les cite) dorment toujours dans les arbres d'app. Pour le
    chiffrement ils comptent — ce sont des octets d'utilisateur —, mais les déplacer est une
    décision distincte : certains lecteurs les retrouvent par GLOB (anonymizer `_blurred*`) et
    aucun test ne couvre ce chemin-là.

    Returns:
        `"users/{user_id}/{app_name}/{subfolder}"` — sans barre finale, séparateurs POSIX.
    """
    return f"users/{user_id}/{app_name}/{subfolder}"


def get_relative_media_path(app_name: str, user_id: Union[int, str], subfolder: str, filename: str) -> str:
    """
    Get the relative path for storing in Django FileField.

    Args:
        app_name: Application name
        user_id: User ID
        subfolder: Subfolder name ('input' or 'output')
        filename: Filename

    Returns:
        Relative path string: {app_name}/{user_id}/{subfolder}/{filename}
    """
    return f"{app_media_dir(app_name, user_id, subfolder)}/{filename}"


def copy_into_app_input(source_path, app_name: str, user_id, subfolder: str = 'input',
                        allowed_exts=None, *, for_instance=None, field=None,
                        provenance_kind='temp', provenance_ref=None):
    """Copy a source file into an app's media folder with collision-safe naming.

    Centralises the logic duplicated by every ``import_to_<app>()`` helper:
    validate extension, ensure the destination dir, append ``_N`` on name
    collision, copy, and compute the MEDIA_ROOT-relative path.

    Args:
        source_path: Path (or str) of the file to copy.
        app_name:    Target app (e.g. 'reader', 'enhancer').
        user_id:     Owning user id.
        subfolder:   Destination subfolder ('input', 'input/audio', …).
        allowed_exts: Optional iterable of accepted extensions (lowercase,
                      dot-prefixed, e.g. {'.pdf', '.png'}). Raises ValueError
                      if the source extension is not in the set.
        for_instance/field: si donnés, la PROVENANCE est enregistrée ici — au SEUL endroit
                      où la copie se fait. La brique se souvient de ce qu'elle a fait ; aucune
                      app n'écrit la provenance elle-même (cf. `utils/provenance.py`).
        provenance_kind/ref: nature et adresse de la source. `temp` par défaut, parce que
                      c'est d'où vient l'écrasante majorité des imports (`users/<u>/temp/…`,
                      le dossier que le gestionnaire de fichiers alimente).

    Returns:
        (dest_path: Path, relative_path: str)
    """
    import shutil
    from pathlib import Path

    src = Path(source_path)
    ext = src.suffix.lower()
    if allowed_exts is not None and ext not in {e.lower() for e in allowed_exts}:
        raise ValueError(f"Format non supporté : {ext}")

    dest_dir = get_app_media_path(app_name, user_id, subfolder)
    dest_dir.mkdir(parents=True, exist_ok=True)

    dest_path = dest_dir / src.name
    if dest_path.exists():
        stem, suffix, counter = dest_path.stem, dest_path.suffix, 1
        while dest_path.exists():
            dest_path = dest_dir / f"{stem}_{counter}{suffix}"
            counter += 1

    shutil.copy2(src, dest_path)
    relative_path = get_relative_media_path(app_name, user_id, subfolder, dest_path.name)

    if for_instance is not None and field:
        # ⚠ L'adresse de la SOURCE, pas celle de la copie : c'est ce qui permet de retrouver
        # « qui référence ce fichier » et « ai-je déjà copié cette source ». Par défaut on
        # rend le chemin relatif à MEDIA_ROOT quand la source y vit — sinon son chemin brut.
        from wama.common.utils.provenance import record_provenance, ref_for
        record_provenance(for_instance, field, kind=provenance_kind,
                          ref=provenance_ref if provenance_ref is not None else ref_for(src),
                          original_name=src.name, source_path=src)

    return dest_path, relative_path


def in_user_home(rel_path, user_id) -> bool:
    """Ce chemin (relatif à `MEDIA_ROOT`) est-il DANS l'arbre de CET utilisateur ?

    La frontière du pointage : `users/<uid>/…` — son dossier temporaire, sa médiathèque, les
    entrées et sorties de ses apps. Tout le reste (montage, cache, arbre d'un AUTRE utilisateur)
    n'y est pas, et se copie. La comparaison de l'identifiant est ce qui interdit à une card de
    pointer les octets d'autrui, condition du chiffrement par utilisateur.
    """
    rel = str(rel_path or '').replace('\\', '/').lstrip('/')
    return rel.startswith(f'users/{user_id}/')


def reference_or_copy(source_path, app_name: str, user_id, subfolder: str = 'input',
                      allowed_exts=None, *, for_instance=None, field=None,
                      provenance_kind=None, provenance_ref=None):
    """POINTER le fichier s'il est déjà dans l'arbre de l'utilisateur, le COPIER sinon.

    Décision de Fabien du 2026-09-23 (`MEDIA_STORAGE_TIERING §Cible`, jalon annoncé le 12/09 :
    *« sortir les fichiers médias des apps et ne faire que les POINTER »*). Même contrat de retour
    que `copy_into_app_input` — `(chemin, chemin relatif)` — pour que les importeurs ne changent
    que d'appel : les métadonnées se lisent ensuite sur le fichier POINTÉ, ce qui est le même
    fichier.

    Pourquoi c'était possible sans rien casser (mesuré) : **un `FileField` EST déjà un pointeur**
    — il stocke un chemin relatif à `MEDIA_ROOT`, et l'aperçu commun sert `/media/<ce chemin>`
    (`preview_utils`, via `field.url`). Rien dans la chaîne ne suppose que le fichier vive dans le
    dossier de l'app : la route « importer un fichier déjà sur le serveur » du synthesizer le fait
    depuis des mois.

    Ce qui se copie encore, et pourquoi :
      * un dépôt depuis le poste (il n'a pas de source dans WAMA) ;
      * un dossier CONNECTÉ (hors `MEDIA_ROOT` ; et un traitement ne doit pas lire un disque
        réseau — verdict de performance de `MEDIA_STORAGE_TIERING`) ;
      * une URL (matérialisée par `ensure_local_input`) ;
      * l'arbre d'un AUTRE utilisateur (`in_user_home` refuse) ;
      * une app qui lit ses entrées PAR DOSSIER (cam_analyzer, RTMaps) — elle garde son appel à
        `copy_into_app_input`, et le site le dit.
    Ce qui se POINTE en plus de l'arbre de l'utilisateur (2026-09-28) : un asset SYSTÈME actif
    (`is_system_asset_file`) — zone commune en lecture, jamais supprimée par une card.

    Returns:
        `(path: Path, relative_path: str)` — pointé : le chemin de la SOURCE ; copié : la copie.
    """
    from pathlib import Path

    src = Path(source_path)
    ext = src.suffix.lower()
    if allowed_exts is not None and ext not in {e.lower() for e in allowed_exts}:
        raise ValueError(f"Format non supporté : {ext}")

    rel = None
    try:
        _absolu, rel_candidat = resolve_under_media_root(str(src))
        # Un asset SYSTÈME (zone commune, sans propriétaire, hors du chiffrement par utilisateur)
        # se pointe aussi (2026-09-28) : `owns_file` ne le tient jamais pour le fichier d'une
        # card, aucune suppression de card ne l'atteint donc.
        if in_user_home(rel_candidat, user_id) or is_system_asset_file(rel_candidat):
            rel = rel_candidat
    except (OutsideMediaRoot, FileNotFoundError):
        rel = None

    if rel is None:
        return copy_into_app_input(
            src, app_name, user_id, subfolder, allowed_exts,
            for_instance=for_instance, field=field,
            provenance_kind=provenance_kind or 'temp', provenance_ref=provenance_ref)

    if for_instance is not None and field:
        # La provenance d'une entrée POINTÉE se désigne elle-même : « cette entrée EST ce
        # fichier de l'utilisateur ». La nature se dérive du chemin (temp, app, médiathèque).
        from wama.common.utils.provenance import kind_of, record_provenance
        record_provenance(for_instance, field, kind=provenance_kind or kind_of(rel),
                          ref=provenance_ref if provenance_ref is not None else rel,
                          original_name=src.name, source_path=src)
    return src, rel


def is_system_asset_file(rel_path) -> bool:
    """Ce chemin est-il le fichier d'un asset SYSTÈME actif de la médiathèque ?

    Zone commune (`SYSTEM_ASSET_ROOT`), gérée par les admins, sans propriétaire : lisible par
    tous, jamais chiffrée par utilisateur. Le préfixe seul ne suffit pas — un fichier déposé là
    sans ligne `SystemAsset` active n'est pas un asset qu'on offre.
    """
    rel = str(rel_path or '').replace('\\', '/').lstrip('/')
    if not rel.startswith(SYSTEM_ASSET_ROOT + '/'):
        return False
    from wama.media_library.models import SystemAsset
    return SystemAsset.objects.filter(file=rel, is_active=True).exists()


def readable_by(rel_path, user) -> bool:
    """Cet utilisateur peut-il DÉSIGNER ce fichier comme entrée d'une card ?

    Son propre arbre (`users/<uid>/…` : temporaire, médiathèque, entrées et sorties de ses
    apps) ou un asset système actif. ⚠ Le fichier d'un AUTRE utilisateur n'est PAS lisible ici,
    même partagé : le pointer ou le recopier dépend du modèle de clés du chiffrement par
    utilisateur, pas encore décidé (`WAMA_COLLABORATION §9`, cadre du 2026-09-28). Le jour où il
    l'est, c'est CETTE fonction qui s'étend (objet visible qui le désigne) — et nulle autre.
    """
    rel = str(rel_path or '').replace('\\', '/').lstrip('/')
    user_id = getattr(user, 'id', None)
    return bool(user_id) and (in_user_home(rel, user_id) or is_system_asset_file(rel))


#: Champ POST d'une DÉSIGNATION : le chemin (relatif à `MEDIA_ROOT`) d'un fichier que la card
#: reçoit sans qu'on le lui téléverse — choisi dans la médiathèque, glissé depuis l'arbre. Répété
#: pour plusieurs fichiers. Même vue d'upload que le dépôt, mêmes champs de volet à côté.
DESIGNATION_FIELD = 'designated_path'


class ReceivedInput:
    """UN fichier reçu par une vue d'upload : téléversé, ou DÉSIGNÉ.

    La vue lit `name` (nom d'origine : extension, libellé) et assigne `value` au champ fichier
    de l'élément. `value` est le fichier téléversé, ou le CHEMIN relatif de la désignation —
    assigner une chaîne à un `FileField` enregistre le chemin sans rien écrire : c'est le
    pointage (`reference_or_copy`). `local_path` est un chemin lisible sur le disque pour une
    désignation (extraction d'audio, comptage de pages), `None` pour un téléversement.
    """

    def __init__(self, name, value, *, local_path=None, designation=None):
        self.name = name
        self.value = value
        self.local_path = local_path
        self.designation = designation

    @property
    def designated(self) -> bool:
        return self.designation is not None

    @property
    def size(self):
        if self.designated:
            return Path(self.local_path).stat().st_size
        return getattr(self.value, 'size', None)

    @property
    def content_type(self):
        if self.designated:
            import mimetypes
            return mimetypes.guess_type(self.name)[0] or 'application/octet-stream'
        return getattr(self.value, 'content_type', None)

    def chunks(self, chunk_size=64 * 1024):
        if not self.designated:
            yield from self.value.chunks()
            return
        with open(self.local_path, 'rb') as fh:
            while True:
                block = fh.read(chunk_size)
                if not block:
                    return
                yield block

    def record(self, instance, field):
        """La PROVENANCE, une fois l'élément créé. Rien pour un téléversement : il n'a pas de
        source dans WAMA (`MEDIA_STORAGE_TIERING §8.6` D21)."""
        if not self.designated:
            return
        from wama.common.utils.provenance import kind_of, record_provenance
        record_provenance(instance, field, kind=kind_of(self.designation), ref=self.designation,
                          original_name=self.name, source_path=Path(self.local_path))


class ReceivedInputs(list):
    """Les entrées reçues, plus `refusal` : le motif du premier refus (désignation illisible,
    hors `MEDIA_ROOT`, absente). Une vue qui ne reçoit RIEN le rend tel quel — un refus se dit."""
    refusal = ''


def received_inputs(request, user, app_name: str, field: str = 'file',
                    subfolder: str = 'input') -> ReceivedInputs:
    """Ce qu'une vue d'upload reçoit : les fichiers TÉLÉVERSÉS sous `field`, puis les fichiers
    DÉSIGNÉS sous `DESIGNATION_FIELD` — dans cet ordre.

    Une désignation passe trois gardes avant d'être reçue : le confinement dans `MEDIA_ROOT`
    (`resolve_under_media_root`, traversée `..` comprise), l'existence du fichier, et la
    lisibilité pour CET utilisateur (`readable_by`). Elle est ensuite POINTÉE ou copiée par
    `reference_or_copy` — la même décision que « Envoyer vers », en un seul endroit.
    Ne lève jamais : un refus est rangé dans `refusal`.
    """
    received = ReceivedInputs(ReceivedInput(f.name, f) for f in request.FILES.getlist(field))
    for raw in request.POST.getlist(DESIGNATION_FIELD):
        try:
            abs_path, rel = resolve_under_media_root(raw)
        except (OutsideMediaRoot, FileNotFoundError) as exc:
            received.refusal = received.refusal or str(exc)
            continue
        if not readable_by(rel, user):
            received.refusal = received.refusal or f"Fichier non accessible : {os.path.basename(rel)}"
            continue
        path, value = reference_or_copy(abs_path, app_name, user.id, subfolder)
        received.append(ReceivedInput(os.path.basename(rel), value,
                                      local_path=str(path), designation=rel))
    return received


class UploadToUserPath:
    """
    Callable class for Django FileField upload_to that generates user-specific paths.
    This class is serializable by Django migrations.

    Usage in models.py:
        file = models.FileField(upload_to=UploadToUserPath('anonymizer', 'input'))
    """

    def __init__(self, app_name: str, subfolder: str = 'input'):
        self.app_name = app_name
        self.subfolder = subfolder

    def __call__(self, instance, filename):
        user_id = instance.user_id if hasattr(instance, 'user_id') else instance.user.id
        # Ensure directory exists
        path = get_app_media_path(self.app_name, user_id, self.subfolder)
        path.mkdir(parents=True, exist_ok=True)
        # Generate unique filename if needed
        unique_name = get_unique_filename(path, filename)
        return get_relative_media_path(self.app_name, user_id, self.subfolder, unique_name)

    def deconstruct(self):
        """Required for Django migrations serialization."""
        return (
            'wama.common.utils.media_paths.UploadToUserPath',
            [self.app_name, self.subfolder],
            {}
        )


#: Racine des assets SYSTÈME de la médiathèque — sans propriétaire, gérés par les admins
#: (`MEDIA_STORAGE_TIERING §8bis`). Rangés par NATURE depuis le 2026-09-22 (décision de Fabien,
#: ligne D18 du §8.6) : ils étaient à plat, 9 avatars et 28 voix mêlés.
SYSTEM_ASSET_ROOT = 'media_library/system'


def system_asset_relpath(asset_type: str, filename: str) -> str:
    """Chemin relatif (sous `MEDIA_ROOT`) d'un asset système : un sous-dossier par NATURE.

    Par NATURE seulement — une voix ne devient pas un avatar, le chemin ne ment donc jamais.
    Jamais par TAXONOMIE (langue, âge, genre vivent dans `attributes`, décision D3) ni par
    VISIBILITÉ (mutable, décision D2) : le chemin ne porte que ce qui ne change pas.
    C'est le SEUL endroit qui compose ce chemin — l'`upload_to` et la commande de rangement
    (`organize_system_assets`) le lisent tous deux ici.
    """
    nature = ''.join(c for c in (asset_type or '').strip().lower() if c.isalnum() or c in '_-')
    return f'{SYSTEM_ASSET_ROOT}/{nature or "other"}/{os.path.basename(filename)}'


class UploadToSystemAssetPath:
    """`upload_to` de `SystemAsset.file` — `media_library/system/<asset_type>/<fichier>`.

    Classe appelable et DÉCONSTRUCTIBLE (sérialisable en migration), sur le patron
    d'`UploadToUserPath` ci-dessus. Les collisions de nom sont laissées au stockage Django,
    comme avant (l'ancien `upload_to` était une chaîne fixe).
    """

    def __call__(self, instance, filename):
        return system_asset_relpath(getattr(instance, 'asset_type', ''), filename)

    def deconstruct(self):
        """Required for Django migrations serialization."""
        return ('wama.common.utils.media_paths.UploadToSystemAssetPath', [], {})


def upload_to_user_input(app_name: str):
    """
    Convenience function to create an UploadToUserPath for input folder.

    Usage in models.py:
        file = models.FileField(upload_to=upload_to_user_input('anonymizer'))
    """
    return UploadToUserPath(app_name, 'input')


def upload_to_user_output(app_name: str):
    """
    Convenience function to create an UploadToUserPath for output folder.

    Usage in models.py:
        output_file = models.FileField(upload_to=upload_to_user_output('anonymizer'))
    """
    return UploadToUserPath(app_name, 'output')


def migrate_file_to_user_path(
    old_path: Union[str, Path],
    app_name: str,
    user_id: Union[int, str],
    subfolder: str = 'input',
    move: bool = True
) -> Optional[str]:
    """
    Migrate a file from old location to new user-specific location.

    Args:
        old_path: Current file path (relative to MEDIA_ROOT or absolute)
        app_name: Application name
        user_id: User ID
        subfolder: Target subfolder ('input' or 'output')
        move: If True, move the file. If False, copy it.

    Returns:
        New relative path for storing in DB, or None if file doesn't exist
    """
    import shutil

    # Handle relative paths
    if not os.path.isabs(old_path):
        old_path = Path(settings.MEDIA_ROOT) / old_path
    else:
        old_path = Path(old_path)

    if not old_path.exists():
        return None

    # Get new path
    new_dir = get_app_media_path(app_name, user_id, subfolder)
    new_dir.mkdir(parents=True, exist_ok=True)

    filename = old_path.name
    unique_name = get_unique_filename(new_dir, filename)
    new_path = new_dir / unique_name

    # Move or copy
    if move:
        shutil.move(str(old_path), str(new_path))
    else:
        shutil.copy2(str(old_path), str(new_path))

    return get_relative_media_path(app_name, user_id, subfolder, unique_name)
