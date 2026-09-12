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
