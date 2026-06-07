import numpy as np
import random
import sys
import os

# Planner Module Import (Used for constants)
from planner_logic_5 import NUM_NETWORK_1_APS, RL_SPARSE_SIZE

def prepare_observation_instant(current_net1_configs):
    """
    Converts the current state (12 APs) into the numerical Observation vector (instantaneous data).
    """
    obs = []
    for ap in current_net1_configs:
        obs.extend([
            ap['tx_power_dbm'],
            ap['obss_pd_dbm'],
            ap['channel_width_mhz'],
            ap['channel']
        ])
    return np.array(obs, dtype=np.float32)

def prepare_observation_aggregated(aggregation_history):
    """
    Converts the 48-step history into a fixed-size aggregated Observation vector 
    for end-of-episode RL training. (Example: Mean RSSI)
    """
    # aggregation_history = (all_final_matrices, all_rssi_matrices, all_overlap_matrices)
    
    rssi_history = aggregation_history[1]
    if not rssi_history:
         return np.zeros(144) # 12*12 flattened RSSI
         
    mean_rssi_matrix = np.mean(np.stack(rssi_history), axis=0)
    
    # Flatten the 12x12 mean RSSI matrix (144 features)
    agg_obs = mean_rssi_matrix.flatten()
    
    return agg_obs


def get_action(current_net1_configs, step, aggregation_history):
    """
    Predicts the next best RRM action based on the current step.
    
    Args:
        current_net1_configs (list): Instantaneous state of 12 APs.
        step (int): Current simulation step (0-47).
        aggregation_history (tuple): Full history of matrices for RL aggregation at step 47.
        
    Returns:
        tuple: Sparse action arrays (indices, tx, pd, ch, cw).
    """
    
    if step == 47: 
        # --- End of Episode: Use Aggregated Data ---
        print("[RL Agent 5G] Generating action based on FULL 48-STEP EPISODE HISTORY.", flush=True)
        observation = prepare_observation_aggregated(aggregation_history)
    else:
        # --- During Episode: Use Instantaneous Data ---
        observation = prepare_observation_instant(current_net1_configs)

    # ----------------------------------------------------
    # PLACEHOLDER LOGIC: Replace this with your actual RL Model prediction code
    # ----------------------------------------------------
    
    # Choose M=4 random AP indices to target
    rl_ap_indices_sparse = sorted(random.sample(range(NUM_NETWORK_1_APS), RL_SPARSE_SIZE))
    
    # Generate random, but bounded, proposed values (size 4)
    valid_channels = [36.0, 48.0, 149.0, 161.0]
    valid_cws = [20.0, 40.0, 80.0]
    
    rl_tx_dbm_sparse = np.random.uniform(18.0, 22.0, RL_SPARSE_SIZE)
    rl_pd_dbm_sparse = np.random.uniform(-70.0, -40.0, RL_SPARSE_SIZE)
    rl_channel_sparse = np.array([random.choice(valid_channels) for _ in range(RL_SPARSE_SIZE)])
    rl_cw_mhz_sparse = np.array([random.choice(valid_cws) for _ in range(RL_SPARSE_SIZE)])
    
    # ----------------------------------------------------
    
    return (rl_ap_indices_sparse, rl_tx_dbm_sparse, rl_pd_dbm_sparse, 
            rl_channel_sparse, rl_cw_mhz_sparse)