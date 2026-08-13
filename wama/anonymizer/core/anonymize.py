import os
import gc
import cv2
import torch
import numpy as np

from tqdm import tqdm
from pathlib import Path

from .blur_utils import blur_detection, blur_segmentation, normalize_blur_ratio
from .ffmpeg_utils import copy_audio_to_video
from ultralytics import YOLO, settings
from ultralytics.utils import MACOS, WINDOWS

from wama.anonymizer.backends import DetectionBackend
from wama.common.utils.video_utils import is_image
from wama.settings import MEDIA_INPUT_ROOT, MEDIA_OUTPUT_ROOT


class Anonymize(DetectionBackend):
    def __init__(self, source_dir=None, destination_dir=None):
        self.device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        print(f"Using device: {self.device}")

        # Path settings - use custom paths or fall back to Django settings
        self.source = str(source_dir) if source_dir else str(MEDIA_INPUT_ROOT)
        self.destination = str(destination_dir) if destination_dir else str(MEDIA_OUTPUT_ROOT)
        os.makedirs(self.source, exist_ok=True), os.makedirs(self.destination, exist_ok=True)
        self.input_path, self.output_path = None, None
        self.save_path, self.models_dir = './runs', './models'
        settings.update({'runs_dir': self.save_path, 'weights_dir': self.models_dir})

        # Model settings
        self.class_list = []
        self.classes2blur = ['face', 'plate']  # ['person', 'car', 'truck', 'bus']
        self.model_name = None
        self.model_path = None
        self.model = None
        self.device = None
        self.tracker = None
        self.usage = (('predict', 'track'), ('detect', 'segment'))
        self.mode = self.usage[0][1]
        self.task = self.usage[1][0]
        self.meta_data = None
        self.ret_mask = False
        self.vid_writer = None
        self.results = None
        self.plotted_img = None

        # ── MULTI-MODÈLES (2026-08-13) ────────────────────────────────────────────────────
        # `self.models` : un descripteur par modèle chargé — {'yolo', 'path', 'name',
        # 'classes' (celles qu'il doit couvrir), 'seg' (segmentation ?), 'indices'}.
        # `self.model` reste le PREMIER : tout le code historique (is_loaded, suffixe de
        # sortie, gardes) continue de fonctionner sans le savoir.
        #
        # POURQUOI ICI ET PAS DANS UN SECOND PIPELINE. Le chemin multi-modèles vivait dans
        # `detection_only.py` + `merged_blur.py` + un transport Redis : une réimplémentation
        # qui avait PERDU l'interpolation, le format de sortie, le statut RUNNING, l'ETA et
        # l'annulation, et qui décodait la vidéo N+1 fois. Tout cela existe déjà, correct,
        # dans cette classe. Lui apprendre N modèles coûte moins que maintenir deux chaînes,
        # et récupère ces cinq fonctions d'un coup.
        self.models = []
        self._resultats_par_modele = []

        # Option settings
        self.blur_ratio = 25
        self.rounded_edges = 5
        self.progressive_blur = 15
        self.ROI_enlargement = 1.05
        self.conf = 0.25
        self.blur = True
        self.show = True
        self.line_width = None
        self.boxes = True
        self.show_labels = True
        self.show_conf = True
        self.save = False
        self.save_txt = False

        # Interpolation settings
        self.interpolate_detections = True
        self.max_interpolation_frames = 15  # Will be capped at 0.5s based on FPS
        self.detection_buffer = {}  # {track_id: [(frame_idx, bbox, label), ...]}

    # ── Contrat commun (BaseModelBackend) ────────────────────────────────────
    # Dépendances et empreinte VRAM déclaratives : c'est ce que le gouverneur réserve si la
    # mesure autour du chargement n'est pas concluante. YOLOv8n ≈ 0,5 Go, yolov8m ≈ 2 Go.
    REQUIRED_PACKAGES = ['ultralytics']
    recommended_vram_gb = 2

    @property
    def is_loaded(self) -> bool:
        return self.model is not None

    def unload(self) -> None:
        """Libère LES modèles YOLO (et la réservation VRAM, via l'enveloppe du contrat commun)."""
        if self.model is None and not self.models:
            return
        self.model = None
        # En multi-modèles, oublier `self.model` seul laisserait les autres poids en VRAM :
        # c'est la fuite que le gouverneur de ressources ne saurait pas reprendre.
        self.models = []
        self._resultats_par_modele = []
        try:
            import gc
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass

    # `load_model(**kwargs)` (nom historique, hérité de DetectionBackend) délègue ICI : c'est
    # ce qui fait passer tous les appelants par la déclaration d'empreinte.
    def load(self, **kwargs) -> bool:
        """
        Charge UN modèle (`model_path=`) ou PLUSIEURS (`models=[{'path','classes'}, …]`).

        `models` prime quand il est fourni. Chaque descripteur porte les classes que CE modèle
        doit couvrir : c'est la couverture (`couvrir_classes`) qui les a réparties, la classe ne
        redécide rien. Le premier modèle devient `self.model` — le reste du code historique le
        voit comme avant.
        """
        descripteurs = kwargs.get('models') or []
        if not descripteurs:
            self.model_name = 'yolov8n-seg.pt' if self.task == 'segment' else "yolov8n.pt"
            if any([classe in self.classes2blur for classe in ['face', 'plate']]):
                self.model_name = "yolov8m_faces&plates_720p.pt"
            chemin = kwargs.get('model_path', os.path.join(self.models_dir, self.model_name))
            descripteurs = [{'path': chemin, 'classes': None}]
            if 'model_path' not in kwargs:
                # Chemin par défaut : on conserve le `model_name` calculé ci-dessus.
                descripteurs[0]['name'] = self.model_name

        self.models = []
        for d in descripteurs:
            chemin = d.get('path') or d.get('model_path')
            if not chemin:
                continue
            print(f'Model used: {chemin}')
            y = YOLO(chemin)
            classes_modele = list(y.model.names.values()) if hasattr(y.model, 'names') \
                else list((getattr(y, 'names', {}) or {}).values())
            self.models.append({
                'yolo': y,
                'path': chemin,
                'name': d.get('name') or os.path.basename(chemin),
                # Classes que ce modèle doit couvrir. None = « toutes celles qu'il connaît »,
                # comportement historique du mono-modèle.
                'classes': [c.lower() for c in (d.get('classes') or [])] or None,
                'seg': self._est_segmentation(chemin, y),
                'class_list': classes_modele,
            })

        if not self.models:
            print('❌ Aucun modèle chargeable')
            return False

        premier = self.models[0]
        self.model = premier['yolo']
        self.model_path = premier['path']
        self.model_name = premier['name']
        self.class_list = premier['class_list']

        # ── EMPREINTE VRAM DÉCLARÉE AU GOUVERNEUR (multi-modèles) ────────────────────────
        # `_wrap_load` (common/backends/base.py) MESURE la VRAM prise autour de ce `load()` et
        # ne retombe sur `recommended_vram_gb` que si la mesure est nulle. Or `YOLO(chemin)` ne
        # place RIEN sur le GPU — le device n'arrive qu'au `track()`/`predict()`. La mesure vaut
        # donc ~0 et c'est bien la valeur déclarée qui est réservée. Sans mise à l'échelle, on
        # annoncerait 1 modèle alors qu'on en charge N, et le gouverneur laisserait un autre
        # process prendre la place manquante.
        # Attribut d'INSTANCE, pas une `property` : `backends/manager.py:68` lit
        # `recommended_vram_gb` sur la CLASSE, où une property rendrait l'objet property.
        base_gb = type(self).recommended_vram_gb or 0
        if base_gb:
            self.recommended_vram_gb = base_gb * len(self.models)

        # `task`/`ret_mask` sont GLOBAUX à l'appel ultralytics : dès qu'UN modèle segmente, on
        # demande les masques. Chaque modèle reste interrogé selon SON propre drapeau `seg`
        # au moment de lire les résultats — un détecteur ne rendra simplement pas de masques.
        self._is_segmentation_model = premier['seg']
        if any(m['seg'] for m in self.models):
            self.task = 'segment'
            self.ret_mask = True
            print(f'[Segmentation] {sum(1 for m in self.models if m["seg"])} modèle(s) de '
                  f'segmentation → task={self.task}')
        return True

    def _reessayer(self, operation, replier_sur_cpu=None):
        """Exécute `operation` avec récupération VRAM (brique `MemoryManager`), ou tel quel si
        le model_manager est indisponible — une dépendance de confort ne doit pas empêcher de
        flouter."""
        try:
            from wama.model_manager.services.memory_manager import MemoryManager
        except Exception:
            return operation()
        return MemoryManager.reessayer_apres_liberation(
            operation, proprietaire='anonymizer', replier_sur_cpu=replier_sur_cpu)

    @staticmethod
    def _indices_classes(class_list, voulues) -> list:
        """
        Index des classes du modèle correspondant à `voulues`, **alias compris**.

        Indispensable : `couvrir_classes` rend les classes dans le vocabulaire de l'APPELANT
        (`plate`), et le modèle peut les nommer autrement (`license_plate`). Comparer les
        libellés bruts ferait rendre une liste vide, et le modèle serait écarté sans un mot.
        """
        from wama.common.services.model_coverage import (
            formes_equivalentes, normaliser_classe,
        )
        acceptees = set()
        for v in (voulues or []):
            acceptees |= formes_equivalentes(v)
        return [i for i, nom in enumerate(class_list)
                if normaliser_classe(nom) in acceptees]

    def _est_segmentation(self, chemin: str, y) -> bool:
        """Ce modèle-ci segmente-t-il ? (variante par modèle de `_detect_segmentation_model`)."""
        bas = (chemin or '').lower()
        if 'seg' in bas or '/segment/' in bas or '\\segment\\' in bas:
            return True
        try:
            return getattr(y, 'task', None) == 'segment'
        except Exception:
            return False

    def _detect_segmentation_model(self):
        """
        Detect if the loaded model is a segmentation model.

        Returns:
            bool: True if model supports segmentation, False otherwise
        """
        if not self.model:
            return False

        # Check if model path contains 'seg' or is in segment directory
        if 'seg' in self.model_path.lower() or '/segment/' in self.model_path or '\\segment\\' in self.model_path:
            return True

        # Check model task
        try:
            if hasattr(self.model, 'task') and self.model.task == 'segment':
                return True
        except:
            pass

        return False

    def _get_model_suffix(self):
        """
        Get a short model identifier for output filename.

        Returns:
            str: Model suffix (e.g., 'yolov8m', 'yolov8n-seg')
        """
        # Multi-modèles : le nom d'UN modèle mentirait sur le contenu du fichier produit.
        # Même suffixe que l'ancien chemin (`_blurred_multi-model`) pour que les sorties déjà
        # sur disque restent reconnues par `_resolve_output_rel` et la vue de téléchargement.
        if len(self.models) > 1:
            return 'multi-model'
        if not self.model_name:
            return 'yolo'

        # Extract model name without extension
        name = os.path.splitext(self.model_name)[0]

        # Simplify common patterns
        if 'faces&plates' in name.lower():
            # e.g., "yolov8m_faces&plates_720p" -> "yolov8m-fp"
            if 'yolov8m' in name.lower():
                return 'yolov8m-fp'
            elif 'yolov8l' in name.lower():
                return 'yolov8l-fp'
            elif 'yolov8x' in name.lower():
                return 'yolov8x-fp'
            return 'yolo-fp'

        # For standard YOLO models, keep it simple
        # e.g., "yolov8n-seg" -> "yolov8n-seg", "yolov8m" -> "yolov8m"
        return name.lower()

    def process(self, **kwargs):
        if not self.model:
            print('❌ No model is loaded')
            return

        self.input_path = kwargs.get('media_path', self.input_path or self.source)

        # Get model suffix for output filename
        model_suffix = self._get_model_suffix()

        # Folder
        if os.path.isdir(self.input_path):
            for media in os.listdir(self.input_path):
                media_path = os.path.join(self.input_path, media)
                self.input_path = media_path
                name, ext = os.path.splitext(media)
                self.output_path = os.path.join(
                    self.destination, f"{name}_blurred_{model_suffix}{ext}"
                )

                if is_image(media_path):
                    self.process_image(media_path, self.output_path, **kwargs)
                else:
                    self.setup_source(**kwargs)
                    self.apply_process(**kwargs)
        # TODO: File list
        # File
        else:
            name, ext = os.path.splitext(os.path.basename(self.input_path))
            self.output_path = os.path.join(self.destination, f"{name}_blurred_{model_suffix}{ext}")

            if is_image(self.input_path):
                self.process_image(self.input_path, self.output_path, **kwargs)
            else:
                self.setup_source(**kwargs)
                self.apply_process(**kwargs)


    def process_image(self, input_path, output_path, **kwargs):
        img = cv2.imread(input_path)
        if img is None:
            print(f"❌ Could not load image: {input_path}")
            return

        self.classes2blur = kwargs.get('classes2blur', self.classes2blur)
        classes2blur_lower = [c.lower() for c in self.classes2blur]

        # UNE prédiction par modèle sur LA MÊME image — même principe que la vidéo. Sans cette
        # boucle, une image traitée en multi-modèles n'aurait été vue que par le premier modèle
        # (les plaques floutées, les visages non, ou l'inverse).
        self._resultats_par_modele = []
        for entree in self.models:
            voulues = entree['classes'] or classes2blur_lower
            indices = self._indices_classes(entree['class_list'], voulues)
            if not indices:
                print(f"[Detection] {entree['name']} : aucune classe demandée en commun "
                      f"({voulues}) — modèle ignoré pour cette image")
                self._resultats_par_modele.append([])
                continue
            entree['indices'] = indices

            def _predire(dev, _e=entree, _idx=indices):
                return _e['yolo'].predict(
                    source=img, task=self.task, device=dev, retina_masks=self.ret_mask,
                    imgsz=max(img.shape[:2]), conf=kwargs.get('detection_threshold', self.conf),
                    classes=_idx, verbose=False,
                )

            # Ici le repli CPU EST légitime : une image, c'est quelques secondes. Sur la vidéo
            # (apply_process) il est volontairement absent — il durerait des heures.
            self._resultats_par_modele.append(self._reessayer(
                lambda: _predire(self.device),
                replier_sur_cpu=lambda: _predire('cpu'),
            ))

        if any(self._resultats_par_modele):
            self.results = next(r for r in self._resultats_par_modele if r)
            self.plotted_img = self.results[0].plot(boxes=False, conf=False, labels=False)
            self.blur_results(**kwargs)
        else:
            print("No detections found.")
            cv2.imwrite(output_path, img)


    def setup_source(self, **kwargs):
        print(f'Setting up media: {self.input_path}')
        cap = cv2.VideoCapture(self.input_path)
        fps = cap.get(cv2.CAP_PROP_FPS)
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        cap.release()

        # Use a lossless/high-quality intermediate codec to preserve quality
        # We'll re-encode with FFmpeg later to match input codec
        suffix = '.avi'
        # Use FFV1 (lossless) or MJPEG (high quality) for intermediate file
        # FFV1 requires ffmpeg, so we use MJPEG which is widely supported
        fourcc = 'MJPG'  # Motion JPEG - high quality, widely supported

        save_path = str(Path(self.output_path).with_suffix(suffix))
        self.temp_video_path = save_path  # Store temp video path for later use
        self.meta_data = {'fps': fps, 'size': (width, height)}

        # Try to create video writer with high quality settings
        self.vid_writer = cv2.VideoWriter(
            save_path,
            cv2.VideoWriter_fourcc(*fourcc),
            fps,
            (width, height),
            True  # isColor
        )

        if not self.vid_writer.isOpened():
            # Fallback to mp4v if MJPEG fails
            print("Warning: MJPEG codec not available, using mp4v")
            suffix = '.mp4'
            fourcc = 'mp4v'
            save_path = str(Path(self.output_path).with_suffix(suffix))
            self.temp_video_path = save_path  # Update temp path
            self.vid_writer = cv2.VideoWriter(save_path, cv2.VideoWriter_fourcc(*fourcc), fps, (width, height))

    def apply_process(self, **kwargs):
        self.classes2blur = kwargs.get('classes2blur', self.classes2blur)

        # Normalize classes to lowercase for case-insensitive matching
        classes2blur_lower = [c.lower() for c in self.classes2blur]
        classes2blur_by_index = [i for i, name in enumerate(self.class_list) if name.lower() in classes2blur_lower]

        # Debug: Show which classes will be detected
        matched_classes = [name for name in self.class_list if name.lower() in classes2blur_lower]
        unmatched_classes = [c for c in self.classes2blur if c.lower() not in [n.lower() for n in self.class_list]]

        print(f'[Detection] Classes requested: {self.classes2blur}')
        print(f'[Detection] Classes found in model: {matched_classes}')
        if unmatched_classes:
            print(f'[Detection] WARNING: Classes not in model (will be ignored): {unmatched_classes}')
            print(f'[Detection] Available model classes: {self.class_list[:20]}...')  # Show first 20

        if not classes2blur_by_index:
            print(f'[Detection] ERROR: No matching classes found! Blurring will not work.')

        source = kwargs.get('media_path', self.input_path)
        imgsz = self.meta_data['size'][0] if 'size' in self.meta_data else self.meta_data['shape'][0]

        # UNE PASSE PAR MODÈLE sur la MÊME source. Chaque passe garde ses frames en mémoire
        # (ultralytics `track` sans `stream`), donc le floutage qui suit ne redécode rien : on
        # reste à N décodages pour N modèles, contre N+1 dans la chaîne Celery qu'on remplace
        # — et surtout sans aucun transport des masques par Redis.
        self._resultats_par_modele = []
        for entree in self.models:
            # Chaque modèle ne détecte QUE les classes qui lui ont été confiées, et selon SON
            # propre vocabulaire : les index de classe diffèrent d'un jeu de poids à l'autre.
            voulues = entree['classes'] or classes2blur_lower
            indices = self._indices_classes(entree['class_list'], voulues)
            if not indices:
                print(f"[Detection] {entree['name']} : aucune classe demandée en commun "
                      f"({voulues}) — modèle ignoré pour ce média")
                self._resultats_par_modele.append([])
                continue
            entree['indices'] = indices
            # Seul le PREMIER modèle hérite des options d'affichage/sauvegarde : les rejouer
            # pour chaque modèle ouvrirait N fenêtres et écrirait N fois les mêmes artefacts.
            premier = entree is self.models[0]

            def _suivre(_e=entree, _p=premier, _idx=indices):
                return _e['yolo'].track(
                    source=source, task=self.task, mode=self.mode, device=self.device,
                    retina_masks=self.ret_mask, imgsz=imgsz,
                    classes=_idx, conf=kwargs.get('detection_threshold', self.conf),
                    save=self.save if _p else False,
                    save_txt=self.save_txt if _p else False,
                    show=kwargs.get('show_preview', self.show) if _p else False,
                    boxes=kwargs.get('show_boxes', self.boxes) if _p else False,
                    show_labels=kwargs.get('show_labels', self.show_labels) if _p else False,
                    show_conf=kwargs.get('show_conf', self.show_conf) if _p else False,
                )

            # Erreur CUDA → libérer la VRAM des AUTRES modèles du process, puis réessayer.
            # PAS de repli CPU ici : sur une vidéo il durerait des heures et donnerait
            # l'illusion d'un blocage. Un échec net remonte en FAILURE avec son message.
            self._resultats_par_modele.append(
                self._reessayer(_suivre, replier_sur_cpu=None))

        # Compat : tout le code historique lit `self.results` (frames du 1er modèle).
        self.results = next((r for r in self._resultats_par_modele if r), [])
        # Blur detections
        if self.classes2blur:
            self.blur_results(**kwargs)
            if self.vid_writer:
                self.vid_writer.release()
                # Use the temp video path (e.g., .avi) that was actually created
                self.copy_audio(self.temp_video_path)
            print(f'✅ Process complete for media: {self.input_path}')
        # if cv2.waitKey(1) & 0xFF == ord('q'):
        #     break
        # cv2.waitKey(0)
        # print(results[0].boxes.data)

    def validate_bbox(self, bbox, img_shape):
        """
        Validate and clamp bounding box to image boundaries.

        Args:
            bbox: Bounding box [x1, y1, x2, y2]
            img_shape: Image shape (height, width, channels)

        Returns:
            Valid bbox [x1, y1, x2, y2] or None if invalid
        """
        if bbox is None or len(bbox) < 4:
            return None

        height, width = img_shape[:2]

        # Clamp coordinates to image boundaries
        x1 = max(0, min(bbox[0], width))
        y1 = max(0, min(bbox[1], height))
        x2 = max(0, min(bbox[2], width))
        y2 = max(0, min(bbox[3], height))

        # Ensure x2 > x1 and y2 > y1 (positive dimensions)
        if x2 <= x1 or y2 <= y1:
            return None

        # Ensure minimum size (at least 5x5 pixels)
        if (x2 - x1) < 5 or (y2 - y1) < 5:
            return None

        return [x1, y1, x2, y2]

    def interpolate_bbox(self, bbox1, bbox2, ratio):
        """
        Linear interpolation between two bounding boxes.

        Args:
            bbox1: First bbox [x1, y1, x2, y2]
            bbox2: Second bbox [x1, y1, x2, y2]
            ratio: Interpolation ratio (0 = bbox1, 1 = bbox2)

        Returns:
            Interpolated bbox [x1, y1, x2, y2]
        """
        return [
            bbox1[0] + (bbox2[0] - bbox1[0]) * ratio,
            bbox1[1] + (bbox2[1] - bbox1[1]) * ratio,
            bbox1[2] + (bbox2[2] - bbox1[2]) * ratio,
            bbox1[3] + (bbox2[3] - bbox1[3]) * ratio,
        ]

    def get_interpolated_detections(self, frame_idx, track_id):
        """
        Get interpolated or extrapolated detection for a missing frame.

        Args:
            frame_idx: Current frame index
            track_id: ID of the tracked object

        Returns:
            (bbox, label) if interpolation is possible, None otherwise
        """
        if track_id not in self.detection_buffer:
            return None

        detections = self.detection_buffer[track_id]
        if len(detections) < 2:
            return None

        # Find the two nearest detections (before and after current frame)
        before = None
        after = None

        for det_frame, bbox, label in detections:
            if det_frame < frame_idx:
                if before is None or det_frame > before[0]:
                    before = (det_frame, bbox, label)
            elif det_frame > frame_idx:
                if after is None or det_frame < after[0]:
                    after = (det_frame, bbox, label)

        # Interpolation: we have detections before AND after
        if before and after:
            before_frame, before_bbox, before_label = before
            after_frame, after_bbox, after_label = after

            # Check if gap is not too large
            gap = after_frame - before_frame
            if gap > self.max_interpolation_frames * 2:
                return None

            # Linear interpolation
            ratio = (frame_idx - before_frame) / gap
            interpolated_bbox = self.interpolate_bbox(before_bbox, after_bbox, ratio)
            return (interpolated_bbox, before_label)

        # Extrapolation: we only have detections before (forward extrapolation)
        elif before and not after:
            before_frame, before_bbox, before_label = before
            gap = frame_idx - before_frame

            # Only extrapolate for a limited number of frames
            if gap > self.max_interpolation_frames:
                return None

            # If we have at least 2 previous detections, use velocity estimation
            if len(detections) >= 2:
                # Get the two most recent detections
                sorted_dets = sorted(detections, key=lambda x: x[0], reverse=True)
                latest = sorted_dets[0]
                previous = sorted_dets[1]

                latest_frame, latest_bbox, _ = latest
                prev_frame, prev_bbox, _ = previous

                # Estimate velocity
                frame_diff = latest_frame - prev_frame
                if frame_diff > 0 and frame_diff <= self.max_interpolation_frames:
                    velocity = [
                        (latest_bbox[i] - prev_bbox[i]) / frame_diff
                        for i in range(4)
                    ]

                    # Extrapolate using constant velocity
                    extrapolated_bbox = [
                        before_bbox[i] + velocity[i] * gap
                        for i in range(4)
                    ]
                    return (extrapolated_bbox, before_label)

            # Fallback: use last known position
            return (before_bbox, before_label)

        return None

    def _par_frame(self):
        """
        Itère les frames en donnant, pour chacune, le résultat de CHAQUE modèle.

        Rend `(frame_idx, resultat_principal, [(rang, entree_modele, resultat), …])`.
        `resultat_principal` porte l'image (tous les modèles ont vu la même frame).

        `zip` s'arrête au plus court : si deux passes rendaient un nombre de frames différent
        (source illisible en cours de route), on floute ce qu'on peut plutôt que d'exploser.
        """
        listes = [r for r in (self._resultats_par_modele or []) if r]
        if not listes:
            listes = [self.results or []]
        entrees = [e for e, r in zip(self.models, self._resultats_par_modele or []) if r] \
            or self.models or [{'name': 'modele', 'seg': self._is_segmentation_model,
                                'classes': None}]
        for idx, groupe in enumerate(zip(*listes)):
            yield idx, groupe[0], [(rang, entrees[rang], res) for rang, res in enumerate(groupe)]

    def _detections_retenues(self, entree, result, classes2blur, detection_threshold):
        """Détections de CE modèle sur CETTE frame qui doivent être floutées.

        Rend `(indice, boite, label, masque_ou_None)`. Le masque n'est lu que si le modèle
        segmente : un détecteur n'en produit pas, et `result.masks` y vaut None."""
        if not result.boxes:
            return
        from wama.common.services.model_coverage import (
            formes_equivalentes, normaliser_classe,
        )
        voulues = entree.get('classes') or classes2blur
        # Mêmes alias qu'à la sélection des index : le modèle rend `License_Plate` là où la
        # demande dit `plate`. Comparer les libellés bruts rejetterait toutes ses détections
        # APRÈS les avoir calculées — le pire des deux mondes.
        acceptees = set()
        for v in (voulues or []):
            acceptees |= formes_equivalentes(v)
        avec_masques = (entree.get('seg') and getattr(result, 'masks', None) is not None)
        for i, d in enumerate(result.boxes):
            label = result.names[int(d.cls)]
            if normaliser_classe(label) not in acceptees or float(d.conf) < detection_threshold:
                continue
            masque = None
            if avec_masques and i < len(result.masks.data):
                masque = (result.masks.data[i].cpu().numpy() * 255).astype(np.uint8)
            yield i, d, label, masque

    def collect_all_detections(self, classes2blur, detection_threshold, use_segmentation):
        """
        PASS 1: Collect all detections from all frames, TOUS MODÈLES CONFONDUS.

        Returns:
            dict: {track_id: [(frame_idx, bbox, label, mask), ...]}

        ⚠ Le `track_id` est PRÉFIXÉ DU RANG DU MODÈLE. Deux modèles numérotent leurs pistes
        indépendamment : sans préfixe, la piste 1 du détecteur de visages et la piste 1 du
        détecteur de plaques fusionneraient, et l'interpolation ferait glisser un floutage
        d'un visage vers une plaque à l'autre bout de l'image.
        """
        detection_buffer = {}
        print("[Interpolation] Pass 1/2: Collecting all detections...")

        for frame_idx, _principal, par_modele in self._par_frame():
            if not classes2blur:
                continue
            for rang, entree, result in par_modele:
                for i, d, label, masque in self._detections_retenues(
                        entree, result, classes2blur, detection_threshold):
                    brut = int(d.id) if getattr(d, 'id', None) is not None else f"det_{i}"
                    track_id = f"m{rang}:{brut}"
                    detection_buffer.setdefault(track_id, []).append(
                        (frame_idx, d.xyxy[0].cpu().numpy().tolist(), label, masque))

        return detection_buffer

    def fill_detection_gaps(self, detection_buffer, max_gap):
        """
        Identify gaps in detections and fill them with interpolated positions.
        Only interpolates BETWEEN two known detections, never extrapolates.

        Args:
            detection_buffer: {track_id: [(frame_idx, bbox, label, mask), ...]}
            max_gap: Maximum gap size to interpolate (in frames)

        Returns:
            dict: {frame_idx: {track_id: (bbox, label)}}
        """
        interpolated_detections = {}

        print(f"[Interpolation] Pass 2/2: Filling detection gaps (max gap: {max_gap} frames)...")

        for track_id, detections in detection_buffer.items():
            if len(detections) < 2:
                # Need at least 2 detections to interpolate
                continue

            # Sort by frame index
            detections.sort(key=lambda x: x[0])

            # Check for gaps between consecutive detections
            for i in range(len(detections) - 1):
                frame_start, bbox_start, label_start, _ = detections[i]
                frame_end, bbox_end, label_end, _ = detections[i + 1]

                gap = frame_end - frame_start - 1

                if gap > 0 and gap <= max_gap:
                    # Interpolate between these two detections
                    print(f"[Interpolation] Track {track_id}: filling {gap} frames between frame {frame_start} and {frame_end}")

                    for frame_idx in range(frame_start + 1, frame_end):
                        # Linear interpolation
                        ratio = (frame_idx - frame_start) / (frame_end - frame_start)
                        interpolated_bbox = self.interpolate_bbox(bbox_start, bbox_end, ratio)

                        # Store interpolated detection
                        if frame_idx not in interpolated_detections:
                            interpolated_detections[frame_idx] = {}
                        interpolated_detections[frame_idx][track_id] = (interpolated_bbox, label_start)

        return interpolated_detections

    def blur_results(self, **kwargs):

        # Settings
        plot_args = {'line_width': None, 'boxes': False, 'conf': False, 'labels': False}
        classes2blur = kwargs.get('classes2blur', self.classes2blur)
        # Normalize to lowercase for case-insensitive matching
        classes2blur_lower = [c.lower() for c in classes2blur]
        blur_ratio = normalize_blur_ratio(kwargs.get('blur_ratio', self.blur_ratio))
        rounded_edges = int(kwargs.get('rounded_edges', self.rounded_edges))  # Rounding corners
        progressive_blur = int(kwargs.get('progressive_blur', self.progressive_blur))  # Progressive contours
        roi_enlargement = kwargs.get('ROI_enlargement', self.ROI_enlargement)  # Enlarging the blurred area
        detection_threshold = kwargs.get('detection_threshold', self.conf)  # Object detection threshold
        interpolate_detections = kwargs.get('interpolate_detections', self.interpolate_detections)

        # Calculate max interpolation frames based on FPS (0.5 seconds max)
        fps = self.meta_data.get('fps', 30) if isinstance(self.meta_data, dict) else 30
        max_interpolation_time = 0.5  # seconds
        calculated_max_frames = int(fps * max_interpolation_time)

        # Use the smaller of: user setting or calculated limit (0.5s)
        user_max_frames = kwargs.get('max_interpolation_frames', self.max_interpolation_frames)
        max_gap = min(user_max_frames, calculated_max_frames)

        print(f"[Interpolation] FPS: {fps}, Max gap to fill: {max_gap} frames ({max_gap/fps:.2f}s)")

        # Check if we're using segmentation
        use_segmentation = self._is_segmentation_model if hasattr(self, '_is_segmentation_model') else False

        # TWO-PASS APPROACH for interpolation
        interpolated_detections = {}
        if interpolate_detections:
            # PASS 1: Collect all detections (use lowercase for matching)
            detection_buffer = self.collect_all_detections(classes2blur_lower, detection_threshold, use_segmentation)

            # PASS 2: Fill gaps with interpolation
            interpolated_detections = self.fill_detection_gaps(detection_buffer, max_gap)

            print(f"[Interpolation] Generated {sum(len(v) for v in interpolated_detections.values())} interpolated detections across {len(interpolated_detections)} frames")

        # MAIN BLURRING LOOP — UNE passe, TOUS les modèles réunis par frame.
        # L'union des zones se fait ici, en mémoire, sur la frame courante : c'est ce qui
        # remplace la fusion via Redis de l'ancien chemin multi-modèles.
        for frame_idx, principal, par_modele in tqdm(
                self._par_frame(), desc='Blurring media', unit='frames', dynamic_ncols=True):
            # On part TOUJOURS de l'image d'origine. `plot()` était utilisé pour les modèles de
            # détection, mais `plot_args` désactive boîtes, libellés et confiance : il rendait
            # donc déjà l'image nue. En multi-modèles il aurait en plus dessiné les masques
            # colorés du premier modèle segmentant par-dessus la vidéo finale.
            im0 = principal.orig_img.copy()

            if classes2blur:
                for _rang, entree, result in par_modele:
                    for _i, d, label, masque in self._detections_retenues(
                            entree, result, classes2blur_lower, detection_threshold):
                        if masque is not None:
                            im0 = blur_segmentation(im0, masque, blur_ratio, progressive_blur)
                        else:
                            im0 = blur_detection(
                                im0, d.xyxy[0], label, blur_ratio,
                                rounded_edges, progressive_blur, roi_enlargement,
                            )

            # Apply ONLY pre-calculated interpolated detections for this frame
            if interpolate_detections and frame_idx in interpolated_detections:
                for track_id, (bbox, label) in interpolated_detections[frame_idx].items():
                    # Validate bbox before blurring
                    validated_bbox = self.validate_bbox(bbox, im0.shape)
                    if validated_bbox is None:
                        continue  # Skip invalid bbox

                    # Blur the interpolated detection
                    try:
                        im0 = blur_detection(
                            im0,
                            validated_bbox,
                            label,
                            blur_ratio,
                            rounded_edges,
                            progressive_blur,
                            roi_enlargement
                        )
                    except Exception as e:
                        print(f"[Interpolation] Error blurring interpolated bbox at frame {frame_idx}: {e}")
                        continue

            self.plotted_img = im0
            self.write_media()

    def write_media(self):
        if not isinstance(self.meta_data, dict):
            self.meta_data = {}

        if 'fps' not in self.meta_data:
            self.meta_data['fps'] = 1
            # Save image with high quality
            # For JPEG: quality 95 (default is 95, max is 100)
            # For PNG: compression level 3 (default is 3, 0=no compression, 9=max compression)
            ext = os.path.splitext(self.output_path)[1].lower()
            if ext in ['.jpg', '.jpeg']:
                cv2.imwrite(self.output_path, self.plotted_img, [cv2.IMWRITE_JPEG_QUALITY, 95])
            elif ext == '.png':
                cv2.imwrite(self.output_path, self.plotted_img, [cv2.IMWRITE_PNG_COMPRESSION, 3])
            else:
                cv2.imwrite(self.output_path, self.plotted_img)
        else:
            self.vid_writer.write(self.plotted_img)

    def copy_audio(self, temp_video_path):
        """
        Copy audio from original video to processed video.
        Converts intermediate format (.avi) to final .mp4 format.
        """
        print(f"[copy_audio] Input video: {self.input_path}")
        print(f"[copy_audio] Temp video (intermediate): {temp_video_path}")
        print(f"[copy_audio] Temp video exists: {os.path.exists(temp_video_path)}")

        # Final output should always be .mp4
        final_output_path = os.path.splitext(self.output_path)[0] + '.mp4'
        print(f"[copy_audio] Final output path: {final_output_path}")

        copy_audio_to_video(self.input_path, temp_video_path, final_output_path)


def stop_process():
    print('Process stopped')
    exit()


if __name__ == '__main__':
    print('CUDA available:', torch.cuda.is_available())
    torch.cuda.empty_cache()
    gc.collect()
    model = Anonymize()
    model.load_model()
    model.process()
