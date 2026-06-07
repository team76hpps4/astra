import numpy as np

class HysteresisManager:
    def __init__(self, num_aps, thresholds):
        """
        thresholds: dict, e.g., {'tx_power_dbm': 0.5, 'obss_pd_dbm': 3.0}
        """
        self.num_aps = num_aps
        self.thresholds = thresholds

    def filter_changes(self, current_config, candidate_config):
        """
        Compares current vs candidate config.
        Returns a dictionary of changes that pass hysteresis checks.
        """
        # Create a copy to store only valid changes
        valid_changes = {} 
        changed_ap_indices = []

        # We assume configs are dictionaries of numpy arrays
        # keys: 'tx_power', 'obss_pd', 'channel', 'channel_width'

        # 1. TX Power (Delta Check)
        delta_tx = np.abs(candidate_config['tx_power'] - current_config['tx_power'])
        mask_tx = delta_tx >= self.thresholds['tx_power_dbm']
        
        # 2. OBSS PD (Delta Check)
        delta_pd = np.abs(candidate_config['obss_pd'] - current_config['obss_pd'])
        mask_pd = delta_pd >= self.thresholds['obss_pd_dbm']

        # 3. Channel & Width (Discrete Check - any change is valid)
        mask_ch = candidate_config['channel'] != current_config['channel']
        mask_cw = candidate_config['channel_width'] != current_config['channel_width']

        # Combine masks to find ANY significant change per AP
        change_mask = mask_tx | mask_pd | mask_ch | mask_cw
        
        # Build the valid configuration
        # Start with current config (default to no change)
        valid_config = {k: v.copy() for k, v in current_config.items()}
        
        # Apply changes where mask is True
        if np.any(change_mask):
            valid_config['tx_power'][mask_tx] = candidate_config['tx_power'][mask_tx]
            valid_config['obss_pd'][mask_pd] = candidate_config['obss_pd'][mask_pd]
            valid_config['channel'][mask_ch] = candidate_config['channel'][mask_ch]
            valid_config['channel_width'][mask_cw] = candidate_config['channel_width'][mask_cw]
            
            changed_ap_indices = np.where(change_mask)[0].tolist()

        return valid_config, changed_ap_indices