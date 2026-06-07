import matlab.engine
import math
import random
import numpy as np
import time
import json
import os
import sys 
import copy # Added import copy

# ==========================================
# FIX: NAVIGATE TO PROJECT ROOT AND IMPORT MUX
# ==========================================
src_folder = os.path.dirname(os.path.abspath(__file__))
if src_folder not in sys.path:
    sys.path.append(src_folder)

# Assuming give_input5.py (5G MUX) is in the same directory
from give_input5 import generate_rrm_arrays 

# --- HELPER FUNCTION TO BUILD STATIC GEOMETRY TEMPLATE (5G Specific) ---
def build_static_ap_template_5G(config):
    """
    Constructs a baseline list of 36 AP configuration dictionaries with fixed
    position (pos) and network_id. This is called ONCE before the time loop.
    """
    
    NUM_ROOMS = int(config['num_rooms'])
    NUM_APS_PER_ROOM = int(config['ap_per_room'])
    
    # Use random settings that are within valid 5G ranges for the initial RRM values
    DEFAULT_TX = 21.0 
    DEFAULT_PD = -65.0 
    CH_CYCLE_ROOM = [36.0, 48.0, 161.0]
    DEFAULT_CW = 80.0
    
    static_template = []
    
    center_x, center_y = 50.0, 50.0
    spread_factor = 45.0
    golden_angle = math.pi * (3 - math.sqrt(5))
    rng = random.Random(config['random_seed'])
    
    for r in range(NUM_ROOMS):
        radius = spread_factor * math.sqrt(r + 1)
        theta = (r + 1) * golden_angle
        theta_jit = theta + (rng.random() - 0.5) * 0.5
        radius_jit = radius + (rng.random() - 0.5) * 5.0
        
        room_x = center_x + radius_jit * math.cos(theta_jit)
        room_y = center_y + radius_jit * math.sin(theta_jit)
        
        offsets = [(5, 5), (15, 25), (25, 5)]

        for k in range(NUM_APS_PER_ROOM):
            ap_struct = {
                # STATIC GEOMETRY
                'pos': matlab.double([room_x + offsets[k][0], room_y + offsets[k][1]]),
                'network_id': float(k + 1), # Network ID 1, 2, 3
                # INITIAL RRM PARAMETERS (Will be overwritten in loop)
                'tx_power_dbm': DEFAULT_TX,
                'channel_width_mhz': DEFAULT_CW,
                'obss_pd_dbm': DEFAULT_PD,
                'channel': CH_CYCLE_ROOM[k % len(CH_CYCLE_ROOM)], 
            }
            static_template.append(ap_struct)
            
    return static_template
# ----------------------------------------------------------------------


def main():
    
    # ==========================================
    # 0. FIXED SIMULATED TIME CONFIGURATION & MUX CONTROL
    # ==========================================
    
    DT_MS = 300000.0          # Time Step Resolution: 5 minutes
    TOTAL_STEPS = 48          # Total Steps: 48
    SELECT = 0                # MUX Control: 1=Event Loop, 0=RL Agent
    
    SIM_DURATION_S = TOTAL_STEPS * (DT_MS / 1000.0)
    RL_EPISODE_DURATION_MIN = SIM_DURATION_S / 60.0
    
    # --- MATLAB Engine Setup ---
    print("Starting MATLAB Engine...")
    try:
        eng = matlab.engine.start_matlab()
    except Exception as e:
        print(f"Error starting MATLAB engine: {e}")
        return

    # Set MATLAB working directory to Project Root (parent of src_folder)
    project_root = os.path.dirname(src_folder)
    eng.cd(project_root)
    
    # ==========================================
    # 1. BASE CONFIGURATION (5 GHz Specific)
    # ==========================================
    CHANNELS_5G = [36,40,44,48,52,56,60,64,100,104,108,112,116,120,124,128,132,136,140,144,149,153,157,161,165]
    NUM_ROOMS = 12
    NUM_APS_PER_ROOM = 3
    NUM_TOTAL_APS = NUM_ROOMS * NUM_APS_PER_ROOM # 36
    
    config = {
        'random_seed': 123,
        'rl_episode_duration_min': RL_EPISODE_DURATION_MIN,
        'sim_duration_s': SIM_DURATION_S, 
        'dt_ms': DT_MS, 
        'channel_width_mhz': 80.0, 
        'noise_figure_db': 7.0,
        'noise_floor_dbm': -95.0,
        'noise_variation_frac': 0.03, 
        'short_term_shadowing_sigma': 6.0,
        'shadowing_sigma': 4.0,
        'cca_threshold_dbm': -80.0,
        'num_rooms': float(NUM_ROOMS),
        'ap_per_room': float(NUM_APS_PER_ROOM),
        'client_grid_spacing': 5.0, 
        'room_size': matlab.double([10, 10]), 
        'channels': matlab.double(CHANNELS_5G),
        'MCS_SINR_Required': matlab.double([0,1.5,3.5,5,8,10,12,13,15,17,18,20]),
        'pathloss': {'n_exp': 4.0, 'wall_loss_db': 15.0, 'PL_d0_dB': 36.0, 'd0': 1.0},
        'MCS_Rates_20MHz': matlab.double(np.array([6.5,13,19.5,26,39,52,58.5,65,78,86.7,97.5,108.3]) * 3),
        'MCS_Rates_40MHz': matlab.double(np.array([13.5,27,40.5,54,81,108,121.5,135,162,180,202.5,225]) * 3),
        'MCS_Rates_80MHz': matlab.double(np.array([29.3,58.5,87.8,117,175.5,234,263.25,292.5,351,390,438.8,487.5]) * 3),
        'MCS_Rates_160MHz': matlab.double(np.array([58.5,117,175.5,234,351,468,526.5,585,702,780,877.5,975]) * 3),
        'bt': {'count': 6.0, 'tx_power_dbm': 0.0, 'duty_cycle': 0.002},
        'zb': {'count': 1.0, 'tx_power_dbm': -5.0, 'duty_cycle': 0.001},
    }

    # ==========================================
    # 2. STATIC GEOMETRY SETUP (Runs ONLY ONCE)
    # ==========================================
    static_ap_template = build_static_ap_template_5G(config)
    
    # The MUX needs the full list from the previous step (T=0)
    current_full_ap_configs = copy.deepcopy(static_ap_template) 
    
    print(f"--- 5 GHz SIMULATION START ---")
    print(f"Time Step Resolution (dt): {DT_MS/1000:.0f} s ({DT_MS/60000:.0f} min)")
    print(f"Total Simulated Time: {SIM_DURATION_S/3600:.1f} hours")

    # Storage for aggregated results 
    all_p50_throughput_per_ap = [] 
    all_p95_retry_per_ap = [] # NEW: Storage for retry rate aggregation
    
    # ==========================================
    # 3. TIME LOOP: Iterates through simulation steps
    # ==========================================
    
    for step in range(TOTAL_STEPS):
        
        step_time_s = (step + 1) * (DT_MS / 1000)
        print(f"\n--- Running Step {step + 1}/{TOTAL_STEPS} (T={step_time_s:.0f} s) ---", flush=True)

        # --- A. Get RRM Configuration (MUX) ---
        
        # Call MUX to get the validated configuration arrays (12 arrays)
        room_tx_array, room_pd_array, room_cw_array, room_channel = generate_rrm_arrays(
            NUM_ROOMS, 
            SELECT, 
            current_full_ap_configs # Pass the last step's full config to the MUX/Planner
        )
        
        # --- B. UPDATE RRM PARAMETERS ON STATIC GEOMETRY ---
        
        ap_configs_list = [] # List to send to MATLAB
        
        # We iterate through the static template (36 APs)
        for i in range(NUM_TOTAL_APS):
            ap_struct = copy.deepcopy(static_ap_template[i])
            
            # Determine the room index (r) for this AP (0 to 11)
            r = math.floor(i / NUM_APS_PER_ROOM) 
            
            # Determine the AP's index within the room (k) (0 to 2)
            k = i % NUM_APS_PER_ROOM
            
            # Apply RRM committed values from the room arrays (room_tx_array[r])
            ap_struct['tx_power_dbm'] = float(room_tx_array[r])
            ap_struct['obss_pd_dbm'] = float(room_pd_array[r])
            ap_struct['channel_width_mhz'] = float(room_cw_array[r])
            
            # Channel cycling based on the committed base channel (start_ch)
            start_ch = float(room_channel[r])
            CH_CYCLE_ROOM = [start_ch, start_ch + 4, start_ch - 4] 
            ap_struct['channel'] = CH_CYCLE_ROOM[k % len(CH_CYCLE_ROOM)]
            
            ap_configs_list.append(ap_struct)

        # --- C. Run MATLAB Simulation ---
        
        eng.workspace['temp_config_cell'] = ap_configs_list
        eng.eval("ap_configs = [temp_config_cell{:}];", nargout=0)
        eng.workspace['config'] = config
        
        t0 = time.time()
        print(f"Executing 5G simulation for {NUM_TOTAL_APS} APs...", flush=True)
        
        # IMPORTANT: Call the 5 GHz MATLAB function
        eng.eval("res = simulate_environment_5G(config, ap_configs);", nargout=0)
        json_str = eng.eval("jsonencode(res);")
        results = json.loads(json_str)
        
        # --- D. Metric Extraction and Logging (Network 1 Specific) ---
        time_elapsed = time.time() - t0
        
        # 1. Extract Final Output Matrix
        final_matrix = np.array(results['Final_Output_Matrix'])
        
        # 2. Filter Matrix Columns to ONLY Network 1 APs (Columns 0, 3, 6, 9, ..., 33)
        net1_matrix = final_matrix[:, 0::3]
        
        # 3. Extract P50 Throughput (Row 104 in Python indexing)
        p50_thr_per_ap = net1_matrix[104, :]
        current_mean_p50_thr = np.mean(p50_thr_per_ap)
        
        # 4. Extract P95 Retry Rate (Row 105 in Python indexing)
        p95_retry_per_ap = net1_matrix[105, :]
        current_mean_p95_retry = np.mean(p95_retry_per_ap)
        
        # 5. Store data for final overall aggregation
        all_p50_throughput_per_ap.append(p50_thr_per_ap)
        all_p95_retry_per_ap.append(p95_retry_per_ap) # NEW: Store Retry Rate
        
        print(f"Simulation finished in {time_elapsed:.2f}s (Real Time)", flush=True)
        print(f"-> NETWORK 1 THROUGHPUT (Avg P50): {current_mean_p50_thr:.2f} Mbps", flush=True)
        print(f"-> NETWORK 1 RETRY RATE (Avg P95): {current_mean_p95_retry:.2f} %", flush=True)
        
        # --- E. Update State for Next Step (Crucial for Planner) ---
        
        current_full_ap_configs = ap_configs_list
        
    # ==========================================
    # 4. FINAL AGGREGATION OUTPUT
    # ==========================================
    
    if all_p50_throughput_per_ap:
        np.set_printoptions(precision=3, suppress=True, linewidth=150)
        
        # --- Throughput Aggregation ---
        final_p50_thr_array = np.concatenate(all_p50_throughput_per_ap)
        overall_mean_p50_thr = np.mean(final_p50_thr_array)
        output_p50_matrix = final_p50_thr_array.reshape(NUM_ROOMS, TOTAL_STEPS)
        
        # --- Retry Rate Aggregation ---
        final_p95_retry_array = np.concatenate(all_p95_retry_per_ap)
        overall_mean_p95_retry = np.mean(final_p95_retry_array)
        output_p95_retry_matrix = final_p95_retry_array.reshape(NUM_ROOMS, TOTAL_STEPS)
        
        print("\n" + "=" * 80)
        print(f"FINAL AGGREGATED RESULTS (Across {TOTAL_STEPS} Steps)")
        print("=" * 80)
        
        print(f"[THROUGHPUT] OVERALL MEAN P50 NETWORK 1: {overall_mean_p50_thr:.2f} Mbps")
        print(f"[RETRY RATE] OVERALL MEAN P95 NETWORK 1: {overall_mean_p95_retry:.2f} %")
        print("-" * 80)
        
        # Print P50 Matrix
        print(f"P50 THROUGHPUT MATRIX (12 Net 1 APs x {TOTAL_STEPS} Steps):")
        print(output_p50_matrix)
        print("-" * 80)

        # Print P95 Retry Rate Matrix
        print(f"P95 RETRY RATE MATRIX (12 Net 1 APs x {TOTAL_STEPS} Steps):")
        print(output_p95_retry_matrix)
        
        print("=" * 80)


    eng.quit()
    print("--- 5 GHz SIMULATION END ---")

if __name__ == "__main__":
    main()