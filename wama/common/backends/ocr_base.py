"""
Contrat des moteurs d'OCR — spécialisation de `BaseModelBackend` (2026-10-07).

POURQUOI UN CONTRAT. olmOCR, docTR et GLM-OCR avaient déjà la MÊME signature (`run(file_path,
mode, language, progress_cb, on_partial)`) sans qu'elle soit déclarée nulle part : rien ne la
disait au rôle `backend` qui écrit un nouveau moteur, et la résolution ne pouvait pas borner un
moteur partagé à sa tâche. Déclaré ici et dans `backend_inventory.TASK_CONTRACTS`, il sert trois
lecteurs, une seule table :
  • la RÉSOLUTION — un backend OCR sous un moteur qui sert plusieurs tâches (Ollama héberge le chat
    ET `glm-ocr`) n'y exécute que l'OCR ;
  • le rôle `backend` — la méthode à écrire pour un moteur OCR nouveau, lue par AST ;
  • la porte commune `manager.run_contract` — elle passe à `run` les valeurs de l'élément PAR
    LEUR NOM : les arguments portent les noms des paramètres du schéma (`mode`, `language`).

LES NOMS SUIVENT LES CONVENTIONS EXISTANTES (alignés le 2026-10-09, la veille ils étaient propres
au reader) : le fichier arrive sous le nom de son PORT (`work_file`, celui que les modèles d'OCR
déclarent en `inputs_required`) — la règle « un port arrive dans l'argument du MÊME NOM » de
l'outil `add_to_<app>` (`generic_runner.port_arguments`) ; la progression sous `progress_callback`,
le nom de tous les autres contrats et des routes par nature.

Ce que le contrat NE fait pas : choisir le modèle. La clé de catalogue choisie arrive par
`catalogue_key` (contrat commun) ; un moteur qui sert plusieurs modèles la lit.
"""
import logging
import re
import zlib
from abc import abstractmethod
from typing import Callable, Optional

from wama.common.backends.base import BaseModelBackend

logger = logging.getLogger(__name__)

#: Une sortie plus compressible que cela est une BOUCLE, pas un texte : le modèle répète le même
#: passage jusqu'au plafond de jetons. Même mesure que Whisper (`compression_ratio_threshold`),
#: seuil plus haut car une page d'OCR est longue : un texte réel se compresse d'un facteur 2 à 4.
DEGENERATE_COMPRESSION_RATIO = 8.0
#: En deçà, une page est trop courte pour qu'une répétition se distingue d'un texte bref.
DEGENERATE_MIN_CHARS = 1000


def is_degenerate_output(text: str) -> bool:
    """Le texte rendu par un moteur d'OCR VLM est-il une boucle de répétition ?

    Mesuré le 2026-10-12 (card reader #1335, note manuscrite de 1848×4000) : GLM-OCR rend soit
    une erreur d'Ollama (« token repeat limit reached »), soit — échantillonné, ou par bandes —
    12 535 caractères du MÊME paragraphe, ou une colonne de « 20 ». Rangé tel quel, c'est un
    SUCCÈS rempli de bruit que l'assistant aurait servi comme le texte du document."""
    if not text or len(text) < DEGENERATE_MIN_CHARS:
        return False
    raw = text.encode('utf-8')
    return len(raw) / len(zlib.compress(raw)) > DEGENERATE_COMPRESSION_RATIO


#: En deçà de cette confiance, le classifieur d'orientation n'est pas suivi : l'image part telle
#: quelle. Mesuré sur la card #1335 et ses trois rotations : 0,89 à 0,98.
ORIENTATION_MIN_CONFIDENCE = 0.6
_ORIENTATION_PREDICTOR = []


def _orientation_predictor():
    """Le classifieur d'orientation de PAGE de docTR (`mobilenet_v3_small_page_orientation`,
    6 Mo, CPU, ~0,04 s par image), chargé une fois par process. Poids sous `DOCTR_CACHE_DIR`
    (posé dans `settings.py`). None si docTR manque : le redressement est un confort."""
    if not _ORIENTATION_PREDICTOR:
        try:
            from doctr.models import page_orientation_predictor
            _ORIENTATION_PREDICTOR.append(page_orientation_predictor(pretrained=True))
        except Exception:
            logger.warning("[OCR] classifieur d'orientation indisponible — images non redressées",
                           exc_info=True)
            _ORIENTATION_PREDICTOR.append(None)
    return _ORIENTATION_PREDICTOR[0]


def upright_image(image_path: str, dest_dir: str) -> str:
    """Le chemin d'une image DROITE : l'étiquette EXIF d'orientation appliquée, puis la rotation
    (0/90/180/270°) que prédit le classifieur de docTR. L'original n'est jamais modifié ; une
    copie redressée est écrite dans `dest_dir` (dossier de travail de l'appelant). Image déjà
    droite, prédiction incertaine ou classifieur absent : le chemin d'origine revient.

    POURQUOI AVANT TOUT MOTEUR (2026-10-12, card reader #1335) : une note photographiée de côté,
    sans étiquette EXIF. GLM-OCR n'y lisait rien et bouclait jusqu'au plafond de jetons ; la même
    image redressée de 90° était lue juste. La rotation est une propriété de la PHOTO, pas du
    moteur : un seul redressement sert glm-ocr, olmOCR et docTR."""
    from pathlib import Path

    try:
        import numpy as np
        from PIL import Image, ImageOps

        with Image.open(image_path) as source:
            exif_rotated = (source.getexif().get(0x0112) or 1) != 1   # 0x0112 = Orientation
            image = ImageOps.exif_transpose(source).convert('RGB')
        angle = 0
        predictor = _orientation_predictor()
        if predictor is not None:
            _, angles, confidences = predictor([np.array(image)])
            if float(confidences[0]) >= ORIENTATION_MIN_CONFIDENCE:
                angle = int(angles[0])
        if not angle and not exif_rotated:
            return image_path
        if angle:
            # Le classifieur rend l'angle dont la page est TOURNÉE : la rotation de même angle la
            # redresse (vérifié sur les quatre rotations de la card #1335).
            image = image.rotate(angle, expand=True)
            logger.info(f"[OCR] image redressée de {angle}° : {Path(image_path).name}")
        upright = Path(dest_dir) / f"upright_{Path(image_path).stem}.jpg"
        image.save(upright, format='JPEG', quality=95)
        return str(upright)
    except Exception:
        logger.warning(f"[OCR] redressement impossible, image telle quelle : {image_path}",
                       exc_info=True)
        return image_path


#: Lignes non vides consécutives dont le RETOUR, à l'identique, marque le début de la recopie.
LOOP_WINDOW_LINES = 4


def trim_repetition(text: str) -> tuple[str, bool]:
    """Coupe une sortie d'OCR au PREMIER RETOUR d'une suite de `LOOP_WINDOW_LINES` lignes non
    vides déjà lue. Rend `(texte, coupé ?)`. À n'appeler que sur une sortie déjà reconnue comme
    boucle (`is_degenerate_output`) : un vrai document peut répéter quatre lignes.

    Mesuré le 2026-10-12 (card #1335, image redressée) : GLM-OCR lit la note JUSTE une fois —
    « Personnalisation du pipeline par utilisation. Chaque utilisateur peut personnaliser / créer
    son propre pipeline… » — puis, faute de s'arrêter, la recopie jusqu'au plafond de jetons, en
    intercalant des en-têtes qui varient d'une copie à l'autre : une période EXACTE ne s'y voit
    que tard (deux copies et demie gardées, mesuré). Le premier passage est la lecture ; la suite
    n'ajoute rien. Lignes comparées sans les espaces de bord.
    ⚠ Corrigé le 2026-10-28 (question de Fabien, card #1485) : « I24 Rotation » n'est PAS un
    en-tête inventé — c'est le titre manuscrit « I24Motion », MAL LU, de la première ligne de la
    note, à côté de « WAMA ». Seule la balise « ```markdown » est inventée
    (`unwrap_format_fences`), et le modèle rend cette première ligne APRÈS le corps du texte."""
    lines = (text or '').splitlines()
    filled = [(index, line.strip()) for index, line in enumerate(lines) if line.strip()]
    seen = set()
    for position in range(len(filled) - LOOP_WINDOW_LINES + 1):
        window = tuple(t for _, t in filled[position:position + LOOP_WINDOW_LINES])
        if window in seen:
            return '\n'.join(lines[:filled[position][0]]).rstrip(), True
        seen.add(window)
    return text, False


def loop_cut_notice(pages) -> dict:
    """La REMARQUE d'une lecture coupée au premier passage (`trim_repetition`), telle qu'une glu la
    rend au squelette (`notices`) et que la card la montre en pastille près du nombre de mots
    (2026-10-29, décision de Fabien). La coupe peut se tromper dans les deux sens — un premier
    passage incomplet, une vraie répétition prise pour une boucle — : sans elle, rien ne dit de
    vérifier. `pages` : numéros de page (à partir de 1)."""
    pages = sorted({int(p) for p in pages or ()})
    where = (f" (page {pages[0]})" if len(pages) == 1
             else f" (pages {', '.join(map(str, pages))})" if pages else '')
    return {'key': 'ocr_loop_cut', 'label': 'Lecture coupée', 'icon': 'fa-scissors',
            'title': f"Le moteur répétait le même passage{where} : seule la première lecture est "
                     f"gardée. Si le texte semble incomplet, relancez avec un autre moteur."}


#: Une balise de bloc qui annonce du TEXTE (« ```markdown », « ```text ») : un modèle de vision
#: l'ajoute par habitude de format, aucune page ne la porte à l'encre. Un bloc de CODE annoncé
#: (« ```python ») est gardé — il peut rendre la structure d'une page imprimée.
_FORMAT_FENCE = re.compile(r'^\s*```\s*(markdown|md|text|plaintext|plain)\s*$', re.I)
_BARE_FENCE = re.compile(r'^\s*```\s*$')


def unwrap_format_fences(text: str) -> str:
    """Retire d'une lecture d'OCR les balises de format qu'un modèle de vision y glisse, en gardant
    ce qu'elles entourent : l'ouvrante « ```markdown » (ou `md`, `text`…) et la clôture nue qui lui
    répond, s'il y en a une — une boucle coupée (`trim_repetition`) la laisse souvent sans clôture.

    Card reader #1485 (2026-10-28, relevé par Fabien) : GLM-OCR a rendu la première ligne de la
    note (« I24Motion », lu « I24 Rotation », et « WAMA ») dans un bloc « ```markdown » ; la mise en
    forme l'a refermé, et la page de lecture montrait un bloc de code là où la feuille porte deux
    titres soulignés."""
    lines, kept, open_wrapper = (text or '').split('\n'), [], False
    for line in lines:
        if _FORMAT_FENCE.match(line):
            open_wrapper = True
            continue
        if open_wrapper and _BARE_FENCE.match(line):
            open_wrapper = False
            continue
        kept.append(line)
    return '\n'.join(kept).strip() if len(kept) != len(lines) else text


class OCRBackend(BaseModelBackend):
    """Un moteur d'OCR : un document (PDF ou image) → son texte."""

    #: Pages (à partir de 1) dont la lecture tournait en boucle et a été COUPÉE au premier passage
    #: lors du DERNIER `run` — remis à vide au début de chaque `run` d'un moteur qui coupe, lu par l'appelant après lui
    #: (`loop_cut_notice`). Un moteur qui ne coupe jamais n'a rien à faire.
    cut_pages: tuple = ()

    @abstractmethod
    def run(
        self,
        work_file: str,
        mode: str = 'auto',
        language: str = '',
        progress_callback: Optional[Callable[[int, str], None]] = None,
        on_partial: Optional[Callable[[str], None]] = None,
    ) -> str:
        """Texte du document `work_file`.

        work_file         : le fichier du port `work_file` ;
        mode              : 'auto' | 'printed' | 'handwritten' — indication, que le moteur peut
                            ignorer (la capacité `params` du catalogue dit ceux qu'il LIT) ;
        language          : code de langue indicatif ('' = détection) ;
        progress_callback : `(pourcentage, message)` ;
        on_partial        : `(texte cumulé)` après chaque page — aperçu « pendant » (preview_utils).
        """

    def read_lines(
        self,
        work_file: str,
        language: str = '',
        progress_callback: Optional[Callable[[int, str], None]] = None,
    ) -> list:
        """Le texte du document AVEC SA PLACE — une entrée par page, dans l'ordre :

            {'width': W, 'height': H, 'unit': 'pt' | 'px',
             'lines': [{'bbox': [x0, y0, x1, y1], 'text': '…', 'conf': 0.97,
                        'words': [{'bbox': [...], 'text': '…', 'conf': 0.99}]}]}

        Coordonnées dans l'unité de la PAGE, origine en haut à gauche : en points pour un PDF (celles
        que `document_text` lit sur un PDF natif, `get_text('dict')`), en pixels de l'image d'origine
        pour une image ; `conf` entre 0 et 1. Les mots `{'text', 'bbox'}` sont ceux qu'attend la
        structure des tableaux (`table_transformer_backend.extract_tables`).

        Des LIGNES, pas des paragraphes : réunir les lignes en blocs est le travail de qui réécrit
        la page. Mesuré le 2026-10-29 (scan à 150 dpi de deux pages d'article, lignes natives pour
        vérité) : docTR retrouve 44/46 et 54/57 lignes, texte identique en médiane ; son propre
        regroupement en blocs (`resolve_blocks`) mêle deux paragraphes dans 3 blocs sur 9 et 4 sur 8.

        Réservé aux moteurs qui DÉCLARENT `supports_text_positions` (2026-10-29) ; les autres ne
        rendent que le texte (`run`) et le disent ici plutôt que de rendre une page vide. Méthode
        concrète, pas abstraite : le contrat n'a qu'UNE méthode de travail (`manager._work_method`),
        comme `MusicGenerationBackend.plan_score`."""
        raise NotImplementedError(
            f"{type(self).__name__} ne rend pas la place du texte (`supports_text_positions` non déclaré).")

    def process(self, **kwargs) -> str:
        """Point d'entrée métier générique (contrat commun) → délègue à `run()`."""
        return self.run(**kwargs)
