"""
Emotion recognition module.
Detects facial expressions and emotional states.

Provides:
- 7 basic emotions (Ekman)
- Valence/Arousal model
- Dominant emotion detection
- Age estimation (DeepFace only)
- Gender detection (DeepFace only)

Backends:
- FER: Lightweight, fast, emotions only
- DeepFace: Full analysis (emotions, age, gender), more accurate
"""
import logging
from dataclasses import dataclass
from typing import Optional, Dict, Any, List
from collections import deque
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
class EmotionResult:
    """Emotion analysis result."""
    # Ekman's basic emotions (probabilities 0-1)
    happy: float = 0.0
    sad: float = 0.0
    angry: float = 0.0
    fear: float = 0.0
    surprise: float = 0.0
    disgust: float = 0.0
    neutral: float = 0.0

    # Derived metrics
    dominant_emotion: str = "neutral"
    confidence: float = 0.0

    # Valence-Arousal model
    valence: float = 0.0  # -1 (negative) to 1 (positive)
    arousal: float = 0.0  # 0 (calm) to 1 (excited)

    # Demographics (DeepFace only)
    age: Optional[int] = None  # Estimated age
    gender: Optional[str] = None  # 'Man' or 'Woman'
    gender_confidence: float = 0.0  # Confidence of gender prediction

    timestamp: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        result = {
            'emotions': {
                'happy': round(self.happy, 3),
                'sad': round(self.sad, 3),
                'angry': round(self.angry, 3),
                'fear': round(self.fear, 3),
                'surprise': round(self.surprise, 3),
                'disgust': round(self.disgust, 3),
                'neutral': round(self.neutral, 3)
            },
            'dominant_emotion': self.dominant_emotion,
            'confidence': round(self.confidence, 2),
            'valence': round(self.valence, 2),
            'arousal': round(self.arousal, 2),
            'timestamp': self.timestamp
        }
        # Include demographics if available (DeepFace)
        if self.age is not None:
            result['age'] = self.age
        if self.gender is not None:
            result['gender'] = self.gender
            result['gender_confidence'] = round(self.gender_confidence, 2)
        return result

    def get_emotions_dict(self) -> Dict[str, float]:
        """Get emotions as dictionary."""
        return {
            'happy': self.happy,
            'sad': self.sad,
            'angry': self.angry,
            'fear': self.fear,
            'surprise': self.surprise,
            'disgust': self.disgust,
            'neutral': self.neutral
        }


class EmotionRecognizer:
    """
    Facial emotion recognition.

    Uses DeepFace or FER for emotion detection from facial images.
    Supports real-time analysis with temporal smoothing.

    Backends:
    - 'fer': Fast, lightweight, emotions only
    - 'deepface': Full analysis with age, gender, and better accuracy
    """

    EMOTION_LABELS = ['happy', 'sad', 'angry', 'fear', 'surprise', 'disgust', 'neutral']

    # Valence-Arousal mapping for each emotion
    EMOTION_VA = {
        'happy': (0.8, 0.6),
        'sad': (-0.6, 0.2),
        'angry': (-0.5, 0.8),
        'fear': (-0.7, 0.7),
        'surprise': (0.2, 0.8),
        'disgust': (-0.6, 0.4),
        'neutral': (0.0, 0.1)
    }

    def __init__(self,
                 backend: str = 'fer',
                 smoothing_window: int = 5,
                 min_confidence: float = 0.3,
                 enable_age_gender: bool = True,
                 deepface_detector: str = 'opencv'):
        """
        Initialize emotion recognizer.

        Args:
            backend: Detection backend ('fer', 'deepface').
            smoothing_window: Number of frames for temporal smoothing.
            min_confidence: Minimum confidence threshold.
            enable_age_gender: Enable age/gender detection (DeepFace only).
            deepface_detector: Face detector for DeepFace ('opencv', 'mtcnn', 'retinaface').
        """
        self.backend = backend
        self.smoothing_window = smoothing_window
        self.min_confidence = min_confidence
        self.enable_age_gender = enable_age_gender and backend == 'deepface'
        self.deepface_detector = deepface_detector

        self._detector = None
        self._initialized = False
        self._history: deque = deque(maxlen=smoothing_window)
        self._age_history: deque = deque(maxlen=smoothing_window)
        self._gender_history: deque = deque(maxlen=smoothing_window)
        self._frame_count = 0

    def _initialize(self):
        """Lazy initialization of detection backend."""
        if self._initialized:
            return

        try:
            if self.backend == 'fer':
                from fer import FER
                self._detector = FER(mtcnn=False)  # Use OpenCV for speed
                logger.info("FER emotion detector initialized (emotions only)")
            elif self.backend == 'deepface':
                # DeepFace is used directly without pre-initialization
                import deepface
                self._detector = 'deepface'
                actions = ['emotion']
                if self.enable_age_gender:
                    actions.extend(['age', 'gender'])
                logger.info(f"DeepFace initialized (actions: {actions}, detector: {self.deepface_detector})")
            else:
                logger.warning(f"Unknown backend: {self.backend}, using FER")
                from fer import FER
                self._detector = FER(mtcnn=False)
                self.backend = 'fer'

            self._initialized = True

        except ImportError as e:
            logger.error(f"Failed to import emotion detection library: {e}")
            logger.info("Install with: pip install fer  OR  pip install deepface")
            raise

    def reset(self):
        """Reset recognizer state."""
        self._history.clear()
        self._age_history.clear()
        self._gender_history.clear()
        self._frame_count = 0

    def process(self, frame: np.ndarray, timestamp: float = None) -> Optional[EmotionResult]:
        """
        Detect emotions in a frame.

        Args:
            frame: BGR image as numpy array.
            timestamp: Frame timestamp.

        Returns:
            EmotionResult or None if no face detected.
        """
        self._initialize()

        if timestamp is None:
            timestamp = self._frame_count / 30.0  # Assume 30 fps
        self._frame_count += 1

        # Detect emotions (and optionally age/gender)
        detection_result = self._detect_emotions(frame)

        if detection_result is None:
            return None

        emotions = detection_result.get('emotions')
        if emotions is None:
            return None

        # Add to history for smoothing
        self._history.append(emotions)

        # Track age/gender history for smoothing (DeepFace only)
        if detection_result.get('age') is not None:
            self._age_history.append(detection_result['age'])
        if detection_result.get('gender') is not None:
            self._gender_history.append(detection_result['gender'])

        # Apply temporal smoothing
        smoothed = self._smooth_emotions()

        # Calculate derived metrics
        dominant, confidence = self._get_dominant_emotion(smoothed)
        valence, arousal = self._calculate_valence_arousal(smoothed)

        # Smooth age/gender
        age = None
        gender = None
        gender_confidence = 0.0

        if self._age_history:
            age = int(np.median(list(self._age_history)))

        if self._gender_history:
            # Most common gender in history
            from collections import Counter
            gender_counts = Counter(self._gender_history)
            gender = gender_counts.most_common(1)[0][0]
            gender_confidence = gender_counts[gender] / len(self._gender_history)

        return EmotionResult(
            happy=smoothed.get('happy', 0),
            sad=smoothed.get('sad', 0),
            angry=smoothed.get('angry', 0),
            fear=smoothed.get('fear', 0),
            surprise=smoothed.get('surprise', 0),
            disgust=smoothed.get('disgust', 0),
            neutral=smoothed.get('neutral', 0),
            dominant_emotion=dominant,
            confidence=confidence,
            valence=valence,
            arousal=arousal,
            age=age,
            gender=gender,
            gender_confidence=gender_confidence,
            timestamp=timestamp
        )

    def _detect_emotions(self, frame: np.ndarray) -> Optional[Dict[str, Any]]:
        """
        Detect emotions using the configured backend.

        Returns:
            Dictionary with 'emotions', and optionally 'age', 'gender' keys.
        """
        try:
            if self.backend == 'fer' and hasattr(self._detector, 'detect_emotions'):
                results = self._detector.detect_emotions(frame)
                if results and len(results) > 0:
                    # Get the first face's emotions
                    return {'emotions': results[0]['emotions']}

            elif self.backend == 'deepface':
                try:
                    from deepface import DeepFace
                except ImportError as import_err:
                    logger.error(f"DeepFace import failed: {import_err}")
                    logger.info("Falling back to FER backend. Install with: pip install deepface tf-keras")
                    # Fallback to FER
                    self.backend = 'fer'
                    from fer import FER
                    self._detector = FER(mtcnn=False)
                    results = self._detector.detect_emotions(frame)
                    if results and len(results) > 0:
                        return {'emotions': results[0]['emotions']}
                    return None

                # Build actions list
                actions = ['emotion']
                if self.enable_age_gender:
                    actions.extend(['age', 'gender'])

                result = DeepFace.analyze(
                    frame,
                    actions=actions,
                    enforce_detection=False,
                    detector_backend=self.deepface_detector,
                    silent=True
                )

                if result:
                    if isinstance(result, list):
                        result = result[0]

                    # Extract emotions and normalize to 0-1
                    emotions = result.get('emotion', {})
                    total = sum(emotions.values())
                    if total > 0:
                        emotions = {k.lower(): v / 100.0 for k, v in emotions.items()}

                    detection = {'emotions': emotions}

                    # Extract age if available
                    if 'age' in result:
                        detection['age'] = int(result['age'])
                        logger.debug(f"DeepFace age: {detection['age']}")

                    # Extract gender if available
                    if 'gender' in result or 'dominant_gender' in result:
                        gender_data = result.get('gender', {})
                        if isinstance(gender_data, dict):
                            # Get dominant gender
                            detection['gender'] = result.get('dominant_gender', 'Unknown')
                            detection['gender_confidence'] = max(gender_data.values()) / 100.0 if gender_data else 0.0
                        else:
                            detection['gender'] = str(gender_data)
                            detection['gender_confidence'] = 1.0
                        logger.debug(f"DeepFace gender: {detection['gender']}")

                    return detection

        except Exception as e:
            logger.debug(f"Emotion detection failed: {e}")

        return None

    def _smooth_emotions(self) -> Dict[str, float]:
        """Apply temporal smoothing to emotion predictions."""
        if not self._history:
            return {e: 0.0 for e in self.EMOTION_LABELS}

        # Average over history
        smoothed = {}
        for emotion in self.EMOTION_LABELS:
            values = [h.get(emotion, 0) for h in self._history if h]
            smoothed[emotion] = np.mean(values) if values else 0.0

        # Normalize
        total = sum(smoothed.values())
        if total > 0:
            smoothed = {k: v / total for k, v in smoothed.items()}

        return smoothed

    def _get_dominant_emotion(self, emotions: Dict[str, float]) -> tuple:
        """Get the dominant emotion and its confidence."""
        if not emotions:
            return 'neutral', 0.0

        dominant = max(emotions, key=emotions.get)
        confidence = emotions[dominant]

        # If confidence is below threshold, return neutral
        if confidence < self.min_confidence:
            return 'neutral', emotions.get('neutral', 0.0)

        return dominant, confidence

    def _calculate_valence_arousal(self, emotions: Dict[str, float]) -> tuple:
        """
        Calculate valence and arousal from emotion probabilities.

        Uses weighted average based on emotion-VA mapping.
        """
        valence = 0.0
        arousal = 0.0

        for emotion, prob in emotions.items():
            if emotion in self.EMOTION_VA:
                v, a = self.EMOTION_VA[emotion]
                valence += prob * v
                arousal += prob * a

        return float(valence), float(arousal)

    def process_batch(self, frames: List[np.ndarray],
                     timestamps: List[float] = None) -> List[EmotionResult]:
        """
        Process multiple frames.

        Args:
            frames: List of BGR images.
            timestamps: Optional timestamps for each frame.

        Returns:
            List of EmotionResult objects.
        """
        results = []
        for i, frame in enumerate(frames):
            ts = timestamps[i] if timestamps else None
            result = self.process(frame, ts)
            if result:
                results.append(result)
        return results


class MicroExpressionDetector:
    """
    Detect micro-expressions (rapid, involuntary facial expressions).

    Micro-expressions typically last 1/25 to 1/5 of a second (40-200ms).
    They can indicate concealed emotions.

    Note: This is experimental and requires high frame rate video (>60 fps).
    """

    def __init__(self, fps: float = 60.0, min_duration_ms: float = 40.0,
                 max_duration_ms: float = 200.0):
        """
        Initialize micro-expression detector.

        Args:
            fps: Video frame rate (should be >= 60 for reliable detection).
            min_duration_ms: Minimum micro-expression duration.
            max_duration_ms: Maximum micro-expression duration.
        """
        self.fps = fps
        self.min_frames = int(min_duration_ms * fps / 1000)
        self.max_frames = int(max_duration_ms * fps / 1000)

        self._emotion_history: deque = deque(maxlen=30)  # ~0.5s at 60fps
        self._baseline_emotion: Optional[str] = None
        self._deviation_start: Optional[int] = None
        self._frame_count = 0

    def process(self, emotion_result: EmotionResult) -> Optional[Dict[str, Any]]:
        """
        Check for micro-expression in current frame.

        Args:
            emotion_result: Current emotion analysis result.

        Returns:
            Micro-expression info if detected, None otherwise.
        """
        self._frame_count += 1
        current_emotion = emotion_result.dominant_emotion

        # Update history
        self._emotion_history.append(current_emotion)

        # Establish baseline (most common emotion in history)
        if len(self._emotion_history) >= 10:
            from collections import Counter
            counts = Counter(self._emotion_history)
            self._baseline_emotion = counts.most_common(1)[0][0]

        if self._baseline_emotion is None:
            return None

        # Detect deviation from baseline
        if current_emotion != self._baseline_emotion:
            if self._deviation_start is None:
                self._deviation_start = self._frame_count
        else:
            if self._deviation_start is not None:
                duration = self._frame_count - self._deviation_start

                # Check if duration is within micro-expression range
                if self.min_frames <= duration <= self.max_frames:
                    # Get the deviant emotion
                    deviant_emotions = [e for e in list(self._emotion_history)[-duration:]
                                       if e != self._baseline_emotion]
                    if deviant_emotions:
                        micro_expr = max(set(deviant_emotions), key=deviant_emotions.count)
                        self._deviation_start = None
                        return {
                            'micro_expression': micro_expr,
                            'baseline_emotion': self._baseline_emotion,
                            'duration_ms': duration * 1000 / self.fps,
                            'timestamp': emotion_result.timestamp
                        }

                self._deviation_start = None

        return None
