import numpy as np
import random
import sys
import os

# Fix for ModuleNotFoundError
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.append(current_dir)

from src.planner_logic_5 import validate_and_commit_changes, PLANNER_GUARDRAILS, HYSTERESIS_THRESHOLDS, RL_SPARSE_SIZE

# --- CONSTANTS ---
NUM_NETWORK_1_APS = 12
NETWORK_ID = 1.0 

def create_mock_full_current_config():
    """ Creates a mock list of 36 AP dictionaries (simulating simulation output). """
    CH_CYCLE_5G = [36.0, 48.0, 149.0, 161.0] 
    CW_ALLOWED = [20.0, 40.0, 80.0]
    all_ap_configs = []
    
    for i in range(36):
        net_id = float((i % 3) + 1)
        if net_id == NETWORK_ID:
            tx_dbm = 18.0 + random.uniform(-1, 1)  
            pd_dbm = -60.0 + random.uniform(-5, 5) 
            channel = random.choice(CH_CYCLE_5G)
            cw_mhz = random.choice(CW_ALLOWED)
        else:
            tx_dbm = 20.0; pd_dbm = -50.0; channel = 161.0; cw_mhz = 80.0
            
        ap_config = {
            'tx_power_dbm': tx_dbm, 'obss_pd_dbm': pd_dbm, 'channel': channel,
            'channel_width_mhz': cw_mhz, 'network_id': net_id
        }
        all_ap_configs.append(ap_config)
    return all_ap_configs

def create_mock_rl_sparse_proposal(current_net1_configs):
    """
    Creates sparse (size M=4) arrays simulating the RL agent's output.
    """
    
    # 1. Select 4 AP Indices (randomly choose which APs to target)
    # Ensure they are unique and within the 0-11 range
    rl_ap_indices_sparse = sorted(random.sample(range(NUM_NETWORK_1_APS), RL_SPARSE_SIZE))

    # 2. Assign specific test scenarios to these 4 indices
    
    # A. Index 0 (e.g., AP at original index 0): Hysteresis Reject (TX)
    i0 = rl_ap_indices_sparse[0]
    current_tx_0 = current_net1_configs[i0]['tx_power_dbm']
    prop_tx_0 = current_tx_0 + (HYSTERESIS_THRESHOLDS['tx_power_dbm'] / 2.0) # Half the threshold
    prop_ch_0 = current_net1_configs[i0]['channel'] # No channel change
    
    # B. Index 1 (e.g., AP at original index 3): Guardrail Clip (TX)
    i1 = rl_ap_indices_sparse[1]
    current_tx_1 = current_net1_configs[i1]['tx_power_dbm']
    prop_tx_1 = PLANNER_GUARDRAILS['tx_power_dbm']['max'] + 1.0 # Above max guardrail
    prop_ch_1 = current_net1_configs[i1]['channel'] 
    
    # C. Index 2 (e.g., AP at original index 5): Hysteresis Commit (PD)
    i2 = rl_ap_indices_sparse[2]
    current_pd_2 = current_net1_configs[i2]['obss_pd_dbm']
    prop_pd_2 = current_pd_2 - 5.0 # Well below (more negative) threshold
    prop_ch_2 = current_net1_configs[i2]['channel'] 
    
    # D. Index 3 (e.g., AP at original index 7): Invalid Discrete (Channel)
    i3 = rl_ap_indices_sparse[3]
    prop_tx_3 = current_net1_configs[i3]['tx_power_dbm'] # No change to TX
    prop_ch_3 = 99.0 # Invalid channel ID

    # 3. Construct the Sparse Arrays (Size 4)
    rl_tx_dbm_sparse = np.array([prop_tx_0, prop_tx_1, prop_tx_3, prop_tx_3]) 
    rl_pd_dbm_sparse = np.array([current_net1_configs[i]['obss_pd_dbm'] for i in rl_ap_indices_sparse])
    rl_pd_dbm_sparse[2] = prop_pd_2 # Set the significant PD change
    rl_channel_sparse = np.array([prop_ch_0, prop_ch_1, prop_ch_2, prop_ch_3])
    rl_cw_mhz_sparse = np.array([current_net1_configs[i]['channel_width_mhz'] for i in rl_ap_indices_sparse])
    
    # 4. Print Scenario
    print(f"\n--- RL PROPOSAL SCENARIOS (Sparse M={RL_SPARSE_SIZE}) ---")
    print(f"Targeted Indices (0-11): {rl_ap_indices_sparse}")
    
    scenarios = {
        i0: f"AP {i0}: TX Hys Reject (Prop {prop_tx_0:.1f})",
        i1: f"AP {i1}: TX Guardrail Clip (Prop {prop_tx_1:.1f})",
        i2: f"AP {i2}: PD Hys Commit (Prop {prop_pd_2:.1f})",
        i3: f"AP {i3}: CH Guardrail Reject (Prop {prop_ch_3:.0f})"
    }
    
    for idx in rl_ap_indices_sparse:
         print(scenarios[idx])

    return rl_ap_indices_sparse, rl_tx_dbm_sparse, rl_pd_dbm_sparse, rl_channel_sparse, rl_cw_mhz_sparse


def main():
    
    # 1. GENERATE FULL MOCK CONFIGURATION (Raw data from simulation)
    current_full_ap_configs = create_mock_full_current_config()
    
    # >>> CRITICAL STEP: FILTERING (The caller's responsibility) <<<
    current_net1_configs = [ap for ap in current_full_ap_configs if ap['network_id'] == NETWORK_ID]
    
    # 2. GENERATE MOCK RL PROPOSAL (Sparse input arrays)
    rl_ap_indices_sparse, rl_tx_dbm_sparse, rl_pd_dbm_sparse, rl_channel_sparse, rl_cw_mhz_sparse = \
        create_mock_rl_sparse_proposal(current_net1_configs)

    # 3. RUN THE PLANNER LOGIC (Uses sparse inputs)
    print("-" * 50)
    print("Running Planner: Validate and Commit Changes")
    print("-" * 50)
    
    committed_config_matrix = validate_and_commit_changes(
        current_net1_configs, 
        rl_ap_indices_sparse,
        rl_tx_dbm_sparse,
        rl_pd_dbm_sparse,
        rl_channel_sparse,
        rl_cw_mhz_sparse
    )

    # 4. DISPLAY RESULTS 
    
    # Get current configurations for comparison
    current_tx = np.array([ap['tx_power_dbm'] for ap in current_net1_configs])
    current_pd = np.array([ap['obss_pd_dbm'] for ap in current_net1_configs])
    current_ch = np.array([ap['channel'] for ap in current_net1_configs])
    current_cw = np.array([ap['channel_width_mhz'] for ap in current_net1_configs])
    
    print("\n" + "=" * 80)
    print(f"PLANNED ACTION SUMMARY (M={RL_SPARSE_SIZE} APs Targeted, N={NUM_NETWORK_1_APS} APs Managed)")
    print("=" * 80)
    
    print(f"Hysteresis Thresholds: TX >= {HYSTERESIS_THRESHOLDS['tx_power_dbm']} dB | PD >= {HYSTERESIS_THRESHOLDS['obss_pd_dbm']} dB")
    
    print("\n{:<5} {:<6} {:<10} {:<10} | {:<10} {:<15} | {:<10} {:<10}".format(
        "AP ID", "Param", "Current", "Proposed", "Committed", "Action", "Ch_Cur", "Ch_New"))
    print("-" * 80)

    for i in range(NUM_NETWORK_1_APS):
        
        # Determine the action result for TX
        tx_action = "KEPT (Implicit)" if i not in rl_ap_indices_sparse else "N/A"
        if i in rl_ap_indices_sparse:
            if committed_config_matrix[0, i] == current_tx[i]:
                tx_action = "REJECT (Hys)"
            elif committed_config_matrix[0, i] != rl_tx_dbm_sparse[rl_ap_indices_sparse.index(i)]:
                tx_action = "CLIP (Guard)"
            else:
                tx_action = "COMMIT"

        # Determine the action result for PD
        pd_action = "KEPT (Implicit)" if i not in rl_ap_indices_sparse else "N/A"
        if i in rl_ap_indices_sparse:
            if committed_config_matrix[1, i] == current_pd[i]:
                pd_action = "REJECT (Hys)" 
            elif committed_config_matrix[1, i] != rl_pd_dbm_sparse[rl_ap_indices_sparse.index(i)]:
                pd_action = "CLIP (Guard)"
            else:
                pd_action = "COMMIT"
        
        # Use the Dense Proposed Arrays for comparison in the table output
        proposed_tx_dense = committed_config_matrix[0, i] + (current_tx[i] - committed_config_matrix[0, i]) if tx_action == "REJECT (Hys)" else committed_config_matrix[0, i]
        proposed_pd_dense = committed_config_matrix[1, i] + (current_pd[i] - committed_config_matrix[1, i]) if pd_action == "REJECT (Hys)" else committed_config_matrix[1, i]
        
        # Display TX results
        print("{:<5} {:<6} {:<10.3f} {:<10.3f} | {:<10.3f} {:<15} | {:<10.0f} {:<10.0f}".format(
            i, "TX", current_tx[i], proposed_tx_dense if i in rl_ap_indices_sparse else current_tx[i], 
            committed_config_matrix[0, i], tx_action, current_ch[i], committed_config_matrix[2, i]))
        
        # Display PD results
        print("{:<5} {:<6} {:<10.3f} {:<10.3f} | {:<10.3f} {:<15} | {:<10.0f} {:<10.0f}".format(
            i, "PD", current_pd[i], proposed_pd_dense if i in rl_ap_indices_sparse else current_pd[i], 
            committed_config_matrix[1, i], pd_action, current_cw[i], committed_config_matrix[3, i]))

if __name__ == "__main__":
    # Ensure random seed is set for predictable testing
    random.seed(123) 
    np.random.seed(123)
    np.set_printoptions(precision=3, suppress=True)
    main()