import matlab.engine
import math
import random
import numpy as np
import time
import json
import os
import sys 
import copy 

# --- PATH AND IMPORTS ---
src_folder = os.path.dirname(os.path.abspath(__file__))
if src_folder not in sys.path:
    sys.path.append(src_folder)
    
from give_input5 import generate_rrm_arrays 
from planner_logic_5 import NUM_NETWORK_1_APS, RL_SPARSE_SIZE

# ==========================================
# 1. CONFIGURATION CONSTANTS (5 GHz Specific)
# ==========================================
NUM_ROOMS = 12
NUM_APS_PER_ROOM = 3
NUM_TOTAL_APS = NUM_ROOMS * NUM_APS_PER_ROOM # 36
NET1_SLICE = slice(0, None, 3)

config_5g = {
    'random_seed': 123,
    'dt_ms': 300000.0,
    'channel_width_mhz': 80.0, 'noise_figure_db': 7.0, 'noise_floor_dbm': -95.0,
    'noise_variation_frac': 0.03, 'short_term_shadowing_sigma': 6.0, 'shadowing_sigma': 4.0,
    'cca_threshold_dbm': -80.0, 'num_rooms': float(NUM_ROOMS), 'ap_per_room': float(NUM_APS_PER_ROOM),
    'client_grid_spacing': 5.0, 'room_size': matlab.double([10, 10]), 
    'channels': matlab.double([36,40,44,48,52,56,60,64,100,104,108,112,116,120,124,128,132,136,140,144,149,153,157,161,165]),
    'MCS_SINR_Required': matlab.double([0,1.5,3.5,5,8,10,12,13,15,17,18,20]),
    'pathloss': {'n_exp': 4.0, 'wall_loss_db': 15.0, 'PL_d0_dB': 36.0, 'd0': 1.0},
    'MCS_Rates_20MHz': matlab.double(np.array([6.5,13,19.5,26,39,52,58.5,65,78,86.7,97.5,108.3]) * 3),
    'MCS_Rates_40MHz': matlab.double(np.array([13.5,27,40.5,54,81,108,121.5,135,162,180,202.5,225]) * 3),
    'MCS_Rates_80MHz': matlab.double(np.array([29.3,58.5,87.8,117,175.5,234,263.25,292.5,351,390,438.8,487.5]) * 3),
    'MCS_Rates_160MHz': matlab.double(np.array([58.5,117,175.5,234,351,468,526.5,585,702,780,877.5,975]) * 3),
    'bt': {'count': 6.0, 'tx_power_dbm': 0.0, 'duty_cycle': 0.002},
    'zb': {'count': 1.0, 'tx_power_dbm': -5.0, 'duty_cycle': 0.001},
    'sim_duration_s': 10.0, # Placeholder, as actual time is controlled by master
    'rl_episode_duration_min': 240.0, # Placeholder
}

# ----------------------------------------------------------------------


def run_5g_step(eng, config, current_full_ap_configs, static_ap_template, step, SELECT, *aggregation_history):
    """ 
    Executes one time step of the 5 GHz simulation and RRM loop. 
    """
    
    step_time_s = (step + 1) * (config['dt_ms'] / 1000)
    print(f"\n[5G] Running Step {step + 1} (T={step_time_s:.0f} s)...", flush=True)

    # --- A. Get RRM Configuration (MUX) ---
    room_tx_array, room_pd_array, room_cw_array, room_channel = generate_rrm_arrays(
        NUM_ROOMS, 
        SELECT, 
        current_full_ap_configs,
        step, # Pass current step number
        aggregation_history # Pass the entire aggregation history tuple
    )
    
    # --- B. UPDATE RRM PARAMETERS ON STATIC GEOMETRY ---
    ap_configs_list = [] 
    
    for i in range(NUM_TOTAL_APS):
        ap_struct = copy.deepcopy(static_ap_template[i])
        
        r = math.floor(i / NUM_APS_PER_ROOM) # Room index (0-11)
        k = i % NUM_APS_PER_ROOM            # AP index within room (0-2)
        
        # Apply RRM committed values from the room arrays
        ap_struct['tx_power_dbm'] = float(room_tx_array[r])
        ap_struct['obss_pd_dbm'] = float(room_pd_array[r])
        ap_struct['channel_width_mhz'] = float(room_cw_array[r])
        
        # Channel cycling based on the committed base channel
        start_ch = float(room_channel[r])
        CH_CYCLE_ROOM = [start_ch, start_ch + 4, start_ch - 4] 
        ap_struct['channel'] = CH_CYCLE_ROOM[k % len(CH_CYCLE_ROOM)]
        
        ap_configs_list.append(ap_struct)

    # --- C. Run MATLAB Simulation ---
    eng.workspace['temp_config_cell'] = ap_configs_list
    eng.eval("ap_configs = [temp_config_cell{:}];", nargout=0)
    eng.workspace['config'] = config
    
    t0 = time.time()
    eng.eval("res = simulate_environment_5G(config, ap_configs);", nargout=0)
    json_str = eng.eval("jsonencode(res);")
    results = json.loads(json_str)
    time_elapsed = time.time() - t0
    
    print(f"[5G] Execution time: {time_elapsed:.2f}s", flush=True)

    # --- D. Return updated state and results ---
    # ap_configs_list (the current state) is now the new baseline for the next step
    return ap_configs_list, results


def get_5G_data(eng, config, current_full_ap_configs,step):
    """ 
    Executes one time step of the 5 GHz simulation and RRM loop for training.
    """
    
    step_time_s = (step + 1) * (config['dt_ms'] / 1000)
    #print(f"\n[5G] Running Step {step + 1} (T={step_time_s:.0f} s)...", flush=True)
    #log_file.write(f"\n--- STEP {step + 1} (T={step_time_s:.0f} s) [5G] ---\n")

    # CRITICAL STEP 1: Filter the full 36 AP list down to the 12 managed APs (Network 1)
    current_net1_configs = [ap for ap in current_full_ap_configs if ap['network_id'] == 1.0]

    # --- A. Setup and Run MATLAB Simulation (To get instantaneous matrices) ---
    ap_configs_list = current_full_ap_configs # Use the current config list
    
    eng.workspace['temp_config_cell'] = ap_configs_list
    eng.eval("ap_configs = [temp_config_cell{:}];", nargout=0)
    eng.workspace['config'] = config
    
    t0 = time.time()
    eng.eval("res = simulate_environment_5G(config, ap_configs);", nargout=0)
    json_str = eng.eval("jsonencode(res);")
    results = json.loads(json_str)
    time_elapsed = time.time() - t0
    
    # Extract ALL 36x36 matrices (RAW DATA)
    final_matrix_36 = np.array(results['Final_Output_Matrix'])
    rssi_matrix_36 = np.array(results['AP2AP_rssi_dbm'])
    overlap_matrix_36 = np.array(results['Channel_Overlap_Matrix'])
    
    print(f"[5G] Execution time: {time_elapsed:.2f}s", flush=True)

    # =================================================================
    # B. NETWORK 1 MATRIX FILTERING (12x12) & RL Policy Call
    # =================================================================

    # 1. Filter Metrics (107 rows, 36 columns -> 107 rows, 12 columns)
    final_matrix_12 = final_matrix_36[:, NET1_SLICE]

    # 2. Filter RSSI/Overlap Matrices (36x36 -> 12x12)
    # This matrix contains the coupling only among Network 1 APs.
    rssi_matrix_12 = rssi_matrix_36[NET1_SLICE, :][:, NET1_SLICE]
    overlap_matrix_12 = overlap_matrix_36[NET1_SLICE, :][:, NET1_SLICE]
    
    return final_matrix_12, overlap_matrix_12, rssi_matrix_12