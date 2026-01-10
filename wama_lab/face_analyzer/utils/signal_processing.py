"""
Signal processing utilities for physiological signal analysis.
Provides filtering, FFT, peak detection, and HRV metrics.
"""
import logging
from dataclasses import dataclass
from typing import Optional, Tuple, List, Dict, Any
import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class HRVMetrics:
    """Heart Rate Variability metrics."""
    sdnn: float  # Standard deviation of NN intervals (ms)
    rmssd: float  # Root mean square of successive differences (ms)
    pnn50: float  # Percentage of successive differences > 50ms
    mean_hr: float  # Mean heart rate (bpm)
    min_hr: float  # Minimum heart rate (bpm)
    max_hr: float  # Maximum heart rate (bpm)

    def to_dict(self) -> Dict[str, float]:
        return {
            'sdnn': round(self.sdnn, 2),
            'rmssd': round(self.rmssd, 2),
            'pnn50': round(self.pnn50, 2),
            'mean_hr': round(self.mean_hr, 1),
            'min_hr': round(self.min_hr, 1),
            'max_hr': round(self.max_hr, 1)
        }


class BandpassFilter:
    """
    Bandpass filter for physiological signals.
    Uses Butterworth filter design.
    """

    def __init__(self, fs: float, order: int = 4):
        """
        Initialize the filter.

        Args:
            fs: Sampling frequency in Hz.
            order: Filter order.
        """
        self.fs = fs
        self.order = order

    def filter(self, signal: np.ndarray, lowcut: float, highcut: float) -> np.ndarray:
        """
        Apply bandpass filter to signal.

        Args:
            signal: Input signal.
            lowcut: Low cutoff frequency in Hz.
            highcut: High cutoff frequency in Hz.

        Returns:
            Filtered signal.
        """
        from scipy.signal import butter, filtfilt

        nyq = 0.5 * self.fs
        low = lowcut / nyq
        high = highcut / nyq

        # Ensure valid frequency range
        low = max(0.01, min(low, 0.99))
        high = max(low + 0.01, min(high, 0.99))

        b, a = butter(self.order, [low, high], btype='band')
        return filtfilt(b, a, signal)

    def lowpass(self, signal: np.ndarray, cutoff: float) -> np.ndarray:
        """Apply lowpass filter."""
        from scipy.signal import butter, filtfilt

        nyq = 0.5 * self.fs
        normalized_cutoff = min(cutoff / nyq, 0.99)
        b, a = butter(self.order, normalized_cutoff, btype='low')
        return filtfilt(b, a, signal)

    def highpass(self, signal: np.ndarray, cutoff: float) -> np.ndarray:
        """Apply highpass filter."""
        from scipy.signal import butter, filtfilt

        nyq = 0.5 * self.fs
        normalized_cutoff = max(cutoff / nyq, 0.01)
        b, a = butter(self.order, normalized_cutoff, btype='high')
        return filtfilt(b, a, signal)


class SignalProcessor:
    """
    Signal processing utilities for physiological signals.
    """

    def __init__(self, fs: float):
        """
        Initialize the processor.

        Args:
            fs: Sampling frequency in Hz.
        """
        self.fs = fs
        self.filter = BandpassFilter(fs)

    def extract_heart_rate(self,
                           signal: np.ndarray,
                           min_hr: float = 40.0,
                           max_hr: float = 180.0) -> Tuple[float, np.ndarray]:
        """
        Extract heart rate from rPPG signal using FFT.

        Args:
            signal: rPPG signal.
            min_hr: Minimum expected heart rate in bpm.
            max_hr: Maximum expected heart rate in bpm.

        Returns:
            Tuple of (heart_rate_bpm, power_spectrum).
        """
        # Detrend signal
        signal = self.detrend(signal)

        # Bandpass filter for cardiac band (0.7-3 Hz = 40-180 bpm)
        min_freq = min_hr / 60.0
        max_freq = max_hr / 60.0
        filtered = self.filter.filter(signal, min_freq, max_freq)

        # Apply window
        windowed = filtered * np.hanning(len(filtered))

        # FFT
        n = len(windowed)
        fft = np.fft.rfft(windowed)
        freqs = np.fft.rfftfreq(n, 1.0 / self.fs)
        power = np.abs(fft) ** 2

        # Find peak in cardiac band
        cardiac_mask = (freqs >= min_freq) & (freqs <= max_freq)
        cardiac_power = power.copy()
        cardiac_power[~cardiac_mask] = 0

        peak_idx = np.argmax(cardiac_power)
        peak_freq = freqs[peak_idx]
        heart_rate = peak_freq * 60.0

        return heart_rate, power

    def extract_respiratory_rate(self,
                                 signal: np.ndarray,
                                 min_rr: float = 6.0,
                                 max_rr: float = 30.0) -> float:
        """
        Extract respiratory rate from signal.

        Args:
            signal: Input signal (can be rPPG or optical flow based).
            min_rr: Minimum expected respiratory rate (breaths/min).
            max_rr: Maximum expected respiratory rate (breaths/min).

        Returns:
            Respiratory rate in breaths per minute.
        """
        # Detrend
        signal = self.detrend(signal)

        # Filter for respiratory band (0.1-0.5 Hz = 6-30 breaths/min)
        min_freq = min_rr / 60.0
        max_freq = max_rr / 60.0
        filtered = self.filter.filter(signal, min_freq, max_freq)

        # FFT
        n = len(filtered)
        fft = np.fft.rfft(filtered * np.hanning(n))
        freqs = np.fft.rfftfreq(n, 1.0 / self.fs)
        power = np.abs(fft) ** 2

        # Find peak
        resp_mask = (freqs >= min_freq) & (freqs <= max_freq)
        resp_power = power.copy()
        resp_power[~resp_mask] = 0

        peak_idx = np.argmax(resp_power)
        peak_freq = freqs[peak_idx]

        return peak_freq * 60.0

    def find_peaks(self,
                   signal: np.ndarray,
                   min_distance: int = None,
                   height: float = None) -> np.ndarray:
        """
        Find peaks in signal.

        Args:
            signal: Input signal.
            min_distance: Minimum distance between peaks in samples.
            height: Minimum peak height.

        Returns:
            Array of peak indices.
        """
        from scipy.signal import find_peaks as scipy_find_peaks

        if min_distance is None:
            # Default: assume 40-180 bpm, so min distance = 60/180 * fs
            min_distance = int(self.fs * 0.33)

        peaks, _ = scipy_find_peaks(signal, distance=min_distance, height=height)
        return peaks

    def calculate_hrv(self, peak_indices: np.ndarray) -> Optional[HRVMetrics]:
        """
        Calculate HRV metrics from R-peak indices.

        Args:
            peak_indices: Indices of detected peaks.

        Returns:
            HRVMetrics object or None if insufficient peaks.
        """
        if len(peak_indices) < 3:
            return None

        # Calculate RR intervals in ms
        rr_intervals = np.diff(peak_indices) / self.fs * 1000

        # Filter out physiologically impossible intervals
        valid_mask = (rr_intervals > 300) & (rr_intervals < 2000)  # 30-200 bpm
        rr_intervals = rr_intervals[valid_mask]

        if len(rr_intervals) < 2:
            return None

        # Calculate metrics
        sdnn = float(np.std(rr_intervals))
        mean_rr = float(np.mean(rr_intervals))

        # Successive differences
        diff_rr = np.diff(rr_intervals)
        rmssd = float(np.sqrt(np.mean(diff_rr ** 2)))
        pnn50 = float(np.sum(np.abs(diff_rr) > 50) / len(diff_rr) * 100)

        # Heart rate stats
        hr = 60000 / rr_intervals
        mean_hr = float(np.mean(hr))
        min_hr = float(np.min(hr))
        max_hr = float(np.max(hr))

        return HRVMetrics(
            sdnn=sdnn,
            rmssd=rmssd,
            pnn50=pnn50,
            mean_hr=mean_hr,
            min_hr=min_hr,
            max_hr=max_hr
        )

    def detrend(self, signal: np.ndarray) -> np.ndarray:
        """Remove linear trend from signal."""
        from scipy.signal import detrend
        return detrend(signal)

    def normalize(self, signal: np.ndarray) -> np.ndarray:
        """Normalize signal to zero mean and unit variance."""
        mean = np.mean(signal)
        std = np.std(signal)
        if std == 0:
            return signal - mean
        return (signal - mean) / std

    def moving_average(self, signal: np.ndarray, window_size: int) -> np.ndarray:
        """Apply moving average smoothing."""
        kernel = np.ones(window_size) / window_size
        return np.convolve(signal, kernel, mode='same')

    def interpolate_signal(self, signal: np.ndarray, timestamps: np.ndarray,
                          new_fs: float) -> Tuple[np.ndarray, np.ndarray]:
        """
        Resample signal to uniform sampling rate.

        Args:
            signal: Input signal.
            timestamps: Corresponding timestamps.
            new_fs: New sampling frequency.

        Returns:
            Tuple of (resampled_signal, new_timestamps).
        """
        from scipy.interpolate import interp1d

        duration = timestamps[-1] - timestamps[0]
        new_n = int(duration * new_fs)
        new_timestamps = np.linspace(timestamps[0], timestamps[-1], new_n)

        f = interp1d(timestamps, signal, kind='cubic', fill_value='extrapolate')
        new_signal = f(new_timestamps)

        return new_signal, new_timestamps


class SpO2Estimator:
    """
    Blood oxygen saturation (SpO2) estimation from rPPG.
    Note: This is an approximation and not medically accurate.
    """

    def __init__(self):
        # Calibration constants (approximate)
        self.r_constant = 1.5
        self.ir_constant = 1.0

    def estimate(self, red_signal: np.ndarray, ir_signal: np.ndarray) -> float:
        """
        Estimate SpO2 from red and infrared PPG signals.

        In webcam-based rPPG, we approximate:
        - Red channel as red light
        - Green channel as approximation for IR

        Args:
            red_signal: PPG signal from red channel.
            ir_signal: PPG signal from green/IR channel.

        Returns:
            Estimated SpO2 percentage (typically 95-100%).
        """
        # AC/DC ratio for each channel
        red_ac = np.std(red_signal)
        red_dc = np.mean(red_signal) if np.mean(red_signal) != 0 else 1
        ir_ac = np.std(ir_signal)
        ir_dc = np.mean(ir_signal) if np.mean(ir_signal) != 0 else 1

        # Ratio of ratios
        r = (red_ac / red_dc) / (ir_ac / ir_dc)

        # Empirical formula (approximate)
        spo2 = 110 - 25 * r

        # Clamp to realistic range
        return float(np.clip(spo2, 70, 100))
