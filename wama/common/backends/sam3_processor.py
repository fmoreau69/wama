"""
SAM3 Processor for WAMA Anonymizer
Handles image and video segmentation using SAM3 (Segment Anything Model 3)
for prompt-based object blurring.

This module provides the SAM3Processor class which is parallel to the YOLO-based
Anonymize class, enabling text prompt-driven segmentation and blurring.
"""

import os
import gc
import re
import cv2
import torch
import numpy as np
import logging

from PIL import Image

from .detection_base import DetectionBackend
from wama.common.utils.video_utils import is_image
from wama.settings import MEDIA_INPUT_ROOT, MEDIA_OUTPUT_ROOT, MODEL_PATHS, AI_MODELS_DIR

logger = logging.getLogger(__name__)


# ⚠⚠ `setup_sam3_hf_environment()` RETIRÉE le 2026-09-07 (demande de Fabien) — elle était le
# DERNIER site à muter un jeton HuggingFace dans l'environnement du processus.
#
# Ce qu'elle faisait, et pourquoi plus rien ne doit le faire :
#   • elle lisait un SECOND exemplaire du jeton dans un fichier `token` du dossier du modèle,
#     alors que le socle en a UN SEUL DOMICILE depuis le 2026-09-02 — `.env`, lu par
#     `load_dotenv()` et promu en `HF_TOKEN` au démarrage (`settings.py`). Deux domiciles pour
#     un secret, c'est un domicile de trop : celui qui n'est pas le bon finit par diverger ;
#   • elle écrivait ce jeton dans le `$HOME` de l'utilisateur (`HfFolder.save_token`) — hors du
#     dépôt, hors de toute déclaration, exactement ce que la règle des poids hors HuggingFace
#     interdit pour les fichiers de modèles ; un secret mérite au moins la même rigueur ;
#   • son bloc de CACHE avait déjà été retiré le 06/09 (SAM3 était le dernier consommateur de
#     `hf_cache_scope`). Il ne restait donc que le jeton — la fonction entière était le résidu.
#
# `huggingface_hub` lit `HF_TOKEN` dans l'environnement : le jeton posé par le socle suffit,
# et le dépôt gated se charge sans que personne ne touche `os.environ`.
# Ne JAMAIS réintroduire de mutation d'environnement ici (ROADMAP §5b).

# ⚠ HISTORIQUE, corrigé le 2026-09-06 — ce bloc prescrivait la bascule `hf_cache_scope`
# au motif que « la lib sam3 n'accepte pas de `cache_dir=` ». Le motif était VRAI et la
# conclusion FAUSSE : la lib accepte `checkpoint_path=` + `load_from_HF=False`, ce qui est
# mieux qu'un `cache_dir=`. La bascule (2026-08-12, après la fuite inter-apps qui vidait le
# squelette olmOCR) était le bon réflexe avec l'information de l'époque ; elle n'a
# simplement jamais été re-mesurée.
#
# Le chargement passe désormais par la 3ᵉ voie (`common/utils/hf_weights.poids_locaux`) :
# on résout les poids DANS le dossier du modèle, on donne un chemin, et l'environnement du
# processus n'est jamais touché — ni durablement, ni « le temps d'un with ». SAM3 était le
# DERNIER consommateur de `hf_cache_scope`.
# Ne JAMAIS revenir à une mutation d'environnement, permanente ou scopée (ROADMAP §5b).


def _sam_root():
    return MODEL_PATHS.get('vision', {}).get('sam') \
        or (AI_MODELS_DIR / 'models' / 'vision' / 'sam')


def load_sam3_image_model():
    """Le modèle IMAGE de SAM3, chargé depuis ses poids LOCAUX — le seul chemin de chargement
    (2026-09-27). Les poids sont résolus dans le dossier du modèle (`poids_locaux`, 3ᵉ voie,
    téléchargés là s'ils manquent) et la lib reçoit un CHEMIN (`load_from_HF=False`) : ni jeton
    au chargement, ni cache partagé, ni environnement touché. Le cam_analyzer appelait
    `build_sam3_image_model()` nu — la lib passait alors par le Hub avec le jeton d'instance.
    """
    import os

    from sam3.model_builder import build_sam3_image_model

    from wama.common.utils.hf_weights import poids_locaux
    snapshot = poids_locaux('facebook/sam3', _sam_root(), patterns=['sam3.pt', 'config.json'])
    return build_sam3_image_model(checkpoint_path=os.path.join(snapshot, 'sam3.pt'),
                                  load_from_HF=False)


class SAM3Processor(DetectionBackend):
    """
    SAM3-based processor for prompt-driven object segmentation and blurring.

    This class provides similar functionality to the YOLO-based Anonymize class,
    but uses SAM3 (Segment Anything Model 3) for text prompt-based segmentation.

    Args:
        source_dir: Custom input directory (defaults to MEDIA_INPUT_ROOT)
        destination_dir: Custom output directory (defaults to MEDIA_OUTPUT_ROOT)

    Usage (détection seule depuis le 2026-10-04 — le floutage se joue depuis le document) :
        processor = SAM3Processor()
        processor.load_model('auto')
        doc = processor.detect(media_path='/path/to/video.mp4', sam3_prompt='face, license plate')
    """

    def __init__(self, source_dir=None, destination_dir=None):
        self.device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        logger.info(f"[SAM3] Using device: {self.device}")
        print(f"[SAM3] Using device: {self.device}")

        # Path settings - use custom paths or fall back to Django settings
        self.source = str(source_dir) if source_dir else str(MEDIA_INPUT_ROOT)
        self.destination = str(destination_dir) if destination_dir else str(MEDIA_OUTPUT_ROOT)
        os.makedirs(self.source, exist_ok=True)
        os.makedirs(self.destination, exist_ok=True)

        self.input_path = None

        # Model instances (lazy loaded)
        self.image_model = None
        self.image_processor = None
        self.video_predictor = None
        self._model_loaded = False

        # Processing settings
        self.text_prompt = ""
        self.confidence_threshold = 0.3


    # ── Contrat commun (BaseModelBackend) ────────────────────────────────────
    # Repli d'empreinte si la mesure autour du chargement n'est pas concluante.
    # 3 Go = ce que le catalogue AIModel déclare pour SAM3 (model_registry).
    #: Moteur piloté (contrat commun). ⚠ Déclaré le 2026-09-06 : cette classe vit HORS
    #: du paquet `backends/`, donc le registre ne la voit pas et l'invariant « tout
    #: backend concret déclare ENGINE » ne pouvait pas la rattraper — angle mort mesuré
    #: ce jour. La déclaration est posée MAINTENANT pour que le déplacement à venir
    #: n'ait plus qu'à déplacer.
    ENGINE = 'sam3'
    REQUIRED_PACKAGES = ['sam3']
    recommended_vram_gb = 3

    @property
    def is_loaded(self) -> bool:
        return self._model_loaded

    def unload(self) -> None:
        """
        Libère les modèles SAM3 (et la réservation VRAM, via l'enveloppe du contrat commun).

        `cleanup()` reste le point d'entrée historique : il libère EN PLUS le writer vidéo.
        """
        if not self._model_loaded and self.image_model is None:
            return
        self.image_model = None
        self.image_processor = None
        self.video_predictor = None
        self._model_loaded = False
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        logger.info("[SAM3] Models unloaded ✓")

    # `load_model(model_type, **kwargs)` (nom historique, hérité de DetectionBackend) délègue ICI.
    def load(self, model_type='auto', **kwargs) -> bool:
        """
        Load SAM3 model for image or video processing.

        Args:
            model_type: 'image', 'video', or 'auto' (detects based on input)
            **kwargs: Additional arguments passed to model builder

        Raises:
            ImportError: If SAM3 is not installed
            RuntimeError: If model loading fails
        """
        if self._model_loaded:
            logger.info("[SAM3] Model already loaded")
            return True

        # Token HF (global, inoffensif) — la bascule du CACHE, elle, est confinée ci-dessous.

        try:
            # Import SAM3 modules
            # Note: We only import the image model as video predictor requires 'triton' (Linux only)
            from sam3.model.sam3_image_processor import Sam3Processor as Sam3ImageProcessor

            if model_type in ['image', 'auto']:
                logger.info("[SAM3] Loading image model...")
                print("[SAM3] Loading image model...")
                # 3ᵉ VOIE (2026-09-06) — remplace la bascule d'environnement `hf_cache_scope`,
                # dont SAM3 était le DERNIER consommateur. On résout les poids nous-mêmes DANS
                # le dossier du modèle, puis on donne à la lib un CHEMIN. L'environnement du
            # processus n'est jamais touché.
                #
                # ⚠ Le commentaire d'en-tête de ce fichier affirmait « la lib sam3 n'accepte pas
                # de `cache_dir=` » — exact, mais elle accepte MIEUX : `checkpoint_path=` +
                # `load_from_HF=False` (signature vérifiée dans `sam3/model_builder.py`). La
                # bascule n'était donc pas imposée par la lib, seulement par ce qu'on croyait
                # d'elle. *Une contrainte non re-mesurée devient une habitude.*
                #
                # Ce que la bascule laissait passer : elle restaure l'environnement, JAMAIS les
                # fichiers — tout ce que HF téléchargeait pendant la fenêtre (sous-dépendances
                # comprises) restait dans `vision/sam/`. C'est le mécanisme exact qui a déposé
                # `timm/resnet18` dans le dossier de table-transformer.
                # (Corps extrait le 2026-09-27 dans `load_sam3_image_model`, que le cam_analyzer
                # appelle aussi : un seul chargement de SAM3.)
                self.image_model = load_sam3_image_model()
                self.image_processor = Sam3ImageProcessor(self.image_model)
                logger.info("[SAM3] Image model loaded successfully")
                print("[SAM3] Image model loaded successfully")

            # Note: Video predictor requires 'triton' which is not available on Windows.
            # We use the image processor for frame-by-frame video processing instead.
            if model_type == 'video':
                logger.warning("[SAM3] Video predictor not available on Windows (requires triton)")
                logger.warning("[SAM3] Using image processor for frame-by-frame video processing")
                print("[SAM3] Video predictor not available, using image processor for videos")
                # Ensure image model is loaded for video processing
                if self.image_model is None:
                    self.load_model('image')

            self._model_loaded = True
            return True

        except ImportError as e:
            error_msg = f"SAM3 not installed. Install with: pip install sam3\nError: {e}"
            logger.error(error_msg)
            raise ImportError(error_msg)
        except Exception as e:
            error_msg = f"Failed to load SAM3 model. Check HuggingFace authentication.\nError: {e}"
            logger.error(error_msg)
            raise RuntimeError(error_msg)

    def _ensure_image_model(self):
        """Load image model if not already loaded."""
        if self.image_model is None or self.image_processor is None:
            self.load_model('image')

    def _ensure_video_model(self):
        """Load model for video processing.
        Since video predictor requires triton (not available on Windows),
        we use the image model for frame-by-frame processing.
        """
        if self.image_model is None or self.image_processor is None:
            self.load_model('image')

    def concepts(self):
        """Le prompt découpé en CONCEPTS — SAM3 n'en segmente qu'un par appel.

        ⚠⚠ MESURÉ le 2026-09-23 sur une photo réelle, même image, même modèle chargé une
        fois, seul le prompt changeant :

            'face'                                        → 3 masques (0.93, 0.89, 0.88)
            'faces'                                       → 3 masques
            'human face'                                  → 3 masques
            'all human faces'                             → 0 masque   ← le quantificateur
            'face and person'                             → 1 masque (0.60, dégradé)
            'faces and license plates'                    → 0 masque   ← la conjonction
            'all human faces and vehicle license plates'  → 0 masque
            'Detect faces and license plates.'            → 0 masque   ← ce qui était envoyé

        SAM3 ancre UN groupe nominal simple. Une conjonction, un quantificateur (« all ») ou
        un verbe (« detect », « blur ») le font échouer SILENCIEUSEMENT : 0 masque, aucune
        erreur, une image de sortie identique à l'entrée. C'est ce qui a rendu l'anonymisation
        du 23/09 vide sans que rien ne le signale.

        Le contrat est donc : **une LISTE de concepts**, séparés par des virgules (ou par
        « and », toléré parce que c'est ce que les modèles écrivent spontanément), chacun
        segmenté à part et les masques réunis. C'est déjà la forme du cam_analyzer, dont les
        prompts SAM3 sont une liste itérée un par un.
        """
        parts = re.split(r'\s*[,;\n]\s*|\s+and\s+|\s+et\s+', self.text_prompt or '')
        return [p.strip().strip('.') for p in parts if p and p.strip().strip('.')]

    def _segment(self, pil_image):
        """Masques de TOUS les concepts du prompt sur une image — un appel SAM3 par concept.
        Rend `(masques, scores, concepts)` : le concept est le libellé de la détection."""
        masks, scores, labels = [], [], []
        for concept in self.concepts():
            state = self.image_processor.set_image(pil_image)
            output = self.image_processor.set_text_prompt(state=state, prompt=concept)
            found = output.get("masks", [])
            raw_scores = output.get("scores")
            values = list(raw_scores) if raw_scores is not None else []
            for i, mask in enumerate(found):
                masks.append(mask)
                scores.append(values[i] if i < len(values) else 1.0)
                labels.append(concept)
        return masks, scores, labels

    def detect(self, **kwargs) -> dict:
        """Le process « DÉTECTION » par SAM3 (2026-10-04) : les contours de ce que le prompt
        nomme, frame par frame, en document `detections` (`common/utils/detections`) — que le
        process « Floutage » relit. Rien n'est flouté, rien n'est écrit ici.

        SAM3 segmente image par image (le prédicteur vidéo exige triton) : les détections n'ont
        donc pas de PISTE, et le floutage ne les interpole pas.

        kwargs : `media_path`, `sam3_prompt`, `on_frame(i, image, détections)`,
        `progress(faites, total)` ; `progress_callback(pourcentage)` (console) reste lu.
        """
        from wama.common.utils import detections as dets
        self.text_prompt = kwargs.get('sam3_prompt', self.text_prompt)
        if not self.text_prompt or not self.text_prompt.strip():
            raise ValueError("SAM3 requires a text prompt. Please provide 'sam3_prompt' parameter.")
        self.input_path = kwargs.get('media_path', self.input_path)
        if not self.input_path or not os.path.exists(self.input_path):
            raise FileNotFoundError(f"Input file not found: {self.input_path}")
        on_frame, progress = kwargs.get('on_frame'), kwargs.get('progress')
        console_progress = kwargs.get('progress_callback')
        self._ensure_image_model()
        concepts = self.concepts()
        logger.info(f"[SAM3] Detecting with concept(s): {concepts}")

        def _frame(index, bgr):
            """Les détections d'UNE frame (BGR OpenCV) au format du document."""
            masks, scores, labels = self._segment(Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)))
            found = []
            for i, mask in enumerate(masks):
                score = float(scores[i]) if i < len(scores) else 1.0
                if score < self.confidence_threshold:
                    continue
                polygons = dets.mask_to_polygons(self._convert_mask_to_numpy(mask, bgr.shape[:2]))
                if not polygons:
                    continue
                found.append(dets.detection(box=dets.box_of_polygons(polygons), label=labels[i],
                                            conf=score, polygons=polygons))
            return found

        try:
            if is_image(self.input_path):
                image = cv2.imread(self.input_path)
                if image is None:
                    raise RuntimeError(f"Could not load image: {self.input_path}")
                height, width = image.shape[:2]
                doc = dets.new_document(media='image', width=width, height=height, engine='sam3',
                                        models=['sam3'], prompt=self.text_prompt)
                found = _frame(0, image)
                dets.add(doc, 0, found)
                if on_frame:
                    on_frame(0, image, found)
                if progress:
                    progress(1, 1)
            else:
                capture = cv2.VideoCapture(self.input_path)
                if not capture.isOpened():
                    raise RuntimeError(f"Could not open video: {self.input_path}")
                total = int(capture.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
                doc = dets.new_document(
                    media='video', width=int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)),
                    height=int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)),
                    fps=capture.get(cv2.CAP_PROP_FPS) or 25.0, frame_count=total,
                    engine='sam3', models=['sam3'], prompt=self.text_prompt)
                index = 0
                try:
                    while True:
                        ok, frame = capture.read()
                        if not ok:
                            break
                        try:
                            found = _frame(index, frame)
                        except Exception as frame_error:
                            # Une frame ratée n'arrête pas le média : elle reste sans détection,
                            # et la console le dit (comme le floutage d'avant l'écrivait telle quelle).
                            logger.warning(f"[SAM3] Frame {index} error: {frame_error}")
                            found = []
                        dets.add(doc, index, found)
                        if on_frame:
                            on_frame(index, frame, found)
                        index += 1
                        if progress:
                            progress(index, total or index)
                        if console_progress and total:
                            console_progress(int(index / total * 100))
                        if index % 100 == 0:
                            gc.collect()
                            if torch.cuda.is_available():
                                torch.cuda.empty_cache()
                finally:
                    capture.release()
            doc['tag'] = 'sam3'
            if not doc['frames']:
                # Un prompt que SAM3 n'ancre pas rend 0 masque SANS erreur : le dire, sinon
                # l'échec est invisible (le floutage rendrait le média tel quel).
                logger.warning(f"[SAM3] AUCUN masque — rien ne sera flouté. Concepts: {concepts}")
            return doc
        finally:
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

    def _convert_mask_to_numpy(self, mask, target_shape):
        """
        Convert a SAM3 mask to numpy array suitable for blurring.

        Args:
            mask: SAM3 output mask (torch tensor or numpy array)
            target_shape: Target (height, width) tuple

        Returns:
            numpy array with shape matching target, values 0-255
        """
        # Convert tensor to numpy
        if torch.is_tensor(mask):
            mask = mask.cpu().numpy()

        # Ensure mask is 2D
        if mask.ndim == 3:
            mask = mask.squeeze()
        if mask.ndim == 4:
            mask = mask.squeeze(0).squeeze(0)

        # Convert to uint8 (0-255 range)
        if mask.max() <= 1.0:
            mask = (mask * 255).astype(np.uint8)
        else:
            mask = mask.astype(np.uint8)

        # Resize to target shape if needed
        if mask.shape[:2] != target_shape:
            mask = cv2.resize(mask, (target_shape[1], target_shape[0]),
                            interpolation=cv2.INTER_LINEAR)

        return mask

    def cleanup(self):
        """Release all resources and models."""
        logger.info("[SAM3] Cleaning up resources...")

        # Modèles + VRAM : passe par unload() (contrat commun) pour que la réservation
        # au gouverneur soit LIBÉRÉE, et pas seulement les références Python.
        self.unload()

        logger.info("[SAM3] Cleanup complete")
