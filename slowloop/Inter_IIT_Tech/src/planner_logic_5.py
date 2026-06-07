import numpy as np
import copy
import logging
import time

# --- IMPORT HELPER MODULES ---
from hysterisis_check import HysteresisManager
from change_budget import ChangeBudgetManager
from rollback_manage import RollbackManager
from global_reset_set import GlobalResetWatcher 

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger("Planner5G")

# ==========================================
# 5 GHz CONFIGURATION
# ==========================================
NUM_NETWORK_1_APS = 12
RL_SPARSE_SIZE = 4

# Hysteresis
HYSTERESIS_5G = {'tx_power_dbm': 0.5, 'obss_pd_dbm': 3.0}

# Short-Term Rollback
ROLLBACK_THRESHOLDS_5G = {'max_retry_rate': 25.0, 'min_throughput': 10.0}

# Long-Term Watcher (Global Reset criteria)
# 5G usually has cleaner spectrum, so we tolerate less failure.
WATCHER_THRESHOLDS_5G = {
    'interference_threshold': 0.3,  # >30% Avg Overlap implies bad plan in 5G
    'max_retry_rate': 12.0,         # >12% is bad for 5G
    'min_throughput': 10.0,         # <10 Mbps is bad for 5G
    'catastrophic_retry': 40.0      # >40% retry triggers immediate reset
}

class Planner5G:
    def __init__(self):
        # 1. Hysteresis
        self.hysteresis = HysteresisManager(NUM_NETWORK_1_APS, HYSTERESIS_5G)
        # 2. Token Bucket
        self.budget = ChangeBudgetManager(NUM_NETWORK_1_APS, refill_rate=1.0/48.0)
        # 3. Rollback Watchdog
        self.rollback = RollbackManager(ROLLBACK_THRESHOLDS_5G)
        # 4. Global Reset Watcher
        self.watcher = GlobalResetWatcher("5G", WATCHER_THRESHOLDS_5G)
        
        self.current_config = None

    def initialize(self, initial_config):
        self.current_config = {
            'tx_power': np.array([ap['tx_power_dbm'] for ap in initial_config]),
            'obss_pd': np.array([ap['obss_pd_dbm'] for ap in initial_config]),
            'channel': np.array([ap['channel'] for ap in initial_config]),
            'channel_width': np.array([ap['channel_width_mhz'] for ap in initial_config]),
        }
        logger.info("[Planner 5G] Initialized with static configuration.")

    def process_rl_proposal(self, candidate_arrays, confidence_alpha):
        candidate_config = {
            'tx_power': candidate_arrays[0],
            'obss_pd': candidate_arrays[1],
            'channel_width': candidate_arrays[2],
            'channel': candidate_arrays[3]
        }

        filtered_config, potential_aps = self.hysteresis.filter_changes(self.current_config, candidate_config)
        if not potential_aps: return self._export_config()

        allowed_aps, rejected_aps = self.budget.check_and_spend(potential_aps, confidence_alpha)
        if not allowed_aps: 
            logger.info("[Planner 5G] All changes rejected by Budget Manager.")
            return self._export_config()

        self.rollback.save_state(self.current_config)

        for i in allowed_aps:
            self.current_config['tx_power'][i] = filtered_config['tx_power'][i]
            self.current_config['obss_pd'][i] = filtered_config['obss_pd'][i]
            self.current_config['channel'][i] = filtered_config['channel'][i]
            self.current_config['channel_width'][i] = filtered_config['channel_width'][i]

        logger.info(f"[Planner 5G] COMMITTED changes to {len(allowed_aps)} APs (Confidence: {confidence_alpha:.2f})")
        return self._export_config()

    def run_watchdog(self, current_metrics):
        if self.rollback.check_metrics(current_metrics):
            self.current_config = self.rollback.get_backup()
            self.rollback.reset_probation()
            logger.warning("[Planner 5G] WATCHDOG: Configuration REVERTED.")
        self.budget.step_clock()

    def evaluate_episode_health(self, avg_overlap, avg_retry, avg_throughput):
        """Called at END OF EPISODE to check for Global Reset."""
        current_time = time.time()
        return self.watcher.check_health(current_time, avg_overlap, avg_retry, avg_throughput)

    def _export_config(self):
        return (
            self.current_config['tx_power'],
            self.current_config['obss_pd'],
            self.current_config['channel_width'],
            self.current_config['channel']
        )

# Singleton Instance
planner_instance_5g = Planner5G()