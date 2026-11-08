"""
Face detection and ROI extraction utilities.
Uses MediaPipe for face mesh and landmark detection.
"""
import logging
from dataclasses import dataclass, field
from typing import Optional, Tuple, List, Dict, Any
import numpy as np

logger = logging.getLogger(__name__)

# Configure logging format if not already configured
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(
        '[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    ))
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)


@dataclass
class FaceLandmarks:
    """Container for face landmarks data."""
    landmarks: np.ndarray  # Shape: (468, 3) for MediaPipe Face Mesh
    bbox: Tuple[int, int, int, int]  # x, y, width, height
    confidence: float = 1.0

    # Key landmark indices for MediaPipe Face Mesh
    LEFT_EYE_INDICES: List[int] = field(default_factory=lambda: [
        33, 7, 163, 144, 145, 153, 154, 155, 133, 173, 157, 158, 159, 160, 161, 246
    ])
    RIGHT_EYE_INDICES: List[int] = field(default_factory=lambda: [
        362, 382, 381, 380, 374, 373, 390, 249, 263, 466, 388, 387, 386, 385, 384, 398
    ])
    LEFT_IRIS_INDICES: List[int] = field(default_factory=lambda: [468, 469, 470, 471, 472])
    RIGHT_IRIS_INDICES: List[int] = field(default_factory=lambda: [473, 474, 475, 476, 477])
    FOREHEAD_INDICES: List[int] = field(default_factory=lambda: [10, 67, 69, 104, 108, 109, 151, 299, 337, 338])
    LEFT_CHEEK_INDICES: List[int] = field(default_factory=lambda: [116, 117, 118, 119, 100, 36, 205, 206, 207])
    RIGHT_CHEEK_INDICES: List[int] = field(default_factory=lambda: [345, 346, 347, 348, 329, 266, 425, 426, 427])
    NOSE_INDICES: List[int] = field(default_factory=lambda: [1, 2, 3, 4, 5, 6, 168, 195, 197])


@dataclass
class ROI:
    """Region of Interest for analysis."""
    name: str
    x: int
    y: int
    width: int
    height: int
    pixels: Optional[np.ndarray] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            'name': self.name,
            'x': self.x,
            'y': self.y,
            'width': self.width,
            'height': self.height
        }


class FaceDetector:
    """
    Les repères du visage (478 points, iris compris) d'une image, et la pose de la tête.

    Le modèle est celui du contrat commun `face-landmark-detection`
    (`common/backends/mediapipe_face_landmarker_backend`), obtenu par la porte de lancement
    (`backend_instance_for_key`) : chargé une fois, gardé par le cache commun, déchargé par le
    déchargement commun. Jusqu'au 2026-11-08, ce module le chargeait lui-même — un
    `FaceLandmarker` par détecteur, donc par IMAGE en temps réel —, avec un repli sur l'API
    `solutions` de MediaPipe, absente de la version installée (0.10.31).
    """

    def __init__(self):
        self._backend = None

    def _landmarker(self):
        """Le backend du Face Landmarker, chargé (la porte commune ; `load` est idempotent). Absent,
        son `load` le DIT (`pull_model …`) : la route l'installe, l'app ne télécharge rien."""
        if self._backend is None:
            from wama.common.backends.manager import backend_instance_for_key
            from .model_config import FACE_LANDMARKER_KEY
            backend = backend_instance_for_key(FACE_LANDMARKER_KEY)
            backend.load(FACE_LANDMARKER_KEY)
            self._backend = backend
        return self._backend

    def detect(self, frame: np.ndarray) -> Optional[FaceLandmarks]:
        """
        Detect face and extract landmarks from a frame.

        Args:
            frame: BGR image as numpy array (OpenCV format).

        Returns:
            FaceLandmarks object or None if no face detected.
        """
        import cv2

        faces = self._landmarker().detect_face_landmarks(
            image=cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        if not faces:
            return None

        # Le premier visage ; ses repères sont en pixels (contrat du backend).
        landmarks = faces[0]

        # Calculate bounding box
        x_coords = landmarks[:, 0]
        y_coords = landmarks[:, 1]
        x_min, x_max = int(x_coords.min()), int(x_coords.max())
        y_min, y_max = int(y_coords.min()), int(y_coords.max())

        bbox = (x_min, y_min, x_max - x_min, y_max - y_min)

        return FaceLandmarks(landmarks=landmarks, bbox=bbox)

    def get_head_pose(self, landmarks: FaceLandmarks, frame_shape: Tuple[int, int]) -> Dict[str, float]:
        """
        Estimate head pose from landmarks.

        Args:
            landmarks: Face landmarks.
            frame_shape: (height, width) of the frame.

        Returns:
            Dictionary with 'pitch', 'yaw', 'roll' in degrees.
        """
        import cv2

        h, w = frame_shape

        # 3D model points (canonical face model)
        model_points = np.array([
            (0.0, 0.0, 0.0),             # Nose tip (landmark 1)
            (0.0, -330.0, -65.0),        # Chin (landmark 152)
            (-225.0, 170.0, -135.0),     # Left eye corner (landmark 263)
            (225.0, 170.0, -135.0),      # Right eye corner (landmark 33)
            (-150.0, -150.0, -125.0),    # Left mouth corner (landmark 287)
            (150.0, -150.0, -125.0)      # Right mouth corner (landmark 57)
        ], dtype=np.float64)

        # 2D image points from landmarks
        image_points = np.array([
            landmarks.landmarks[1][:2],    # Nose tip
            landmarks.landmarks[152][:2],  # Chin
            landmarks.landmarks[263][:2],  # Left eye corner
            landmarks.landmarks[33][:2],   # Right eye corner
            landmarks.landmarks[287][:2],  # Left mouth corner
            landmarks.landmarks[57][:2]    # Right mouth corner
        ], dtype=np.float64)

        # Camera matrix (approximate)
        focal_length = w
        center = (w / 2, h / 2)
        camera_matrix = np.array([
            [focal_length, 0, center[0]],
            [0, focal_length, center[1]],
            [0, 0, 1]
        ], dtype=np.float64)

        # No lens distortion
        dist_coeffs = np.zeros((4, 1))

        # Solve PnP
        success, rotation_vec, translation_vec = cv2.solvePnP(
            model_points, image_points, camera_matrix, dist_coeffs
        )

        if not success:
            return {'pitch': 0.0, 'yaw': 0.0, 'roll': 0.0}

        # Convert rotation vector to rotation matrix
        rotation_mat, _ = cv2.Rodrigues(rotation_vec)

        # Get Euler angles
        pose_mat = cv2.hconcat([rotation_mat, translation_vec])
        _, _, _, _, _, _, euler_angles = cv2.decomposeProjectionMatrix(pose_mat)

        pitch = float(euler_angles[0])
        yaw = float(euler_angles[1])
        roll = float(euler_angles[2])

        return {'pitch': pitch, 'yaw': yaw, 'roll': roll}

    def close(self):
        """Lâche le backend. Il appartient au cache COMMUN (d'autres détecteurs le partagent) : il
        n'est pas déchargé ici, c'est le déchargement commun qui le rend."""
        self._backend = None


class ROIExtractor:
    """
    Extract Regions of Interest from face landmarks.
    Provides ROIs for rPPG (forehead, cheeks), eyes, and other analysis.
    """

    def __init__(self, padding: float = 0.1):
        """
        Initialize the ROI extractor.

        Args:
            padding: Padding ratio to add around ROIs (0.1 = 10%).
        """
        self.padding = padding

    def extract_forehead_roi(self, frame: np.ndarray, landmarks: FaceLandmarks) -> ROI:
        """Extract forehead ROI for rPPG analysis."""
        indices = landmarks.FOREHEAD_INDICES
        points = landmarks.landmarks[indices]
        return self._create_roi_from_points(frame, points, "forehead")

    def extract_left_cheek_roi(self, frame: np.ndarray, landmarks: FaceLandmarks) -> ROI:
        """Extract left cheek ROI for rPPG analysis."""
        indices = landmarks.LEFT_CHEEK_INDICES
        points = landmarks.landmarks[indices]
        return self._create_roi_from_points(frame, points, "left_cheek")

    def extract_right_cheek_roi(self, frame: np.ndarray, landmarks: FaceLandmarks) -> ROI:
        """Extract right cheek ROI for rPPG analysis."""
        indices = landmarks.RIGHT_CHEEK_INDICES
        points = landmarks.landmarks[indices]
        return self._create_roi_from_points(frame, points, "right_cheek")

    def extract_left_eye_roi(self, frame: np.ndarray, landmarks: FaceLandmarks) -> ROI:
        """Extract left eye ROI for eye tracking."""
        indices = landmarks.LEFT_EYE_INDICES
        points = landmarks.landmarks[indices]
        return self._create_roi_from_points(frame, points, "left_eye")

    def extract_right_eye_roi(self, frame: np.ndarray, landmarks: FaceLandmarks) -> ROI:
        """Extract right eye ROI for eye tracking."""
        indices = landmarks.RIGHT_EYE_INDICES
        points = landmarks.landmarks[indices]
        return self._create_roi_from_points(frame, points, "right_eye")

    def extract_all_rppg_rois(self, frame: np.ndarray, landmarks: FaceLandmarks) -> List[ROI]:
        """Extract all ROIs useful for rPPG (forehead + cheeks)."""
        return [
            self.extract_forehead_roi(frame, landmarks),
            self.extract_left_cheek_roi(frame, landmarks),
            self.extract_right_cheek_roi(frame, landmarks)
        ]

    def _create_roi_from_points(self, frame: np.ndarray, points: np.ndarray, name: str) -> ROI:
        """Create a ROI from a set of landmark points."""
        h, w = frame.shape[:2]

        x_coords = points[:, 0]
        y_coords = points[:, 1]

        x_min, x_max = int(x_coords.min()), int(x_coords.max())
        y_min, y_max = int(y_coords.min()), int(y_coords.max())

        # Add padding
        pad_x = int((x_max - x_min) * self.padding)
        pad_y = int((y_max - y_min) * self.padding)

        x_min = max(0, x_min - pad_x)
        x_max = min(w, x_max + pad_x)
        y_min = max(0, y_min - pad_y)
        y_max = min(h, y_max + pad_y)

        # Extract pixels
        pixels = frame[y_min:y_max, x_min:x_max].copy()

        return ROI(
            name=name,
            x=x_min,
            y=y_min,
            width=x_max - x_min,
            height=y_max - y_min,
            pixels=pixels
        )
