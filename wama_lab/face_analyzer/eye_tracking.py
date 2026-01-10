"""
Eye tracking and oculometry module.
Provides gaze estimation, pupil analysis, and blink detection.

Uses MediaPipe Face Mesh with iris tracking for:
- Gaze direction estimation
- Pupil diameter measurement
- Blink detection and rate
- Eye openness (PERCLOS)
"""
import logging
from dataclasses import dataclass
from typing import Optional, List, Tuple, Dict, Any
from collections import deque
import numpy as np

from .utils.preprocessing import FaceLandmarks

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
class GazeResult:
    """Gaze estimation result."""
    horizontal: float  # Degrees, negative = left, positive = right
    vertical: float  # Degrees, negative = down, positive = up
    screen_x: Optional[float] = None  # Normalized screen coordinate (0-1)
    screen_y: Optional[float] = None
    confidence: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            'horizontal': round(self.horizontal, 1),
            'vertical': round(self.vertical, 1),
            'screen_x': round(self.screen_x, 3) if self.screen_x else None,
            'screen_y': round(self.screen_y, 3) if self.screen_y else None,
            'confidence': round(self.confidence, 2)
        }


@dataclass
class PupilResult:
    """Pupil measurement result."""
    left_diameter: float  # Relative diameter (0-1)
    right_diameter: float
    left_center: Tuple[int, int]  # Pixel coordinates
    right_center: Tuple[int, int]
    average_diameter: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            'left_diameter': round(self.left_diameter, 3),
            'right_diameter': round(self.right_diameter, 3),
            'average_diameter': round(self.average_diameter, 3),
            'left_center': self.left_center,
            'right_center': self.right_center
        }


@dataclass
class BlinkResult:
    """Blink detection result."""
    is_blinking: bool
    left_eye_openness: float  # 0 = closed, 1 = fully open
    right_eye_openness: float
    blink_rate: float  # Blinks per minute (rolling average)
    blink_duration: float  # Current blink duration in ms (if blinking)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'is_blinking': self.is_blinking,
            'left_openness': round(self.left_eye_openness, 2),
            'right_openness': round(self.right_eye_openness, 2),
            'blink_rate': round(self.blink_rate, 1),
            'blink_duration': round(self.blink_duration, 0)
        }


@dataclass
class EyeTrackingResult:
    """Complete eye tracking result."""
    gaze: GazeResult
    pupil: PupilResult
    blink: BlinkResult
    perclos: float  # Percentage of eye closure over time (fatigue indicator)
    timestamp: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            'gaze': self.gaze.to_dict(),
            'pupil': self.pupil.to_dict(),
            'blink': self.blink.to_dict(),
            'perclos': round(self.perclos, 2),
            'timestamp': self.timestamp
        }


class EyeTracker:
    """
    Eye tracking and oculometry analysis.

    Provides:
    - Gaze direction estimation
    - Pupil diameter tracking
    - Blink detection and rate
    - PERCLOS (fatigue indicator)
    """

    # MediaPipe Face Mesh indices
    LEFT_EYE_OUTER = 33
    LEFT_EYE_INNER = 133
    LEFT_EYE_TOP = 159
    LEFT_EYE_BOTTOM = 145

    RIGHT_EYE_OUTER = 362
    RIGHT_EYE_INNER = 263
    RIGHT_EYE_TOP = 386
    RIGHT_EYE_BOTTOM = 374

    # Iris indices (if refine_landmarks=True)
    LEFT_IRIS_CENTER = 468
    RIGHT_IRIS_CENTER = 473

    # Blink threshold (eye aspect ratio)
    BLINK_THRESHOLD = 0.2

    def __init__(self,
                 fps: float = 30.0,
                 blink_history_seconds: float = 60.0,
                 perclos_window_seconds: float = 60.0):
        """
        Initialize eye tracker.

        Args:
            fps: Video frame rate.
            blink_history_seconds: Window for blink rate calculation.
            perclos_window_seconds: Window for PERCLOS calculation.
        """
        self.fps = fps
        self._blink_history_size = int(blink_history_seconds * fps)
        self._perclos_window_size = int(perclos_window_seconds * fps)

        # Calibration
        self._calibrated = False
        self._baseline_pupil_size = 1.0
        self._baseline_eye_openness = 1.0

        # State
        self._is_blinking = False
        self._blink_start_time: Optional[float] = None
        self._blink_timestamps: deque = deque(maxlen=100)
        self._eye_openness_history: deque = deque(maxlen=self._perclos_window_size)

        # Frame counter
        self._frame_count = 0

    def reset(self):
        """Reset tracker state."""
        self._is_blinking = False
        self._blink_start_time = None
        self._blink_timestamps.clear()
        self._eye_openness_history.clear()
        self._frame_count = 0

    def calibrate(self, landmarks: FaceLandmarks):
        """
        Calibrate baselines from a neutral expression.

        Args:
            landmarks: Face landmarks in neutral expression.
        """
        left_openness = self._calculate_eye_openness(landmarks, 'left')
        right_openness = self._calculate_eye_openness(landmarks, 'right')

        self._baseline_eye_openness = (left_openness + right_openness) / 2

        # Pupil size baseline
        left_pupil = self._get_pupil_diameter(landmarks, 'left')
        right_pupil = self._get_pupil_diameter(landmarks, 'right')
        self._baseline_pupil_size = (left_pupil + right_pupil) / 2

        self._calibrated = True
        logger.info(f"Eye tracker calibrated: openness={self._baseline_eye_openness:.2f}, "
                   f"pupil={self._baseline_pupil_size:.2f}")

    def process(self, landmarks: FaceLandmarks,
               frame_shape: Tuple[int, int],
               timestamp: float = None) -> EyeTrackingResult:
        """
        Process landmarks for eye tracking.

        Args:
            landmarks: Face landmarks from MediaPipe.
            frame_shape: (height, width) of the frame.
            timestamp: Current timestamp in seconds.

        Returns:
            Complete eye tracking result.
        """
        if timestamp is None:
            timestamp = self._frame_count / self.fps
        self._frame_count += 1

        # Gaze estimation
        gaze = self._estimate_gaze(landmarks, frame_shape)

        # Pupil analysis
        pupil = self._analyze_pupils(landmarks)

        # Blink detection
        blink = self._detect_blink(landmarks, timestamp)

        # PERCLOS calculation
        perclos = self._calculate_perclos()

        return EyeTrackingResult(
            gaze=gaze,
            pupil=pupil,
            blink=blink,
            perclos=perclos,
            timestamp=timestamp
        )

    def _estimate_gaze(self, landmarks: FaceLandmarks,
                      frame_shape: Tuple[int, int]) -> GazeResult:
        """Estimate gaze direction from iris position relative to eye corners."""
        h, w = frame_shape

        # Left eye
        left_outer = landmarks.landmarks[self.LEFT_EYE_OUTER][:2]
        left_inner = landmarks.landmarks[self.LEFT_EYE_INNER][:2]
        left_iris = landmarks.landmarks[self.LEFT_IRIS_CENTER][:2] if len(landmarks.landmarks) > 468 else None

        # Right eye
        right_outer = landmarks.landmarks[self.RIGHT_EYE_OUTER][:2]
        right_inner = landmarks.landmarks[self.RIGHT_EYE_INNER][:2]
        right_iris = landmarks.landmarks[self.RIGHT_IRIS_CENTER][:2] if len(landmarks.landmarks) > 473 else None

        # Calculate horizontal gaze (iris position relative to eye center)
        horizontal_angles = []
        vertical_angles = []

        for eye_outer, eye_inner, iris in [(left_outer, left_inner, left_iris),
                                            (right_outer, right_inner, right_iris)]:
            if iris is None:
                continue

            # Eye center
            eye_center_x = (eye_outer[0] + eye_inner[0]) / 2
            eye_center_y = (eye_outer[1] + eye_inner[1]) / 2
            eye_width = abs(eye_outer[0] - eye_inner[0])

            # Iris displacement from center
            dx = (iris[0] - eye_center_x) / (eye_width / 2 + 1e-6)
            dy = (iris[1] - eye_center_y) / (eye_width / 2 + 1e-6)

            # Convert to degrees (approximate)
            horizontal_angles.append(dx * 30)  # ~30 degrees max horizontal
            vertical_angles.append(-dy * 20)  # ~20 degrees max vertical

        if horizontal_angles:
            horizontal = float(np.mean(horizontal_angles))
            vertical = float(np.mean(vertical_angles))
            confidence = 0.8
        else:
            horizontal = 0.0
            vertical = 0.0
            confidence = 0.0

        # Map to screen coordinates (normalized 0-1)
        screen_x = 0.5 + horizontal / 60  # Assuming ±30 degree range
        screen_y = 0.5 - vertical / 40  # Assuming ±20 degree range

        return GazeResult(
            horizontal=horizontal,
            vertical=vertical,
            screen_x=np.clip(screen_x, 0, 1),
            screen_y=np.clip(screen_y, 0, 1),
            confidence=confidence
        )

    def _analyze_pupils(self, landmarks: FaceLandmarks) -> PupilResult:
        """Analyze pupil size and position."""
        left_diameter = self._get_pupil_diameter(landmarks, 'left')
        right_diameter = self._get_pupil_diameter(landmarks, 'right')

        # Normalize by baseline if calibrated
        if self._calibrated and self._baseline_pupil_size > 0:
            left_diameter /= self._baseline_pupil_size
            right_diameter /= self._baseline_pupil_size
        else:
            # Normalize to 0-1 range
            left_diameter = np.clip(left_diameter, 0, 1)
            right_diameter = np.clip(right_diameter, 0, 1)

        # Iris centers
        if len(landmarks.landmarks) > 473:
            left_center = tuple(landmarks.landmarks[self.LEFT_IRIS_CENTER][:2].astype(int))
            right_center = tuple(landmarks.landmarks[self.RIGHT_IRIS_CENTER][:2].astype(int))
        else:
            # Fallback to eye center
            left_center = tuple(((landmarks.landmarks[self.LEFT_EYE_OUTER][:2] +
                                 landmarks.landmarks[self.LEFT_EYE_INNER][:2]) / 2).astype(int))
            right_center = tuple(((landmarks.landmarks[self.RIGHT_EYE_OUTER][:2] +
                                  landmarks.landmarks[self.RIGHT_EYE_INNER][:2]) / 2).astype(int))

        return PupilResult(
            left_diameter=left_diameter,
            right_diameter=right_diameter,
            left_center=left_center,
            right_center=right_center,
            average_diameter=(left_diameter + right_diameter) / 2
        )

    def _get_pupil_diameter(self, landmarks: FaceLandmarks, eye: str) -> float:
        """Get pupil diameter (as ratio of eye width)."""
        if eye == 'left':
            outer_idx, inner_idx = self.LEFT_EYE_OUTER, self.LEFT_EYE_INNER
            iris_indices = landmarks.LEFT_IRIS_INDICES
        else:
            outer_idx, inner_idx = self.RIGHT_EYE_OUTER, self.RIGHT_EYE_INNER
            iris_indices = landmarks.RIGHT_IRIS_INDICES

        # Eye width
        eye_width = np.linalg.norm(
            landmarks.landmarks[outer_idx][:2] - landmarks.landmarks[inner_idx][:2]
        )

        # Iris size (if available)
        if len(landmarks.landmarks) > max(iris_indices):
            iris_points = landmarks.landmarks[iris_indices][:, :2]
            iris_diameter = np.max([
                np.linalg.norm(iris_points[0] - iris_points[2]),
                np.linalg.norm(iris_points[1] - iris_points[3])
            ])
            return iris_diameter / (eye_width + 1e-6)

        # Fallback: estimate from eye openness
        return self._calculate_eye_openness(landmarks, eye) * 0.5

    def _detect_blink(self, landmarks: FaceLandmarks, timestamp: float) -> BlinkResult:
        """Detect blinks and calculate blink rate."""
        left_openness = self._calculate_eye_openness(landmarks, 'left')
        right_openness = self._calculate_eye_openness(landmarks, 'right')
        avg_openness = (left_openness + right_openness) / 2

        # Store for PERCLOS
        self._eye_openness_history.append(avg_openness)

        # Blink detection using threshold
        threshold = self._baseline_eye_openness * self.BLINK_THRESHOLD if self._calibrated else self.BLINK_THRESHOLD
        is_eye_closed = avg_openness < threshold

        # State machine for blink detection
        blink_duration = 0.0
        if is_eye_closed and not self._is_blinking:
            # Blink started
            self._is_blinking = True
            self._blink_start_time = timestamp
        elif not is_eye_closed and self._is_blinking:
            # Blink ended
            self._is_blinking = False
            if self._blink_start_time:
                blink_duration = (timestamp - self._blink_start_time) * 1000  # Convert to ms
                # Only count as blink if duration is realistic (50-500ms)
                if 50 < blink_duration < 500:
                    self._blink_timestamps.append(timestamp)
            self._blink_start_time = None
        elif self._is_blinking and self._blink_start_time:
            blink_duration = (timestamp - self._blink_start_time) * 1000

        # Calculate blink rate (blinks per minute)
        blink_rate = 0.0
        if self._blink_timestamps:
            # Count blinks in last 60 seconds
            one_minute_ago = timestamp - 60
            recent_blinks = sum(1 for t in self._blink_timestamps if t > one_minute_ago)
            # Scale to full minute
            elapsed = min(60, timestamp)
            blink_rate = (recent_blinks / elapsed) * 60 if elapsed > 0 else 0

        return BlinkResult(
            is_blinking=self._is_blinking,
            left_eye_openness=left_openness,
            right_eye_openness=right_openness,
            blink_rate=blink_rate,
            blink_duration=blink_duration
        )

    def _calculate_eye_openness(self, landmarks: FaceLandmarks, eye: str) -> float:
        """Calculate eye openness using Eye Aspect Ratio (EAR)."""
        if eye == 'left':
            top_idx, bottom_idx = self.LEFT_EYE_TOP, self.LEFT_EYE_BOTTOM
            outer_idx, inner_idx = self.LEFT_EYE_OUTER, self.LEFT_EYE_INNER
        else:
            top_idx, bottom_idx = self.RIGHT_EYE_TOP, self.RIGHT_EYE_BOTTOM
            outer_idx, inner_idx = self.RIGHT_EYE_OUTER, self.RIGHT_EYE_INNER

        # Vertical distance
        vertical = np.linalg.norm(
            landmarks.landmarks[top_idx][:2] - landmarks.landmarks[bottom_idx][:2]
        )

        # Horizontal distance
        horizontal = np.linalg.norm(
            landmarks.landmarks[outer_idx][:2] - landmarks.landmarks[inner_idx][:2]
        )

        # Eye Aspect Ratio
        ear = vertical / (horizontal + 1e-6)

        return float(ear)

    def _calculate_perclos(self) -> float:
        """
        Calculate PERCLOS (PERcentage of eye CLOSure).
        A fatigue indicator: percentage of time eyes are >80% closed.
        """
        if not self._eye_openness_history:
            return 0.0

        # Threshold for "closed" (less than 20% open)
        closed_threshold = 0.2 * (self._baseline_eye_openness if self._calibrated else 1.0)

        closed_count = sum(1 for o in self._eye_openness_history if o < closed_threshold)
        return closed_count / len(self._eye_openness_history)
