"""
Contrat des détecteurs de l'Anonymizer — spécialisation métier de `BaseModelBackend`.

CONTEXTE (2026-07-29) — l'anonymizer n'avait AUCUN `backends/` : ses porteurs de modèle GPU
(`Anonymize` → YOLO, `SAM3Processor` → SAM3) avaient déjà la FORME du contrat (`load_model()`,
parfois `unload()`/`cleanup()`) sans en hériter. Résultat : aucune déclaration d'empreinte au
gouverneur de ressources, alors que l'anonymizer est l'app dont les tâches GPU sont les plus
lourdes.

⚠ MISE À JOUR 2026-08-13 — `Anonymize` peut désormais tenir **plusieurs** modèles à la fois
(multi-modèles : un détecteur de visages ET un de plaques). L'empreinte déclarée est **mise à
l'échelle du nombre de modèles** dans `Anonymize.load()` (attribut d'instance), parce que
`_wrap_load` mesure la VRAM autour du chargement et que `YOLO(chemin)` n'en prend AUCUNE — le
device n'arrive qu'au `track()`. Sans cette mise à l'échelle, une passe à N modèles annoncerait
l'empreinte d'un seul et le gouverneur laisserait un autre process prendre la place manquante.

Cette classe fait UNE chose : mapper le verbe historique `load_model()` sur le `load()` du
contrat commun, pour que l'empreinte soit déclarée **sans toucher un seul appelant**. C'est le
même motif que `ImageGenerationBackend` (imager) et `SpeechToTextBackend` (transcriber) — et
c'est ce motif, pas le rattachement des classes concrètes une par une, qui fait la couverture :
`__init_subclass__` enveloppe les `load`/`unload` définis à N'IMPORTE QUELLE profondeur.
"""

from wama.common.backends.base import BaseModelBackend


class DetectionBackend(BaseModelBackend):
    """Porteur d'un modèle de détection/segmentation (YOLO, SAM3) chargé sur GPU."""

    # Les dépendances et l'empreinte se déclarent dans les classes CONCRÈTES : YOLO
    # (ultralytics, ~2 Go) et SAM3 (~3 Go) n'ont ni les mêmes paquets ni le même poids.

    def load_model(self, *args, **kwargs):
        """
        Nom historique conservé pour tous les appelants (tasks, parallel_detection, core/*).

        ⚠️ NE PAS remplacer par un alias de classe (`load_model = load`) : l'alias capturerait la
        fonction AVANT que `__init_subclass__` n'enveloppe `load`, et les appelants passeraient
        donc à côté de la déclaration VRAM — le mécanisme serait présent et inopérant. C'est la
        délégation via `self.load(...)` qui garantit que TOUS les chemins traversent l'enveloppe.
        """
        return self.load(*args, **kwargs)

    @staticmethod
    def working_dirs(source_dir=None, destination_dir=None) -> tuple:
        """`(source, destination)` d'un détecteur, créés : ceux donnés, sinon les dossiers par
        défaut de l'anonymizer (`anonymizer/input` et `output` sous `MEDIA_ROOT`), lus dans les
        réglages AU MOMENT DE L'APPEL. Jusqu'au 2026-10-27 ils venaient de `MEDIA_INPUT_ROOT` /
        `MEDIA_OUTPUT_ROOT` importés de `wama.settings` — figés à l'import, donc hors de la
        redirection du lanceur de tests : un test qui construisait un détecteur sans dossier
        créait `media/anonymizer/` dans les VRAIS médias (relevé à l'audit des tests)."""
        import os
        from pathlib import Path
        from django.conf import settings
        default = Path(settings.MEDIA_ROOT) / 'anonymizer'
        source = str(source_dir) if source_dir else str(default / 'input')
        destination = str(destination_dir) if destination_dir else str(default / 'output')
        os.makedirs(source, exist_ok=True)
        os.makedirs(destination, exist_ok=True)
        return source, destination

    def process(self, **kwargs):
        """Le point d'entrée métier du contrat commun : pour un détecteur, la DÉTECTION — un
        document `detections` (`common/utils/detections.py`). Depuis le 2026-10-04 les deux
        moteurs ne floutent plus : le floutage se joue depuis le document, sans modèle."""
        return self.detect(**kwargs)

    def detect(self, **kwargs) -> dict:
        raise NotImplementedError


class FrameDetectionBackend(DetectionBackend):
    """Détecteur qui juge chaque IMAGE seule, sans suivi : SAM3, RT-DETR, EgoBlur… (2026-10-10).

    La boucle sur le média (image ou vidéo, aperçu, progression, une frame ratée qui n'arrête
    pas le média) vivait dans `SAM3Processor.detect` ; un second détecteur l'aurait recopiée.
    Elle est ICI, et un détecteur n'écrit plus que `detect_frames` — ses détections sur un LOT
    d'images (BGR OpenCV), au format du document (`common/utils/detections.detection`). Sans
    piste : l'interpolation relie les détections par leur position (`detections.by_frame`).

    Ce que la base fait des détections rendues : elle ne garde que les classes DEMANDÉES (alias
    compris, `model_coverage.formes_equivalentes`) au-dessus du seuil — un détecteur rend ce
    qu'il sait voir, la demande vient de la card. `classes` vide = tout ce qu'il rend (SAM3 :
    ses concepts sont déjà la demande).
    """

    #: Images passées ensemble à `detect_frames` — 1 par défaut ; un détecteur qui gagne à
    #: grouper (transformers, TorchScript) le déclare.
    BATCH_SIZE = 1
    #: Seuil propre au modèle quand la card n'en dit rien (`detection_threshold` absent).
    DEFAULT_THRESHOLD = 0.25

    def detect_frames(self, images, threshold: float) -> list:
        """Les détections de chaque image du lot : une liste par image, même ordre."""
        raise NotImplementedError

    def document_meta(self, **kwargs) -> dict:
        """`engine`, `models`, `prompt` du document — ce que le détecteur dit de lui-même."""
        return {'engine': getattr(self, 'name', '') or self.ENGINE,
                'models': [getattr(self, 'catalogue_key', '') or getattr(self, 'name', '')
                           or type(self).__name__]}

    def prepare(self, **kwargs) -> None:
        """Avant la boucle : lire les réglages de la card, charger le modèle (défaut : `load`)."""
        if not self.is_loaded:
            self.load()

    def threshold_for(self, **kwargs) -> float:
        """Le seuil de confiance appliqué : celui de la card, sinon celui du modèle."""
        requested = kwargs.get('detection_threshold')
        return self.DEFAULT_THRESHOLD if requested is None else float(requested)

    def requested_classes(self, **kwargs) -> list:
        """Les classes gardées (vide = tout ce que le détecteur rend) : celles de la card."""
        return list(kwargs.get('classes2blur') or [])

    def output_tag(self) -> str:
        """Le suffixe du fichier produit (`compose_output_name`)."""
        return getattr(self, 'name', '') or self.ENGINE

    def detect(self, **kwargs) -> dict:
        """Le process « Détection » d'un détecteur image par image : document `detections`.

        kwargs : `media_path`, `classes2blur`, `detection_threshold`, `on_frame(i, image,
        détections)`, `progress(faites, total)`, `progress_callback(pourcentage)` (console)."""
        import gc
        import logging
        import os

        import cv2

        from wama.common.services.model_coverage import formes_equivalentes, normaliser_classe
        from wama.common.utils import detections as dets
        from wama.common.utils.video_utils import is_image

        logger = logging.getLogger(__name__)
        self.prepare(**kwargs)   # d'abord : un réglage manquant se dit avant un fichier absent
        source = kwargs.get('media_path')
        if not source or not os.path.exists(source):
            raise FileNotFoundError(f"Input file not found: {source}")
        threshold = self.threshold_for(**kwargs)
        classes = self.requested_classes(**kwargs)
        accepted = set()
        for wanted in classes:
            accepted |= formes_equivalentes(wanted)
        on_frame, progress = kwargs.get('on_frame'), kwargs.get('progress')
        console_progress = kwargs.get('progress_callback')

        def _kept(found):
            return [d for d in found if d.get('conf', 1.0) >= threshold
                    and (not accepted or normaliser_classe(d.get('label')) in accepted)]

        def _batch(start, images):
            try:
                results = self.detect_frames(images, threshold)
            except Exception as error:
                # Une frame ratée n'arrête pas le média : elle reste sans détection, et le
                # journal le dit (règle reprise de SAM3).
                logger.warning(f"[{type(self).__name__}] frames {start}+{len(images)} : {error}")
                results = [[] for _ in images]
            return [_kept(found) for found in results]

        meta = self.document_meta(**kwargs)
        if is_image(source):
            image = cv2.imread(source)
            if image is None:
                raise RuntimeError(f"Could not load image: {source}")
            height, width = image.shape[:2]
            doc = dets.new_document(media='image', width=width, height=height,
                                    classes=classes, **meta)
            doc['tag'] = self.output_tag()
            found = _batch(0, [image])[0]
            dets.add(doc, 0, found)
            if on_frame:
                on_frame(0, image, found)
            if progress:
                progress(1, 1)
            return doc

        capture = cv2.VideoCapture(source)
        if not capture.isOpened():
            raise RuntimeError(f"Could not open video: {source}")
        total = int(capture.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
        doc = dets.new_document(
            media='video', width=int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)),
            height=int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)),
            fps=capture.get(cv2.CAP_PROP_FPS) or 25.0, frame_count=total,
            classes=classes, **meta)
        doc['tag'] = self.output_tag()
        index, last_pct = 0, -10
        try:
            while True:
                images = []
                while len(images) < max(1, self.BATCH_SIZE):
                    ok, frame = capture.read()
                    if not ok:
                        break
                    images.append(frame)
                if not images:
                    break
                for offset, found in enumerate(_batch(index, images)):
                    dets.add(doc, index + offset, found)
                    if on_frame:
                        on_frame(index + offset, images[offset], found)
                index += len(images)
                if progress:
                    progress(index, total or index)
                if console_progress and total:
                    pct = int(index / total * 100)
                    if pct - last_pct >= 10 or pct >= 100:
                        last_pct = pct
                        console_progress(pct)
                if index % 100 < len(images):
                    gc.collect()
                    self._empty_cuda_cache()
        finally:
            capture.release()
            gc.collect()
            self._empty_cuda_cache()
        return doc

    @staticmethod
    def _empty_cuda_cache():
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass
