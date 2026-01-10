"""
Respiration analysis module.
Extracts respiratory rate and patterns from video.

Methods:
1. Chest/shoulder movement (optical flow)
2. rPPG low-frequency component
3. Face color variation (subtle)
"""
import logging
from dataclasses import dataclass
from typing import Optional, List, Tuple, Dict, Any
from collections import deque
import numpy as np

from .utils.signal_processing import SignalProcessor

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
class RespirationResult:
    """Respiration analysis result."""
    respiratory_rate: float  # Breaths per minute
    amplitude: float  # Relative amplitude (0-1)
    pattern: str  # 'regular', 'irregular', 'shallow', 'deep'
    phase: str  # 'inhale', 'exhale', 'pause'
    confidence: float
    timestamp: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            'respiratory_rate': round(self.respiratory_rate, 1),
            'amplitude': round(self.amplitude, 2),
            'pattern': self.pattern,
            'phase': self.phase,
            'confidence': round(self.confidence, 2),
            'timestamp': self.timestamp
        }


class RespirationAnalyzer:
    """
    Analyze respiration from video.

    Uses multiple methods:
    1. Optical flow on chest/shoulder region
    2. Low-frequency component of rPPG signal
    3. Face color intensity variations
    """

    # Normal respiration range
    MIN_RR = 6.0   # 6 breaths/min (slow)
    MAX_RR = 30.0  # 30 breaths/min (fast)

    def __init__(self,
                 fps: float = 30.0,
                 window_seconds: float = 30.0,
                 method: str = 'optical_flow'):
        """
        Initialize respiration analyzer.

        Args:
            fps: Video frame rate.
            window_seconds: Analysis window in seconds.
            method: Analysis method ('optical_flow', 'rppg', 'combined').
        """
        self.fps = fps
        self.window_size = int(window_seconds * fps)
        self.method = method

        self._signal_processor = SignalProcessor(fps)
        self._prev_frame = None
        self._flow_buffer: deque = deque(maxlen=self.window_size)
        self._rppg_buffer: deque = deque(maxlen=self.window_size)
        self._timestamps: deque = deque(maxlen=self.window_size)
        self._frame_count = 0

        # Optical flow parameters
        self._optical_flow = None

    def reset(self):
        """Reset analyzer state."""
        self._prev_frame = None
        self._flow_buffer.clear()
        self._rppg_buffer.clear()
        self._timestamps.clear()
        self._frame_count = 0

    def process_frame(self,
                     frame: np.ndarray,
                     chest_roi: Optional[Tuple[int, int, int, int]] = None,
                     rppg_signal: Optional[float] = None,
                     timestamp: float = None) -> Optional[RespirationResult]:
        """
        Process a frame for respiration analysis.

        Args:
            frame: BGR image.
            chest_roi: Optional (x, y, w, h) for chest region.
            rppg_signal: Optional current rPPG signal value.
            timestamp: Frame timestamp.

        Returns:
            RespirationResult if enough data collected, None otherwise.
        """
        import cv2

        if timestamp is None:
            timestamp = self._frame_count / self.fps
        self._frame_count += 1
        self._timestamps.append(timestamp)

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        # Store rPPG signal if provided
        if rppg_signal is not None:
            self._rppg_buffer.append(rppg_signal)

        # Optical flow analysis
        if self._prev_frame is not None and chest_roi is not None:
            flow_value = self._calculate_chest_movement(gray, chest_roi)
            self._flow_buffer.append(flow_value)
        elif self._prev_frame is not None:
            # Use full frame if no ROI
            h, w = gray.shape
            # Use lower third of frame as approximation
            default_roi = (0, int(h * 0.6), w, int(h * 0.4))
            flow_value = self._calculate_chest_movement(gray, default_roi)
            self._flow_buffer.append(flow_value)

        self._prev_frame = gray.copy()

        # Check if we have enough data
        if len(self._flow_buffer) >= self.window_size * 0.8:
            return self._analyze()

        return None

    def _calculate_chest_movement(self, gray: np.ndarray,
                                  roi: Tuple[int, int, int, int]) -> float:
        """Calculate vertical movement in chest ROI using optical flow."""
        import cv2

        x, y, w, h = roi

        # Ensure ROI is within bounds
        h_frame, w_frame = gray.shape
        x = max(0, min(x, w_frame - 1))
        y = max(0, min(y, h_frame - 1))
        w = min(w, w_frame - x)
        h = min(h, h_frame - y)

        if w <= 0 or h <= 0:
            return 0.0

        # Current and previous ROI
        current_roi = gray[y:y+h, x:x+w]
        prev_roi = self._prev_frame[y:y+h, x:x+w]

        # Calculate optical flow
        flow = cv2.calcOpticalFlowFarneback(
            prev_roi, current_roi,
            None, 0.5, 3, 15, 3, 5, 1.2, 0
        )

        # Get vertical component (index 1)
        vertical_flow = flow[:, :, 1]

        # Average vertical movement
        return float(np.mean(vertical_flow))

    def _analyze(self) -> RespirationResult:
        """Analyze buffered data for respiratory rate."""
        # Choose signal based on method
        if self.method == 'rppg' and len(self._rppg_buffer) > 0:
            signal = np.array(self._rppg_buffer)
        elif self.method == 'combined' and len(self._rppg_buffer) > 0:
            # Combine optical flow and rPPG
            flow_signal = np.array(self._flow_buffer)
            rppg_signal = np.array(self._rppg_buffer)

            # Interpolate to same length if needed
            if len(flow_signal) != len(rppg_signal):
                min_len = min(len(flow_signal), len(rppg_signal))
                flow_signal = flow_signal[-min_len:]
                rppg_signal = rppg_signal[-min_len:]

            # Normalize and combine
            flow_norm = self._signal_processor.normalize(flow_signal)
            rppg_norm = self._signal_processor.normalize(rppg_signal)
            signal = (flow_norm + rppg_norm) / 2
        else:
            signal = np.array(self._flow_buffer)

        # Extract respiratory rate
        rr = self._signal_processor.extract_respiratory_rate(
            signal, self.MIN_RR, self.MAX_RR
        )

        # Calculate amplitude
        filtered = self._signal_processor.filter.filter(
            signal, self.MIN_RR / 60, self.MAX_RR / 60
        )
        amplitude = np.std(filtered)

        # Normalize amplitude
        amplitude = np.clip(amplitude / (np.max(np.abs(filtered)) + 1e-6), 0, 1)

        # Determine pattern
        pattern = self._classify_pattern(filtered, rr)

        # Determine current phase
        phase = self._determine_phase(filtered)

        # Calculate confidence
        confidence = self._calculate_confidence(signal, rr)

        return RespirationResult(
            respiratory_rate=rr,
            amplitude=float(amplitude),
            pattern=pattern,
            phase=phase,
            confidence=confidence,
            timestamp=float(self._timestamps[-1]) if self._timestamps else 0.0
        )

    def _classify_pattern(self, signal: np.ndarray, rr: float) -> str:
        """Classify respiration pattern."""
        # Calculate variability
        peaks = self._signal_processor.find_peaks(signal, min_distance=int(self.fps * 60 / rr / 2))

        if len(peaks) < 3:
            return 'unknown'

        # Inter-breath intervals
        ibi = np.diff(peaks)
        ibi_std = np.std(ibi) / (np.mean(ibi) + 1e-6)

        # Amplitude variability
        peak_heights = signal[peaks]
        amp_std = np.std(peak_heights) / (np.mean(np.abs(peak_heights)) + 1e-6)

        # Classify
        if ibi_std > 0.3 or amp_std > 0.5:
            return 'irregular'
        elif np.mean(np.abs(peak_heights)) < np.std(signal) * 0.5:
            return 'shallow'
        elif np.mean(np.abs(peak_heights)) > np.std(signal) * 1.5:
            return 'deep'
        else:
            return 'regular'

    def _determine_phase(self, signal: np.ndarray) -> str:
        """Determine current respiratory phase."""
        if len(signal) < 10:
            return 'unknown'

        # Use last few samples to determine trend
        recent = signal[-10:]
        derivative = np.diff(recent)

        avg_derivative = np.mean(derivative)
        threshold = np.std(signal) * 0.1

        if avg_derivative > threshold:
            return 'inhale'
        elif avg_derivative < -threshold:
            return 'exhale'
        else:
            return 'pause'

    def _calculate_confidence(self, signal: np.ndarray, rr: float) -> float:
        """Calculate signal quality confidence."""
        # FFT for SNR
        n = len(signal)
        fft = np.fft.rfft(signal * np.hanning(n))
        freqs = np.fft.rfftfreq(n, 1.0 / self.fps)
        power = np.abs(fft) ** 2

        # Power in respiratory band
        rr_freq = rr / 60.0
        resp_mask = (freqs >= rr_freq - 0.05) & (freqs <= rr_freq + 0.05)
        noise_mask = ~resp_mask

        signal_power = np.mean(power[resp_mask]) if np.any(resp_mask) else 0
        noise_power = np.mean(power[noise_mask]) if np.any(noise_mask) else 1

        snr = signal_power / (noise_power + 1e-6)
        snr_db = 10 * np.log10(snr + 1e-6)

        # Map to confidence
        confidence = np.clip((snr_db + 5) / 15, 0, 1)

        return float(confidence)


class ApneaDetector:
    """
    Detect respiratory pauses (apnea) for sleep studies.

    An apnea event is typically defined as a cessation of breathing
    for >= 10 seconds.
    """

    def __init__(self, fps: float = 30.0, min_pause_seconds: float = 10.0):
        """
        Initialize apnea detector.

        Args:
            fps: Video frame rate.
            min_pause_seconds: Minimum duration to classify as apnea.
        """
        self.fps = fps
        self.min_pause_frames = int(min_pause_seconds * fps)

        self._amplitude_history: deque = deque(maxlen=int(60 * fps))
        self._baseline_amplitude: float = 1.0
        self._low_amplitude_start: Optional[int] = None
        self._frame_count = 0
        self._apnea_events: List[Dict] = []

    def process(self, respiration_result: RespirationResult) -> Optional[Dict]:
        """
        Check for apnea event.

        Args:
            respiration_result: Current respiration analysis.

        Returns:
            Apnea event info if detected, None otherwise.
        """
        self._frame_count += 1
        self._amplitude_history.append(respiration_result.amplitude)

        # Update baseline (75th percentile of amplitude)
        if len(self._amplitude_history) >= 100:
            self._baseline_amplitude = np.percentile(list(self._amplitude_history), 75)

        # Check for low amplitude (< 20% of baseline)
        threshold = self._baseline_amplitude * 0.2

        if respiration_result.amplitude < threshold:
            if self._low_amplitude_start is None:
                self._low_amplitude_start = self._frame_count
        else:
            if self._low_amplitude_start is not None:
                duration = self._frame_count - self._low_amplitude_start

                if duration >= self.min_pause_frames:
                    event = {
                        'type': 'apnea',
                        'start_time': self._low_amplitude_start / self.fps,
                        'end_time': self._frame_count / self.fps,
                        'duration_seconds': duration / self.fps
                    }
                    self._apnea_events.append(event)
                    self._low_amplitude_start = None
                    return event

                self._low_amplitude_start = None

        return None

    def get_apnea_events(self) -> List[Dict]:
        """Get all detected apnea events."""
        return self._apnea_events.copy()

    def get_ahi(self, total_hours: float) -> float:
        """
        Calculate Apnea-Hypopnea Index (AHI).

        AHI = number of apnea events per hour of recording.

        Args:
            total_hours: Total recording duration in hours.

        Returns:
            AHI value.
        """
        if total_hours <= 0:
            return 0.0
        return len(self._apnea_events) / total_hours
