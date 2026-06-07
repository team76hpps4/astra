import numpy as np
from collections import deque

class FrequencyAwareRFEQMFilter:
    def __init__(self, alpha_down=0.75, alpha_up=0.12, severity_scale=0.004,
                 window_size=20, frequency_penalty=0.15, spike_threshold=15):
        """
        RFEQM filter with spike frequency awareness.
        
        Args:
            alpha_down: Base drop rate (0.7-0.9)
            alpha_up: Recovery rate (0.1-0.2)
            severity_scale: Spike magnitude scaling (0.003-0.005)
            window_size: Lookback window for spike counting (10-30 samples)
            frequency_penalty: Additional alpha per spike in window (0.1-0.3)
            spike_threshold: Min RFEQM drop to count as a spike (10-20)
        """
        self.alpha_down = alpha_down
        self.alpha_up = alpha_up
        self.severity_scale = severity_scale
        self.window_size = window_size
        self.frequency_penalty = frequency_penalty
        self.spike_threshold = spike_threshold
        
        self.smoothed_value = 100.0
        self.spike_history = deque(maxlen=window_size)  
        self.raw_history = deque(maxlen=window_size)    
    
    def _count_recent_spikes(self):
        """Count number of spikes in recent history"""
        if len(self.raw_history) < 2:
            return 0
        
        spike_count = 0
        for i in range(1, len(self.raw_history)):
            delta = self.raw_history[i-1] - self.raw_history[i]
            if delta > self.spike_threshold:
                spike_count += 1
        
        return spike_count
    
    def update(self, raw_rfeqm):
        """Update filter with new measurement"""
        self.raw_history.append(raw_rfeqm)
        delta = raw_rfeqm - self.smoothed_value
        
        if delta < 0:
            spike_magnitude = abs(delta)
            
            recent_spike_count = self._count_recent_spikes()
            
            alpha = self.alpha_down + self.severity_scale * spike_magnitude
            
            frequency_boost = self.frequency_penalty * recent_spike_count
            alpha = min(0.98, alpha + frequency_boost)
            
            self.spike_history.append({
                'magnitude': spike_magnitude,
                'count': recent_spike_count
            })
        else:
            alpha = self.alpha_up
        
        self.smoothed_value = alpha * raw_rfeqm + (1 - alpha) * self.smoothed_value
        return self.smoothed_value
    
    def get_rfeqm(self):
        return self.smoothed_value
    
    def get_spike_count(self):
        """Get current spike count in window"""
        return self._count_recent_spikes()
    
    def reset(self):
        self.smoothed_value = 100.0
        self.spike_history.clear()
        self.raw_history.clear()

def frequency_aware_smoothing(rfeqm_values, alpha_down=0.75, alpha_up=0.12, 
                              severity_scale=0.004, window_size=20, 
                              frequency_penalty=0.15, spike_threshold=15):
    """
    Apply frequency-aware smoothing to entire array.
    """
    smoothed = np.zeros_like(rfeqm_values, dtype=float)
    smoothed[0] = rfeqm_values[0]
    
    for i in range(1, len(rfeqm_values)):
        delta = rfeqm_values[i] - smoothed[i-1]
        
        if delta < 0:
            spike_magnitude = abs(delta)
            
            start_idx = max(0, i - window_size)
            window = rfeqm_values[start_idx:i]
            spike_count = 0
            for j in range(1, len(window)):
                if window[j-1] - window[j] > spike_threshold:
                    spike_count += 1
            
            alpha = alpha_down + severity_scale * spike_magnitude
            frequency_boost = frequency_penalty * spike_count
            alpha = min(0.98, alpha + frequency_boost)
        else:
            alpha = alpha_up
        
        smoothed[i] = alpha * rfeqm_values[i] + (1 - alpha) * smoothed[i-1]
    
    return smoothed
