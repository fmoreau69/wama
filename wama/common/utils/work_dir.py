"""Dossier de TRAVAIL jetable — les fichiers intermédiaires ne vivent pas dans `media/`.

POURQUOI (mesuré le 2026-08-25)
    `media/avatarizer/` pesait **1,69 Go pour 2101 fichiers, dont 99,6 % de PNG** : les frames
    intermédiaires de CodeFormer (`cropped_faces/`, `restored_faces/`, `final_results/`),
    écrites directement dans le dossier de sortie du job et jamais nettoyées. Un seul job —
    `job_11` — portait **1715,7 Mo pour une vidéo de 0,70 Mo**.

    `media/` ne contient que trois choses (`MEDIA_STORAGE_TIERING.md`) :
    `<app>/<user>/input/`, `<app>/<user>/output/`, `users/`. Un fichier de travail n'en est pas :
    il est sauvegardé par le miroir, compté par le tiering et servi par Apache pour rien.

CE QUE ÇA REMPLACE
    Le patron `mkdtemp` + `rmtree` est recopié sur **11 sites** du dépôt, et le nettoyage n'y est
    garanti (par un `finally`) que sur 5 d'entre eux. Ici il n'est plus une convention qu'on peut
    oublier : il est **structurel**, porté par le `with`.

    ⚠ Les 6 autres sites n'ont PAS été audités un par un — au moins un délègue son nettoyage à
    l'appelant par contrat documenté (`reader/backends/glm_ocr_backend.py:67`). Les porter est un
    chantier d'adoption à part, à mener site par site : ne pas les convertir en masse sur la foi
    d'un relevé automatique.

USAGE
    from wama.common.utils.work_dir import work_dir

    with work_dir('avatarizer_codeformer') as travail:
        produire_des_intermediaires(dans=travail)
        livrable = recuperer(travail)
        shutil.move(livrable, destination_finale)   # ⚠ SORTIR ce qu'on garde AVANT la fin du bloc
    # ici le dossier n'existe plus, y compris si le bloc a levé
"""
import logging
import os
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path

logger = logging.getLogger(__name__)

#: Conserver les dossiers de travail au lieu de les supprimer (diagnostic d'un pipeline).
#: Même esprit que `FFMPEG_BINARY` : une échappatoire déclarée, pas un comportement caché.
_GARDER = os.environ.get('WAMA_GARDER_WORK_DIR', '').strip() not in ('', '0', 'false', 'False')


@contextmanager
def work_dir(prefix: str = 'wama_work'):
    """Crée un dossier de travail jetable et le supprime À LA SORTIE, même sur exception.

    Le dossier vit dans le temporaire du système — **jamais sous `MEDIA_ROOT`** : c'est
    précisément ce mélange qui a fait grossir `media/`.

    Rend un `Path`. Ce qu'on veut garder doit être DÉPLACÉ hors du dossier avant la fin du bloc.
    """
    chemin = Path(tempfile.mkdtemp(prefix=f"{prefix}_"))
    try:
        yield chemin
    finally:
        if _GARDER:
            logger.warning("[work_dir] conservé (WAMA_GARDER_WORK_DIR) : %s", chemin)
        else:
            # `ignore_errors` : un verrou Windows sur un fichier encore ouvert ne doit pas
            # transformer un traitement RÉUSSI en échec. Le temporaire système sera balayé.
            shutil.rmtree(chemin, ignore_errors=True)


def purge_job_dir(base_dir, job_id, *, prefix: str = 'job_') -> int:
    """Supprime le dossier de job `<base_dir>/<prefix><job_id>/`. Rend le nombre d'octets libérés.

    ⚠ Répond au SECOND défaut mesuré le 2026-08-25 : `avatarizer/views.delete()` ne retirait que
    les trois `FileField` (`safe_delete_file`) — le dossier du job survivait à la suppression de
    la card. Relevé : **13 dossiers `job_*` orphelins** contre 4 encore rattachés, et les
    1715,7 Mo appartenaient à une card **qui n'existait plus**.

    ⚠ Ne PAS généraliser à l'aveugle : au 2026-08-25, l'avatarizer est la SEULE app à créer un
    dossier par job sous `MEDIA_ROOT` (vérifié). Cette fonction est ici parce que c'est le bon
    domicile pour la prochaine, pas parce que d'autres en souffrent déjà.
    """
    from django.conf import settings

    base = Path(base_dir).resolve()
    cible = (base / f"{prefix}{job_id}").resolve()
    media = Path(settings.MEDIA_ROOT).resolve()

    # Trois gardes, aucune redondante : rester sous MEDIA_ROOT, rester sous la base annoncée,
    # et porter le préfixe attendu. Un rmtree mal ciblé ici effacerait des médias irremplaçables.
    if not str(cible).startswith(str(media) + os.sep):
        return 0
    if cible.parent != base:
        return 0
    if not cible.name.startswith(prefix) or not cible.is_dir():
        return 0

    octets = 0
    try:
        octets = sum(f.stat().st_size for f in cible.rglob('*') if f.is_file())
        shutil.rmtree(cible, ignore_errors=True)
    except Exception:
        logger.debug("[work_dir] purge de %s ignorée", cible, exc_info=True)
        return 0
    return octets
