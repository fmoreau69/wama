"""
Face Analysis Pipeline.
Orchestrates all analysis modules for comprehensive facial analysis.
"""
import logging
import time
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List, Callable
from enum import Enum
import numpy as np

from .utils.preprocessing import FaceDetector, ROIExtractor, FaceLandmarks
from .utils.visualization import OverlayRenderer, ChartData
from .rppg import RPPGExtractor, RPPGMethod, RPPGResult
from .eye_tracking import EyeTracker, EyeTrackingResult
from .emotions import EmotionRecognizer, EmotionResult
from .respiration import RespirationAnalyzer, RespirationResult

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


class AnalysisMode(Enum):
    """Analysis mode configuration."""
    REALTIME = "realtime"  # Optimized for real-time webcam
    POSTPROCESS = "postprocess"  # Full analysis on recorded video


@dataclass
class PipelineConfig:
    """Configuration for the analysis pipeline."""
    fps: float = 30.0
    enable_rppg: bool = True
    enable_eye_tracking: bool = True
    enable_emotions: bool = True
    enable_respiration: bool = True
    enable_overlay: bool = True
    rppg_method: RPPGMethod = RPPGMethod.CHROM
    emotion_backend: str = 'deepface'  # 'fer' or 'deepface'
    enable_age_gender: bool = True  # DeepFace only
    mode: AnalysisMode = AnalysisMode.REALTIME


@dataclass
class FrameResult:
    """Result of analyzing a single frame."""
    timestamp: float
    face_detected: bool = False
    landmarks: Optional[FaceLandmarks] = None
    head_pose: Optional[Dict[str, float]] = None
    rppg: Optional[RPPGResult] = None
    eye_tracking: Optional[EyeTrackingResult] = None
    emotions: Optional[EmotionResult] = None
    respiration: Optional[RespirationResult] = None
    processing_time_ms: float = 0.0
    frame_with_overlay: Optional[np.ndarray] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result = {
            'timestamp': self.timestamp,
            'face_detected': self.face_detected,
            'processing_time_ms': round(self.processing_time_ms, 1)
        }

        if self.head_pose:
            result['head_pose'] = {k: round(v, 1) for k, v in self.head_pose.items()}

        if self.rppg:
            result['rppg'] = self.rppg.to_dict()

        if self.eye_tracking:
            result['eye_tracking'] = self.eye_tracking.to_dict()

        if self.emotions:
            result['emotions'] = self.emotions.to_dict()

        if self.respiration:
            result['respiration'] = self.respiration.to_dict()

        return result


class FaceAnalysisPipeline:
    """
    Complete face analysis pipeline.

    Coordinates all analysis modules:
    - Face detection and landmarks
    - rPPG (heart rate, HRV, SpO2)
    - Eye tracking (gaze, pupil, blinks)
    - Emotion recognition
    - Respiration analysis
    """

    def __init__(self, config: PipelineConfig = None):
        """
        Initialize the pipeline.

        Args:
            config: Pipeline configuration.
        """
        self.config = config or PipelineConfig()

        # Initialize components
        self._face_detector = FaceDetector(
            max_num_faces=1,
            refine_landmarks=True
        )
        self._roi_extractor = ROIExtractor()
        self._overlay_renderer = OverlayRenderer()

        # Analysis modules (lazy initialized)
        self._rppg_extractor: Optional[RPPGExtractor] = None
        self._eye_tracker: Optional[EyeTracker] = None
        self._emotion_recognizer: Optional[EmotionRecognizer] = None
        self._respiration_analyzer: Optional[RespirationAnalyzer] = None

        # State
        self._frame_count = 0
        self._start_time: Optional[float] = None
        self._last_rppg_signal: Optional[float] = None

        # Callbacks
        self._progress_callback: Optional[Callable[[float], None]] = None

    def _initialize_modules(self):
        """Lazy initialize analysis modules."""
        if self.config.enable_rppg and self._rppg_extractor is None:
            self._rppg_extractor = RPPGExtractor(
                method=self.config.rppg_method,
                fps=self.config.fps
            )
            logger.info(f"rPPG extractor initialized ({self.config.rppg_method.value})")

        if self.config.enable_eye_tracking and self._eye_tracker is None:
            self._eye_tracker = EyeTracker(fps=self.config.fps)
            logger.info("Eye tracker initialized")

        if self.config.enable_emotions and self._emotion_recognizer is None:
            self._emotion_recognizer = EmotionRecognizer(
                backend=self.config.emotion_backend,
                enable_age_gender=self.config.enable_age_gender
            )
            logger.info(f"Emotion recognizer initialized (backend={self.config.emotion_backend}, age_gender={self.config.enable_age_gender})")

        if self.config.enable_respiration and self._respiration_analyzer is None:
            self._respiration_analyzer = RespirationAnalyzer(fps=self.config.fps)
            logger.info("Respiration analyzer initialized")

    def reset(self):
        """Reset pipeline state."""
        self._frame_count = 0
        self._start_time = None
        self._last_rppg_signal = None

        if self._rppg_extractor:
            self._rppg_extractor.reset()
        if self._eye_tracker:
            self._eye_tracker.reset()
        if self._emotion_recognizer:
            self._emotion_recognizer.reset()
        if self._respiration_analyzer:
            self._respiration_analyzer.reset()

    def process_frame(self, frame: np.ndarray, timestamp: float = None) -> FrameResult:
        """
        Process a single video frame.

        Args:
            frame: BGR image as numpy array.
            timestamp: Frame timestamp in seconds.

        Returns:
            FrameResult with all analysis data.
        """
        start_time = time.perf_counter()

        self._initialize_modules()

        if self._start_time is None:
            self._start_time = time.time()

        if timestamp is None:
            timestamp = self._frame_count / self.config.fps

        self._frame_count += 1

        # Create result object
        result = FrameResult(timestamp=timestamp)

        # Face detection
        landmarks = self._face_detector.detect(frame)

        if landmarks is None:
            result.processing_time_ms = (time.perf_counter() - start_time) * 1000
            return result

        result.face_detected = True
        result.landmarks = landmarks

        # Head pose
        h, w = frame.shape[:2]
        result.head_pose = self._face_detector.get_head_pose(landmarks, (h, w))

        # rPPG analysis
        if self.config.enable_rppg and self._rppg_extractor:
            rois = self._roi_extractor.extract_all_rppg_rois(frame, landmarks)
            if self._rppg_extractor.process_frame(rois, timestamp):
                result.rppg = self._rppg_extractor.get_result()
                if result.rppg and result.rppg.rppg_signal is not None:
                    self._last_rppg_signal = result.rppg.rppg_signal[-1]

        # Eye tracking
        if self.config.enable_eye_tracking and self._eye_tracker:
            result.eye_tracking = self._eye_tracker.process(landmarks, (h, w), timestamp)

        # Emotion recognition
        if self.config.enable_emotions and self._emotion_recognizer:
            result.emotions = self._emotion_recognizer.process(frame, timestamp)

        # Respiration analysis
        if self.config.enable_respiration and self._respiration_analyzer:
            # Use rPPG signal if available
            rppg_val = self._last_rppg_signal
            resp_result = self._respiration_analyzer.process_frame(
                frame, None, rppg_val, timestamp
            )
            if resp_result:
                result.respiration = resp_result

        # Render overlay
        if self.config.enable_overlay:
            result.frame_with_overlay = self._render_overlay(frame.copy(), result)

        result.processing_time_ms = (time.perf_counter() - start_time) * 1000

        return result

    def _render_overlay(self, frame: np.ndarray, result: FrameResult) -> np.ndarray:
        """Render analysis overlay on frame."""
        if not result.face_detected or result.landmarks is None:
            return frame

        landmarks = result.landmarks

        # Draw face mesh (subset of points)
        key_indices = list(range(0, 468, 10))  # Every 10th point
        frame = self._overlay_renderer.draw_face_landmarks(
            frame, landmarks.landmarks, key_indices
        )

        # Draw ROIs
        for roi in self._roi_extractor.extract_all_rppg_rois(frame, landmarks):
            frame = self._overlay_renderer.draw_roi(
                frame, roi.x, roi.y, roi.width, roi.height, roi.name
            )

        # Head pose axes
        if result.head_pose:
            nose_point = tuple(landmarks.landmarks[1][:2].astype(int))
            frame = self._overlay_renderer.draw_head_pose_axes(
                frame, nose_point, result.head_pose
            )

        # Eye tracking overlays
        if result.eye_tracking:
            # Pupil centers
            frame = self._overlay_renderer.draw_iris_center(
                frame, result.eye_tracking.pupil.left_center
            )
            frame = self._overlay_renderer.draw_iris_center(
                frame, result.eye_tracking.pupil.right_center
            )

            # Blink indicator
            frame = self._overlay_renderer.draw_blink_indicator(
                frame, result.eye_tracking.blink.is_blinking
            )

        # Metrics overlay
        metrics = {}
        if result.rppg:
            metrics['HR'] = f"{result.rppg.heart_rate:.0f} bpm"
            metrics['SpO2'] = f"{result.rppg.spo2:.0f}%"

        if result.respiration:
            metrics['RR'] = f"{result.respiration.respiratory_rate:.0f}/min"

        if result.eye_tracking:
            metrics['Blinks'] = f"{result.eye_tracking.blink.blink_rate:.0f}/min"

        if metrics:
            frame = self._overlay_renderer.draw_metrics_overlay(frame, metrics)

        # Emotion bars
        if result.emotions:
            emotions_dict = result.emotions.get_emotions_dict()
            frame = self._overlay_renderer.draw_emotion_bars(
                frame, emotions_dict, position=(10, 200)
            )

        return frame

    def process_video(self, video_path: str,
                     output_path: str = None,
                     progress_callback: Callable[[float], None] = None) -> List[FrameResult]:
        """
        Process an entire video file.

        Args:
            video_path: Path to input video.
            output_path: Optional path for output video with overlay.
            progress_callback: Optional callback for progress updates.

        Returns:
            List of FrameResult objects.
        """
        import cv2

        self._progress_callback = progress_callback

        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            raise ValueError(f"Could not open video: {video_path}")

        # Get video properties
        fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

        # Update config FPS
        self.config.fps = fps
        self.reset()

        logger.info(f"Processing video: {video_path}")
        logger.info(f"  Resolution: {width}x{height}")
        logger.info(f"  FPS: {fps}")
        logger.info(f"  Frames: {total_frames}")

        # Setup output video writer
        writer = None
        if output_path and self.config.enable_overlay:
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            writer = cv2.VideoWriter(output_path, fourcc, fps, (width, height))

        results = []
        frame_idx = 0

        while True:
            ret, frame = cap.read()
            if not ret:
                break

            timestamp = frame_idx / fps
            result = self.process_frame(frame, timestamp)
            results.append(result)

            # Write output frame
            if writer and result.frame_with_overlay is not None:
                writer.write(result.frame_with_overlay)

            # Progress callback
            if progress_callback and frame_idx % 30 == 0:
                progress = (frame_idx + 1) / total_frames
                progress_callback(progress)

            frame_idx += 1

        cap.release()
        if writer:
            writer.release()

        logger.info(f"Processed {len(results)} frames")

        return results

    def get_chart_configs(self) -> List[Dict]:
        """Get chart configurations for frontend."""
        charts = []

        if self.config.enable_rppg:
            charts.append(ChartData.create_heart_rate_chart().to_dict())
            charts.append(ChartData.create_hrv_chart().to_dict())
            charts.append(ChartData.create_rppg_waveform_chart().to_dict())

        if self.config.enable_respiration:
            charts.append(ChartData.create_respiration_chart().to_dict())

        if self.config.enable_eye_tracking:
            charts.append(ChartData.create_gaze_chart().to_dict())
            charts.append(ChartData.create_pupil_chart().to_dict())
            charts.append(ChartData.create_blink_chart().to_dict())

        if self.config.enable_emotions:
            charts.append(ChartData.create_emotion_chart().to_dict())

        charts.append(ChartData.create_head_pose_chart().to_dict())

        return charts

    def close(self):
        """Release resources."""
        self._face_detector.close()
