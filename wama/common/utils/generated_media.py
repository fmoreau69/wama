"""Marquer un média GÉNÉRÉ PAR IA dans ses MÉTADONNÉES — brique commune (2026-09-30).

DÉCISION DE FABIEN (2026-09-30), après l'état des lieux « voix, droits, RGPD » : pour un usage
de RECHERCHE (consignes expérimentales produites par le synthesizer), **on ajoute seulement de la
métadonnée** — pas de tampon audio (filigrane) pour le moment. Un chantier de réflexion COMPLET,
pour TOUS les médias (transparence des contenus générés, filigrane, standard de provenance), est
consigné à part ; cette brique en est la première marche, conçue pour l'accueillir.

CE QU'ELLE FAIT : réécrit le fichier en COPIE DE FLUX (`-c copy`, aucun ré-encodage, aucune perte)
avec un commentaire lisible — « Contenu généré par IA (WAMA …) » — et l'outil qui l'a produit. Les
conteneurs le rangent chacun à leur place (WAV : LIST/INFO ICMT ; MP3 : ID3 COMM ; MP4/MKV :
balise `comment`) ; un lecteur, un explorateur de fichiers ou `ffprobe` le montrent.

⚠ UN ÉCHEC NE FAIT JAMAIS ÉCHOUER LE TRAVAIL : la mention est une information SUR le résultat,
pas le résultat (même règle que `provenance.py`). Le fichier d'origine n'est remplacé qu'une fois
la copie marquée écrite en entier.
"""
import logging
import os
import subprocess
from datetime import date

logger = logging.getLogger(__name__)

#: Le texte posé. Daté et nommé : qui l'a produit, avec quoi, et, pour une voix, si elle est clonée.
NOTICE = 'Contenu généré par IA (WAMA {app}, modèle {model}{detail}) — {day}'
ENCODER = 'WAMA — contenu généré par IA'


def generated_notice(app: str, model: str = '', detail: str = '') -> str:
    """Le texte de la mention, tel qu'il sera écrit dans le fichier."""
    return NOTICE.format(app=app, model=model or 'inconnu',
                         detail=f', {detail}' if detail else '', day=date.today().isoformat())


def mark_as_generated(path: str, *, app: str, model: str = '', detail: str = '') -> bool:
    """Pose la mention « généré par IA » dans les métadonnées de `path`. Rend True si c'est fait.

    Ne lève jamais : un fichier illisible, un conteneur qui refuse, un ffmpeg absent laissent le
    fichier tel quel et journalisent un avertissement.
    """
    try:
        from wama.common.utils.ffmpeg_utils import adapt_path_for_ffmpeg, get_ffmpeg_exe
        if not path or not os.path.isfile(path):
            return False
        root, ext = os.path.splitext(path)
        tmp = f'{root}.marking{ext}'
        exe = get_ffmpeg_exe()
        subprocess.run(
            [exe, '-nostdin', '-y', '-loglevel', 'error', '-i', adapt_path_for_ffmpeg(path, exe),
             '-map', '0', '-map_metadata', '0', '-c', 'copy',
             '-metadata', f'comment={generated_notice(app, model, detail)}',
             '-metadata', f'encoded_by={ENCODER}',
             adapt_path_for_ffmpeg(tmp, exe)],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True, timeout=120)
        if not os.path.isfile(tmp) or os.path.getsize(tmp) == 0:
            return False
        os.replace(tmp, path)
        return True
    except Exception as exc:
        logger.warning('[generated_media] mention non posée sur %s : %s', path, exc)
        try:
            if 'tmp' in locals() and os.path.isfile(tmp):
                os.remove(tmp)
        except OSError:
            pass
        return False
