"""
Visualization utilities for Face Analyzer.
Provides data formatting for charts and overlay rendering.
"""
import logging
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Tuple
from enum import Enum
import numpy as np

logger = logging.getLogger(__name__)


class ChartType(Enum):
    """Types of charts for data visualization."""
    LINE = "line"
    AREA = "area"
    BAR = "bar"
    SCATTER = "scatter"
    GAUGE = "gauge"


@dataclass
class ChartSeries:
    """A single data series for a chart."""
    name: str
    data: List[float]
    timestamps: List[float] = field(default_factory=list)
    color: str = "#3498db"
    unit: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            'name': self.name,
            'data': self.data,
            'timestamps': self.timestamps,
            'color': self.color,
            'unit': self.unit
        }


@dataclass
class ChartConfig:
    """Configuration for a chart."""
    id: str
    title: str
    type: ChartType = ChartType.LINE
    y_axis_label: str = ""
    y_axis_min: Optional[float] = None
    y_axis_max: Optional[float] = None
    x_axis_label: str = "Time (s)"
    series: List[ChartSeries] = field(default_factory=list)
    update_interval_ms: int = 100
    window_seconds: float = 30.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'title': self.title,
            'type': self.type.value,
            'yAxisLabel': self.y_axis_label,
            'yAxisMin': self.y_axis_min,
            'yAxisMax': self.y_axis_max,
            'xAxisLabel': self.x_axis_label,
            'series': [s.to_dict() for s in self.series],
            'updateIntervalMs': self.update_interval_ms,
            'windowSeconds': self.window_seconds
        }


class ChartData:
    """
    Manages chart data for real-time visualization.
    """

    @staticmethod
    def create_heart_rate_chart() -> ChartConfig:
        """Create configuration for heart rate chart."""
        return ChartConfig(
            id="heart_rate",
            title="Heart Rate",
            type=ChartType.LINE,
            y_axis_label="BPM",
            y_axis_min=40,
            y_axis_max=180,
            series=[
                ChartSeries(name="HR", data=[], color="#e74c3c", unit="bpm")
            ],
            window_seconds=60.0
        )

    @staticmethod
    def create_hrv_chart() -> ChartConfig:
        """Create configuration for HRV chart."""
        return ChartConfig(
            id="hrv",
            title="Heart Rate Variability",
            type=ChartType.LINE,
            y_axis_label="ms",
            y_axis_min=0,
            y_axis_max=200,
            series=[
                ChartSeries(name="SDNN", data=[], color="#9b59b6", unit="ms"),
                ChartSeries(name="RMSSD", data=[], color="#3498db", unit="ms")
            ],
            window_seconds=60.0
        )

    @staticmethod
    def create_respiration_chart() -> ChartConfig:
        """Create configuration for respiration chart."""
        return ChartConfig(
            id="respiration",
            title="Respiration",
            type=ChartType.AREA,
            y_axis_label="Breaths/min",
            y_axis_min=5,
            y_axis_max=35,
            series=[
                ChartSeries(name="RR", data=[], color="#2ecc71", unit="br/min")
            ],
            window_seconds=60.0
        )

    @staticmethod
    def create_pupil_chart() -> ChartConfig:
        """Create configuration for pupil diameter chart."""
        return ChartConfig(
            id="pupil",
            title="Pupil Diameter",
            type=ChartType.LINE,
            y_axis_label="Relative Size",
            y_axis_min=0,
            y_axis_max=1,
            series=[
                ChartSeries(name="Left", data=[], color="#e67e22", unit=""),
                ChartSeries(name="Right", data=[], color="#f39c12", unit="")
            ],
            window_seconds=30.0
        )

    @staticmethod
    def create_blink_chart() -> ChartConfig:
        """Create configuration for blink rate chart."""
        return ChartConfig(
            id="blink",
            title="Blink Rate",
            type=ChartType.BAR,
            y_axis_label="Blinks/min",
            y_axis_min=0,
            y_axis_max=30,
            series=[
                ChartSeries(name="Blinks", data=[], color="#1abc9c", unit="/min")
            ],
            window_seconds=60.0
        )

    @staticmethod
    def create_emotion_chart() -> ChartConfig:
        """Create configuration for emotion chart."""
        return ChartConfig(
            id="emotions",
            title="Emotions",
            type=ChartType.BAR,
            y_axis_label="Confidence",
            y_axis_min=0,
            y_axis_max=1,
            series=[
                ChartSeries(name="Happy", data=[], color="#f1c40f", unit=""),
                ChartSeries(name="Sad", data=[], color="#3498db", unit=""),
                ChartSeries(name="Angry", data=[], color="#e74c3c", unit=""),
                ChartSeries(name="Fear", data=[], color="#9b59b6", unit=""),
                ChartSeries(name="Surprise", data=[], color="#e67e22", unit=""),
                ChartSeries(name="Disgust", data=[], color="#27ae60", unit=""),
                ChartSeries(name="Neutral", data=[], color="#95a5a6", unit="")
            ],
            window_seconds=10.0
        )

    @staticmethod
    def create_gaze_chart() -> ChartConfig:
        """Create configuration for gaze direction chart."""
        return ChartConfig(
            id="gaze",
            title="Gaze Direction",
            type=ChartType.LINE,
            y_axis_label="Angle (deg)",
            y_axis_min=-45,
            y_axis_max=45,
            series=[
                ChartSeries(name="Horizontal", data=[], color="#3498db", unit="deg"),
                ChartSeries(name="Vertical", data=[], color="#e74c3c", unit="deg")
            ],
            window_seconds=30.0
        )

    @staticmethod
    def create_head_pose_chart() -> ChartConfig:
        """Create configuration for head pose chart."""
        return ChartConfig(
            id="head_pose",
            title="Head Pose",
            type=ChartType.LINE,
            y_axis_label="Angle (deg)",
            y_axis_min=-90,
            y_axis_max=90,
            series=[
                ChartSeries(name="Pitch", data=[], color="#e74c3c", unit="deg"),
                ChartSeries(name="Yaw", data=[], color="#3498db", unit="deg"),
                ChartSeries(name="Roll", data=[], color="#2ecc71", unit="deg")
            ],
            window_seconds=30.0
        )

    @staticmethod
    def create_rppg_waveform_chart() -> ChartConfig:
        """Create configuration for rPPG waveform chart."""
        return ChartConfig(
            id="rppg_waveform",
            title="rPPG Waveform",
            type=ChartType.LINE,
            y_axis_label="Amplitude",
            series=[
                ChartSeries(name="PPG", data=[], color="#e74c3c", unit="")
            ],
            window_seconds=10.0
        )

    @staticmethod
    def get_all_charts() -> List[ChartConfig]:
        """Get all default chart configurations."""
        return [
            ChartData.create_heart_rate_chart(),
            ChartData.create_hrv_chart(),
            ChartData.create_respiration_chart(),
            ChartData.create_pupil_chart(),
            ChartData.create_blink_chart(),
            ChartData.create_emotion_chart(),
            ChartData.create_gaze_chart(),
            ChartData.create_head_pose_chart(),
            ChartData.create_rppg_waveform_chart()
        ]


class OverlayRenderer:
    """
    Render overlays on video frames for visualization.
    """

    # Colors (BGR for OpenCV)
    COLOR_GREEN = (0, 255, 0)
    COLOR_RED = (0, 0, 255)
    COLOR_BLUE = (255, 0, 0)
    COLOR_YELLOW = (0, 255, 255)
    COLOR_CYAN = (255, 255, 0)
    COLOR_MAGENTA = (255, 0, 255)
    COLOR_WHITE = (255, 255, 255)
    COLOR_ORANGE = (0, 165, 255)

    def __init__(self):
        self._font = None
        self._font_scale = 0.5
        self._thickness = 1

    def _get_cv2(self):
        """Lazy import cv2."""
        import cv2
        if self._font is None:
            self._font = cv2.FONT_HERSHEY_SIMPLEX
        return cv2

    def draw_face_landmarks(self, frame: np.ndarray, landmarks: np.ndarray,
                           indices: List[int] = None, color: Tuple[int, int, int] = None) -> np.ndarray:
        """Draw face landmarks on frame."""
        cv2 = self._get_cv2()
        color = color or self.COLOR_GREEN

        if indices is None:
            indices = range(len(landmarks))

        for idx in indices:
            if idx < len(landmarks):
                x, y = int(landmarks[idx][0]), int(landmarks[idx][1])
                cv2.circle(frame, (x, y), 1, color, -1)

        return frame

    def draw_roi(self, frame: np.ndarray, x: int, y: int, w: int, h: int,
                label: str = "", color: Tuple[int, int, int] = None) -> np.ndarray:
        """Draw a region of interest rectangle."""
        cv2 = self._get_cv2()
        color = color or self.COLOR_CYAN

        cv2.rectangle(frame, (x, y), (x + w, y + h), color, 2)

        if label:
            cv2.putText(frame, label, (x, y - 5), self._font,
                       self._font_scale, color, self._thickness)

        return frame

    def draw_gaze_arrow(self, frame: np.ndarray, eye_center: Tuple[int, int],
                       gaze_direction: Tuple[float, float], length: int = 50,
                       color: Tuple[int, int, int] = None) -> np.ndarray:
        """Draw gaze direction arrow from eye center."""
        cv2 = self._get_cv2()
        color = color or self.COLOR_YELLOW

        x, y = eye_center
        dx, dy = gaze_direction

        # Normalize and scale
        norm = np.sqrt(dx**2 + dy**2)
        if norm > 0:
            dx, dy = dx / norm * length, dy / norm * length

        end_x, end_y = int(x + dx), int(y + dy)
        cv2.arrowedLine(frame, (x, y), (end_x, end_y), color, 2, tipLength=0.3)

        return frame

    def draw_head_pose_axes(self, frame: np.ndarray, nose_point: Tuple[int, int],
                           rotation: Dict[str, float], axis_length: int = 50) -> np.ndarray:
        """Draw 3D head pose axes (XYZ)."""
        cv2 = self._get_cv2()

        x, y = nose_point
        pitch = np.radians(rotation.get('pitch', 0))
        yaw = np.radians(rotation.get('yaw', 0))
        roll = np.radians(rotation.get('roll', 0))

        # Rotation matrices
        Rx = np.array([
            [1, 0, 0],
            [0, np.cos(pitch), -np.sin(pitch)],
            [0, np.sin(pitch), np.cos(pitch)]
        ])
        Ry = np.array([
            [np.cos(yaw), 0, np.sin(yaw)],
            [0, 1, 0],
            [-np.sin(yaw), 0, np.cos(yaw)]
        ])
        Rz = np.array([
            [np.cos(roll), -np.sin(roll), 0],
            [np.sin(roll), np.cos(roll), 0],
            [0, 0, 1]
        ])

        R = Rz @ Ry @ Rx

        # Axis vectors
        axes = np.array([
            [axis_length, 0, 0],   # X (Red)
            [0, axis_length, 0],   # Y (Green)
            [0, 0, axis_length]    # Z (Blue)
        ]).T

        # Rotate axes
        rotated = R @ axes

        # Project to 2D (simple orthographic)
        colors = [self.COLOR_RED, self.COLOR_GREEN, self.COLOR_BLUE]
        labels = ['X', 'Y', 'Z']

        for i in range(3):
            end_x = int(x + rotated[0, i])
            end_y = int(y + rotated[1, i])
            cv2.arrowedLine(frame, (x, y), (end_x, end_y), colors[i], 2, tipLength=0.2)
            cv2.putText(frame, labels[i], (end_x + 5, end_y + 5),
                       self._font, 0.4, colors[i], 1)

        return frame

    def draw_metrics_overlay(self, frame: np.ndarray, metrics: Dict[str, Any],
                            position: Tuple[int, int] = (10, 30)) -> np.ndarray:
        """Draw metrics text overlay."""
        cv2 = self._get_cv2()

        x, y = position
        line_height = 25

        for i, (key, value) in enumerate(metrics.items()):
            if isinstance(value, float):
                text = f"{key}: {value:.1f}"
            else:
                text = f"{key}: {value}"

            cv2.putText(frame, text, (x, y + i * line_height),
                       self._font, self._font_scale, self.COLOR_WHITE, self._thickness)

        return frame

    def draw_emotion_bars(self, frame: np.ndarray, emotions: Dict[str, float],
                         position: Tuple[int, int] = (10, 200),
                         bar_width: int = 100, bar_height: int = 15) -> np.ndarray:
        """Draw emotion probability bars."""
        cv2 = self._get_cv2()

        x, y = position
        spacing = bar_height + 5

        emotion_colors = {
            'happy': self.COLOR_YELLOW,
            'sad': self.COLOR_BLUE,
            'angry': self.COLOR_RED,
            'fear': self.COLOR_MAGENTA,
            'surprise': self.COLOR_ORANGE,
            'disgust': self.COLOR_GREEN,
            'neutral': (150, 150, 150)
        }

        for i, (emotion, prob) in enumerate(emotions.items()):
            current_y = y + i * spacing
            color = emotion_colors.get(emotion.lower(), self.COLOR_WHITE)

            # Background bar
            cv2.rectangle(frame, (x, current_y), (x + bar_width, current_y + bar_height),
                         (50, 50, 50), -1)

            # Filled bar
            filled_width = int(bar_width * prob)
            cv2.rectangle(frame, (x, current_y), (x + filled_width, current_y + bar_height),
                         color, -1)

            # Label
            label = f"{emotion[:3]}: {prob:.0%}"
            cv2.putText(frame, label, (x + bar_width + 5, current_y + bar_height - 3),
                       self._font, 0.4, self.COLOR_WHITE, 1)

        return frame

    def draw_iris_center(self, frame: np.ndarray, iris_center: Tuple[int, int],
                        radius: int = 5, color: Tuple[int, int, int] = None) -> np.ndarray:
        """Draw iris center point."""
        cv2 = self._get_cv2()
        color = color or self.COLOR_CYAN

        cv2.circle(frame, iris_center, radius, color, -1)
        cv2.circle(frame, iris_center, radius + 2, self.COLOR_WHITE, 1)

        return frame

    def draw_blink_indicator(self, frame: np.ndarray, is_blinking: bool,
                            position: Tuple[int, int] = (10, 10)) -> np.ndarray:
        """Draw blink indicator."""
        cv2 = self._get_cv2()

        color = self.COLOR_RED if is_blinking else self.COLOR_GREEN
        label = "BLINK" if is_blinking else "OPEN"

        cv2.circle(frame, position, 10, color, -1)
        cv2.putText(frame, label, (position[0] + 15, position[1] + 5),
                   self._font, 0.5, color, 1)

        return frame
