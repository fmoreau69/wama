"""
Remote Photoplethysmography (rPPG) module.
Extracts cardiovascular signals from facial video.

Supported methods:
- GREEN: Simple green channel averaging
- CHROM: Chrominance-based method (De Haan & Jeanne, 2013)
- POS: Plane-Orthogonal-to-Skin (Wang et al., 2017)
"""
import logging
from dataclasses import dataclass
from typing import Optional, List, Tuple, Dict, Any
from enum import Enum
import numpy as np

from .utils.preprocessing import FaceLandmarks, ROI
from .utils.signal_processing import SignalProcessor, HRVMetrics, SpO2Estimator

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


class RPPGMethod(Enum):
    """Available rPPG extraction methods."""
    GREEN = "green"
    CHROM = "chrom"
    POS = "pos"


@dataclass
class RPPGResult:
    """Result of rPPG analysis for a single frame or window."""
    heart_rate: float  # BPM
    respiratory_rate: float  # Breaths/min
    spo2: float  # % (estimated)
    hrv: Optional[HRVMetrics] = None
    rppg_signal: Optional[np.ndarray] = None
    confidence: float = 0.0
    timestamp: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        result = {
            'heart_rate': round(self.heart_rate, 1),
            'respiratory_rate': round(self.respiratory_rate, 1),
            'spo2': round(self.spo2, 1),
            'confidence': round(self.confidence, 2),
            'timestamp': self.timestamp
        }
        if self.hrv:
            result['hrv'] = self.hrv.to_dict()
        return result


class RPPGExtractor:
    """
    Extract cardiovascular signals from facial video using rPPG.

    Usage:
        extractor = RPPGExtractor(method=RPPGMethod.CHROM, fps=30)
        for frame, landmarks in video_stream:
            extractor.process_frame(frame, landmarks)
            if extractor.has_result():
                result = extractor.get_result()
    """

    def __init__(self,
                 method: RPPGMethod = RPPGMethod.CHROM,
                 fps: float = 30.0,
                 window_seconds: float = 10.0,
                 step_seconds: float = 1.0):
        """
        Initialize the rPPG extractor.

        Args:
            method: rPPG extraction method.
            fps: Video frame rate.
            window_seconds: Analysis window size in seconds.
            step_seconds: Step size for sliding window in seconds.
        """
        self.method = method
        self.fps = fps
        self.window_size = int(window_seconds * fps)
        self.step_size = int(step_seconds * fps)

        self._signal_processor = SignalProcessor(fps)
        self._spo2_estimator = SpO2Estimator()

        # Buffers for RGB signals
        self._rgb_buffer: List[np.ndarray] = []  # List of [R, G, B] means
        self._timestamps: List[float] = []
        self._frame_count = 0
        self._last_result: Optional[RPPGResult] = None

    def reset(self):
        """Reset the extractor state."""
        self._rgb_buffer.clear()
        self._timestamps.clear()
        self._frame_count = 0
        self._last_result = None

    def process_frame(self, rois: List[ROI], timestamp: float = None) -> bool:
        """
        Process a single frame.

        Args:
            rois: List of ROIs (forehead, cheeks) to analyze.
            timestamp: Frame timestamp in seconds.

        Returns:
            True if a new result is available.
        """
        if not rois or all(roi.pixels is None for roi in rois):
            return False

        # Calculate mean RGB for each ROI and average
        rgb_means = []
        for roi in rois:
            if roi.pixels is not None and roi.pixels.size > 0:
                mean_rgb = np.mean(roi.pixels, axis=(0, 1))
                if len(mean_rgb) >= 3:
                    rgb_means.append(mean_rgb[:3])  # BGR -> take first 3

        if not rgb_means:
            return False

        # Average across ROIs
        mean_rgb = np.mean(rgb_means, axis=0)

        # Add to buffer
        self._rgb_buffer.append(mean_rgb)
        self._timestamps.append(timestamp if timestamp else self._frame_count / self.fps)
        self._frame_count += 1

        # Check if we have enough data for analysis
        if len(self._rgb_buffer) >= self.window_size:
            self._analyze()

            # Slide window
            self._rgb_buffer = self._rgb_buffer[self.step_size:]
            self._timestamps = self._timestamps[self.step_size:]
            return True

        return False

    def _analyze(self):
        """Perform rPPG analysis on buffered data."""
        rgb_array = np.array(self._rgb_buffer)

        # Extract rPPG signal based on method
        if self.method == RPPGMethod.GREEN:
            rppg_signal = self._extract_green(rgb_array)
        elif self.method == RPPGMethod.CHROM:
            rppg_signal = self._extract_chrom(rgb_array)
        elif self.method == RPPGMethod.POS:
            rppg_signal = self._extract_pos(rgb_array)
        else:
            rppg_signal = self._extract_green(rgb_array)

        # Normalize signal
        rppg_signal = self._signal_processor.normalize(rppg_signal)

        # Extract heart rate
        heart_rate, power_spectrum = self._signal_processor.extract_heart_rate(rppg_signal)

        # Extract respiratory rate
        respiratory_rate = self._signal_processor.extract_respiratory_rate(rppg_signal)

        # Find peaks for HRV
        filtered = self._signal_processor.filter.filter(rppg_signal, 0.7, 3.0)
        peaks = self._signal_processor.find_peaks(filtered)
        hrv = self._signal_processor.calculate_hrv(peaks)

        # Estimate SpO2 (using red and green channels)
        red_signal = rgb_array[:, 2]  # BGR format, so index 2 is red
        green_signal = rgb_array[:, 1]  # Green as IR approximation
        spo2 = self._spo2_estimator.estimate(red_signal, green_signal)

        # Calculate signal quality/confidence
        confidence = self._calculate_confidence(rppg_signal, power_spectrum, heart_rate)

        self._last_result = RPPGResult(
            heart_rate=heart_rate,
            respiratory_rate=respiratory_rate,
            spo2=spo2,
            hrv=hrv,
            rppg_signal=rppg_signal,
            confidence=confidence,
            timestamp=self._timestamps[-1]
        )

    def _extract_green(self, rgb_array: np.ndarray) -> np.ndarray:
        """
        Simple green channel method.
        Fast but sensitive to motion artifacts.
        """
        # Green channel (index 1 in BGR)
        return rgb_array[:, 1]

    def _extract_chrom(self, rgb_array: np.ndarray) -> np.ndarray:
        """
        CHROM method (De Haan & Jeanne, 2013).
        More robust to motion than green channel.
        """
        # Normalize by mean
        rgb_norm = rgb_array / (np.mean(rgb_array, axis=0) + 1e-6)

        # X and Y chrominance signals
        X = 3 * rgb_norm[:, 2] - 2 * rgb_norm[:, 1]  # 3R - 2G
        Y = 1.5 * rgb_norm[:, 2] + rgb_norm[:, 1] - 1.5 * rgb_norm[:, 0]  # 1.5R + G - 1.5B

        # Bandpass filter
        X = self._signal_processor.filter.filter(X, 0.7, 3.0)
        Y = self._signal_processor.filter.filter(Y, 0.7, 3.0)

        # Combine with alpha
        std_X = np.std(X)
        std_Y = np.std(Y)
        alpha = std_X / (std_Y + 1e-6)

        return X - alpha * Y

    def _extract_pos(self, rgb_array: np.ndarray) -> np.ndarray:
        """
        POS method (Wang et al., 2017).
        Plane-Orthogonal-to-Skin projection.
        """
        # Normalize RGB
        rgb_norm = rgb_array / (np.mean(rgb_array, axis=0) + 1e-6)

        # Projection matrix for skin tone
        # P = [0, 1, -1; -2, 1, 1]
        S1 = rgb_norm[:, 1] - rgb_norm[:, 0]  # G - B
        S2 = -2 * rgb_norm[:, 2] + rgb_norm[:, 1] + rgb_norm[:, 0]  # -2R + G + B

        # Bandpass filter
        S1 = self._signal_processor.filter.filter(S1, 0.7, 3.0)
        S2 = self._signal_processor.filter.filter(S2, 0.7, 3.0)

        # Optimal linear combination
        std_S1 = np.std(S1)
        std_S2 = np.std(S2)
        alpha = std_S1 / (std_S2 + 1e-6)

        return S1 + alpha * S2

    def _calculate_confidence(self, signal: np.ndarray, power: np.ndarray,
                             hr: float) -> float:
        """Calculate signal quality confidence score."""
        # Signal-to-noise ratio in cardiac band
        n = len(signal)
        freqs = np.fft.rfftfreq(n, 1.0 / self.fps)

        hr_freq = hr / 60.0
        cardiac_mask = (freqs >= hr_freq - 0.2) & (freqs <= hr_freq + 0.2)
        noise_mask = ~cardiac_mask

        signal_power = np.mean(power[cardiac_mask]) if np.any(cardiac_mask) else 0
        noise_power = np.mean(power[noise_mask]) if np.any(noise_mask) else 1

        snr = signal_power / (noise_power + 1e-6)
        snr_db = 10 * np.log10(snr + 1e-6)

        # Map SNR to confidence (0-1)
        # SNR > 10 dB = high confidence, < 0 dB = low confidence
        confidence = np.clip((snr_db + 5) / 15, 0, 1)

        return float(confidence)

    def has_result(self) -> bool:
        """Check if a result is available."""
        return self._last_result is not None

    def get_result(self) -> Optional[RPPGResult]:
        """Get the latest analysis result."""
        return self._last_result

    def get_buffer_fill(self) -> float:
        """Get buffer fill percentage (0-1)."""
        return len(self._rgb_buffer) / self.window_size
