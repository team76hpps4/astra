import numpy as np
import math

class CUSUMDetector:
    def __init__(self, win=4096, baseline_windows=3, k=0.5, h=6.0, adaptive_baseline=False, ema_alpha=0.01):
        self.win = win
        self.baseline_windows = baseline_windows
        self.k = k
        self.h = h
        self.adaptive_baseline = adaptive_baseline
        self.ema_alpha = ema_alpha
        self.baseline_mean = 0.0
        self.baseline_count = 0
        self.s = 0.0
        self.windows_processed = 0

        self.cusum_flags = []


    def clear_flags(self):
        flags = self.cusum_flags.copy()

        self.cusum_flags.clear()
        return flags


    def windowed_db_power(self, samples: np.ndarray) -> float:
        power = np.mean(np.abs(samples) ** 2)
        return 10.0 * math.log10(power + 1e-12)

    def predict(self, iq: np.ndarray):
        if iq.shape[0] != self.win:
            raise ValueError("Input must be length 4096 np.complex64 array")

        db = self.windowed_db_power(iq)

        if self.baseline_count < self.baseline_windows:
            self.baseline_count += 1
            self.baseline_mean += (db - self.baseline_mean) / self.baseline_count
            self.s = 0.0
            detect = 0
        else:
            y = db - self.baseline_mean
            self.s = max(0.0, self.s + (y - self.k))
            detect = int(self.s > self.h)
            if self.adaptive_baseline:
                self.baseline_mean = self.ema_alpha * db + (1.0 - self.ema_alpha) * self.baseline_mean
            if detect:
                self.s = 0.0

        self.windows_processed += 1
        self.cusum_flags.append(detect)