import copy
import logging

logger = logging.getLogger("RollbackManager")

class RollbackManager:
    def __init__(self, thresholds):
        """
        thresholds: dict {'max_retry_rate': 25.0, 'min_throughput': 2.0}
        """
        self.thresholds = thresholds
        self.previous_config = None
        self.probation_counter = 0
        self.probation_limit = 1 # Steps to monitor after a change

    def save_state(self, current_config):
        """Saves the configuration BEFORE applying changes."""
        self.previous_config = copy.deepcopy(current_config)
        self.probation_counter = self.probation_limit

    def check_metrics(self, current_metrics):
        """
        Checks if current metrics violate safety thresholds.
        Returns True if Rollback is required.
        """
        if self.probation_counter > 0:
            self.probation_counter -= 1
            
            p95_retry = current_metrics.get('p95_retry', 0)
            p50_thr = current_metrics.get('p50_throughput', 100)

            if (p95_retry > self.thresholds['max_retry_rate'] or 
                p50_thr < self.thresholds['min_throughput']):
                
                logger.warning(f"!!! ROLLBACK TRIGGERED !!! Retry: {p95_retry:.1f}%, Thr: {p50_thr:.1f} Mbps")
                return True
                
        return False

    def get_backup(self):
        """Returns the saved previous configuration."""
        return self.previous_config
    
    def reset_probation(self):
        self.probation_counter = 0