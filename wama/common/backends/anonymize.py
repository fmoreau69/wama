import os
import gc
import cv2
import torch
import numpy as np

from pathlib import Path

from ultralytics import YOLO, settings
from ultralytics.utils import MACOS, WINDOWS

from .detection_base import DetectionBackend
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
    #: Moteur piloté (contrat commun). ⚠ Déclaré le 2026-09-06 : cette classe vit HORS
    #: du paquet `backends/`, donc le registre ne la voit pas et l'invariant « tout
    #: backend concret déclare ENGINE » ne pouvait pas la rattraper — angle mort mesuré
    #: ce jour. La déclaration est posée MAINTENANT pour que le déplacement à venir
    #: n'ait plus qu'à déplacer.
    ENGINE = 'ultralytics'
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
        # Même suffixe que l'ancien chemin (`_blurred_multi-model`) : les sorties déjà sur disque
        # gardent un nom cohérent avec les nouvelles.
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

    def detect(self, **kwargs) -> dict:
        """Le process « DÉTECTION » (2026-10-04) : les objets des classes demandées, frame par
        frame, TOUS MODÈLES RÉUNIS — rendus en document `detections` (`common/utils/detections`),
        que le process « Floutage » relit. Rien n'est flouté, rien n'est écrit ici.

        Une passe par modèle sur la même source, en FLUX (`stream=True`) : aucune frame n'est
        gardée en mémoire — l'ancienne passe unique gardait la vidéo entière pour la flouter
        ensuite. Chaque modèle ne détecte QUE les classes qui lui ont été confiées, selon SON
        vocabulaire (les index de classe diffèrent d'un jeu de poids à l'autre).

        kwargs : `media_path`, `classes2blur`, `detection_threshold`, `on_frame(i, image,
        détections)` (aperçu « pendant », limité par la tâche), `progress(faites, total)`.
        """
        from wama.common.utils import detections as dets
        from wama.common.utils.video_utils import is_image
        if not self.models:
            raise RuntimeError("Aucun modèle de détection chargé.")
        source = kwargs.get('media_path') or self.input_path
        self.input_path = source
        self.classes2blur = kwargs.get('classes2blur', self.classes2blur)
        wanted = [c.lower() for c in self.classes2blur]
        threshold = float(kwargs.get('detection_threshold', self.conf))
        on_frame, progress = kwargs.get('on_frame'), kwargs.get('progress')

        image_mode = is_image(source)
        if image_mode:
            image = cv2.imread(source)
            if image is None:
                raise RuntimeError(f"Image illisible : {os.path.basename(source)}")
            height, width = image.shape[:2]
            fps, total = 0.0, 1
        else:
            capture = cv2.VideoCapture(source)
            fps = capture.get(cv2.CAP_PROP_FPS) or 25.0
            width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
            total = int(capture.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
            capture.release()

        doc = dets.new_document(
            media='image' if image_mode else 'video', width=width, height=height, fps=fps,
            frame_count=total, engine='yolo', models=[m['name'] for m in self.models],
            classes=wanted)
        doc['tag'] = self._get_model_suffix()

        passes = []
        for rang, entree in enumerate(self.models):
            voulues = entree['classes'] or wanted
            indices = self._indices_classes(entree['class_list'], voulues)
            if not indices:
                print(f"[Detection] {entree['name']} : aucune classe demandée en commun "
                      f"({voulues}) — modèle ignoré pour ce média")
                continue
            entree['indices'] = indices
            passes.append((rang, entree, indices))

        for n, (rang, entree, indices) in enumerate(passes):
            def _results(dev, _e=entree, _idx=indices):
                if image_mode:
                    return _e['yolo'].predict(
                        source=image, task=self.task, device=dev, retina_masks=self.ret_mask,
                        imgsz=max(image.shape[:2]), conf=threshold, classes=_idx, verbose=False)
                return _e['yolo'].track(
                    source=source, task=self.task, device=dev, retina_masks=self.ret_mask,
                    imgsz=width, classes=_idx, conf=threshold, stream=True, verbose=False)

            def _pass(dev, _rang=rang, _e=entree, _n=n):
                # Collectées À PART puis réunies au document : une passe REJOUÉE après une
                # erreur CUDA (`_reessayer`) n'ajoute pas deux fois ses détections.
                local = []
                for index, result in enumerate(_results(dev)):
                    found = list(self._frame_detections(_rang, _e, result, wanted, threshold))
                    if found:
                        local.append((index, found))
                    if on_frame:
                        earlier = doc.get('_index', {}).get(index)
                        shown = (doc['frames'][earlier]['d'] if earlier is not None else []) + found
                        on_frame(index, result.orig_img, shown)
                    if progress:
                        done = _n * max(total, 1) + index + 1
                        progress(done, len(passes) * max(total, 1))
                return local

            # Repli CPU sur une IMAGE seulement (quelques secondes) ; sur une vidéo il durerait
            # des heures et donnerait l'illusion d'un blocage — l'échec remonte, dit.
            found_frames = self._reessayer(
                lambda: _pass(self.device),
                replier_sur_cpu=(lambda: _pass('cpu')) if image_mode else None)
            for index, found in found_frames:
                dets.add(doc, index, found)
        print(f"[Detection] {dets.count(doc)} détection(s) sur {len(doc['frames'])} frame(s)")
        return doc

    def _frame_detections(self, rang, entree, result, classes, threshold):
        """Détections de CE modèle sur CETTE frame, au format du document : classe demandée
        (alias compris — le modèle rend `License_Plate` là où la demande dit `plate`), au-dessus
        du seuil ; contour en polygones quand le modèle segmente ; piste préfixée du rang du
        modèle (deux modèles numérotent leurs pistes indépendamment : sans préfixe, la piste 1
        des visages et la piste 1 des plaques se confondraient à l'interpolation)."""
        from wama.common.services.model_coverage import formes_equivalentes, normaliser_classe
        from wama.common.utils import detections as dets
        if not result.boxes:
            return
        acceptees = set()
        for v in (entree.get('classes') or classes or []):
            acceptees |= formes_equivalentes(v)
        contours = None
        if entree.get('seg') and getattr(result, 'masks', None) is not None:
            contours = result.masks.xy
        for i, d in enumerate(result.boxes):
            label = result.names[int(d.cls)]
            confidence = float(d.conf)
            if normaliser_classe(label) not in acceptees or confidence < threshold:
                continue
            polygons = None
            if contours is not None and i < len(contours):
                polygons = dets.points_to_polygons(contours[i]) or None
            raw = getattr(d, 'id', None)
            track = f"m{rang}:{int(raw)}" if raw is not None else None
            yield dets.detection(box=d.xyxy[0].cpu().numpy().tolist(), label=label,
                                 conf=confidence, track=track, polygons=polygons)


def stop_process():
    print('Process stopped')
