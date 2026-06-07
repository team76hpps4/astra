import time
import logging

# Setup Logger
logger = logging.getLogger("GlobalWatcher")

class GlobalResetWatcher:
    def __init__(self, band_prefix, thresholds):
        """
        Monitors long-term network health to trigger Global Graph Coloring.
        
        Args:
            band_prefix (str): "2.4G" or "5G" for logging.
            thresholds (dict): Needs keys:
                - 'interference_threshold': Max acceptable avg spectral overlap (0.0-1.0)
                - 'max_retry_rate': Persistent failure threshold (%)
                - 'min_throughput': Persistent failure threshold (Mbps)
                - 'catastrophic_retry': Immediate reset threshold (%)
        """
        self.band = band_prefix
        self.thresholds = thresholds
        
        # State Tracking
        self.frustration_counter = 0
        self.frustration_limit = 3  # Reset after 3 consecutive bad episodes
        self.last_reset_time = 0
        
        # Constraints
        # Hard limit: Max 1 reset per 24 hours (unless catastrophic) -> CAN BE RECONFIGURED
        self.MIN_RESET_INTERVAL_SEC = 24 * 3600  

    def check_health(self, current_time, avg_overlap, avg_retry, avg_throughput):
        """
        Evaluates system health at the end of an episode.
        Returns True if a Global Reset (Graph Coloring) is required.
        """
        
        # 1. Check Cool-down
        time_since_last = current_time - self.last_reset_time
        in_cooldown = time_since_last < self.MIN_RESET_INTERVAL_SEC

        # 2. Check for CATASTROPHIC Failure (Immediate Trigger)
        # If the network is unusable (e.g., >50% retries), we ignore the cooldown.
        if avg_retry > self.thresholds['catastrophic_retry']:
            logger.critical(f"[{self.band} WATCHER] CATASTROPHIC FAILURE (Retry {avg_retry:.1f}%). FORCE GLOBAL RESET.")
            self.reset_state(current_time)
            return True

        # 3. Check for CHRONIC Failure (Frustration Logic)
        # We only reset if High Interference is the ROOT CAUSE of Bad Performance.
        # If interference is low but performance is bad, it's an RL tuning issue, not a Channel Plan issue.
        
        is_high_interference = avg_overlap > self.thresholds['interference_threshold']
        is_bad_performance = (avg_retry > self.thresholds['max_retry_rate']) or \
                             (avg_throughput < self.thresholds['min_throughput'])

        if is_high_interference and is_bad_performance:
            self.frustration_counter += 1
            logger.warning(f"[{self.band} WATCHER] System Degrading (High Interf + Poor KPI). Frustration: {self.frustration_counter}/{self.frustration_limit}")
        else:
            # Decay frustration if things look okay (Self-healing)
            if self.frustration_counter > 0:
                self.frustration_counter -= 1
                # logger.info(f"[{self.band} WATCHER] System Recovering. Frustration decreased.")

        # 4. Trigger Logic
        if self.frustration_counter >= self.frustration_limit:
            if not in_cooldown:
                logger.warning(f"[{self.band} WATCHER] Persistent Structural Failure Detected. REQUESTING GLOBAL CHANNEL RESET.")
                self.reset_state(current_time)
                return True
            else:
                logger.info(f"[{self.band} WATCHER] Reset needed but in cool-down ({time_since_last/3600:.1f}h < 24h).")
        
        return False

    def reset_state(self, time_now):
        """Called when a reset actually happens to update internal timers."""
        self.frustration_counter = 0
        self.last_reset_time = time_now