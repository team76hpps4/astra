import matlab.engine
import numpy as np
import time
import json
import os
import sys 
import math
import random
import copy
from Inter_IIT_Tech.src import DEFAULTS_YAML, AP_LIST, NOW
import yaml
from Inter_IIT_Tech.src.EventLoopFinal import EventConfigGUI, load_defaults
import datetime
from time import sleep
from Inter_IIT_Tech.src.give_input import get_event_suggestion, config_conversion
from Inter_IIT_Tech.src.give_input5 import get_event_suggestion_5, config_conversion_5
from GRACE.fiveGHz.test_bench import get_embeddings
from GRACE._24GHz.test_bench import get_embeddings2
from Inter_IIT_Tech.src.run_single_step_5g import get_5G_data
from Inter_IIT_Tech.src.run_single_step_2g import get_2G_data


# Add src to path for module access
src_folder = os.path.dirname(os.path.abspath(__file__))
if src_folder not in sys.path:
    sys.path.append(src_folder)

# Import the single-step runners (refactored files)
from run_single_step_5g import run_5g_step, config_5g, NUM_ROOMS, NUM_APS_PER_ROOM
from run_single_step_2g import run_2g_step, config_2g

# ==============================================================
# 1. STATIC GEOMETRY HELPER FUNCTIONS (Centralized Logic)
# --- These generate the fixed AP coordinates for the entire simulation ---
# ==============================================================

def build_static_ap_template_5G(config):
    """ Builds the 36 AP configuration list with fixed geometry for 5G. """
    DEFAULT_TX = 21.0; DEFAULT_PD = -65.0; CH_CYCLE_ROOM = [36.0, 48.0, 161.0]; DEFAULT_CW = 80.0
    static_template = []; center_x, center_y = 50.0, 50.0
    spread_factor = 45.0; golden_angle = math.pi * (3 - math.sqrt(5)); rng = random.Random(config['random_seed'])
    for r in range(NUM_ROOMS):
        radius = spread_factor * math.sqrt(r + 1); theta = (r + 1) * golden_angle
        theta_jit = theta + (rng.random() - 0.5) * 0.5; radius_jit = radius + (rng.random() - 0.5) * 5.0
        room_x = center_x + radius_jit * math.cos(theta_jit); room_y = center_y + radius_jit * math.sin(theta_jit)
        offsets = [(5, 5), (15, 25), (25, 5)]
        for k in range(NUM_APS_PER_ROOM):
            ap_struct = {
                'pos': matlab.double([room_x + offsets[k][0], room_y + offsets[k][1]]), 'network_id': float(k + 1),
                'tx_power_dbm': DEFAULT_TX, 'channel_width_mhz': DEFAULT_CW,
                'obss_pd_dbm': DEFAULT_PD, 'channel': CH_CYCLE_ROOM[k % len(CH_CYCLE_ROOM)], 
            }
            static_template.append(ap_struct)
    
    final_ap_config = []
    for d in static_template:
        final_ap_config.append(d) if d['network_id']==1 else 1

    with open(AP_LIST, "r") as f:
        data = yaml.safe_load(f)
    aps = []
    for i in range(len(final_ap_config)):
        aps.append(f"AP_5G_{i}")
        
    with open(AP_LIST, "w") as f:
        data["5G"] = aps
        yaml.safe_dump(data, f, sort_keys=False)
    
    return static_template

def build_static_ap_template_2g(config):
    """ Builds the 36 AP configuration list with fixed geometry for 2.4G. """
    DEFAULT_TX = 18.0; DEFAULT_PD = -70.0; CH_CYCLE_ROOM = [1.0, 6.0, 11.0]; DEFAULT_CW = 20.0 
    static_template = []; center_x, center_y = 50.0, 50.0
    spread_factor = 45.0; golden_angle = math.pi * (3 - math.sqrt(5)); rng = random.Random(config['random_seed'])
    for r in range(NUM_ROOMS):
        radius = spread_factor * math.sqrt(r + 1); theta = (r + 1) * golden_angle
        theta_jit = theta + (rng.random() - 0.5) * 0.5; radius_jit = radius + (rng.random() - 0.5) * 5.0
        room_x = center_x + radius_jit * math.cos(theta_jit); room_y = center_y + radius_jit * math.sin(theta_jit)
        offsets = [(5, 5), (15, 25), (25, 5)]
        for k in range(NUM_APS_PER_ROOM):
            ap_struct = {
                'pos': matlab.double([room_x + offsets[k][0], room_y + offsets[k][1]]), 'network_id': float(k + 1),
                'tx_power_dbm': DEFAULT_TX, 'channel_width_mhz': DEFAULT_CW,
                'obss_pd_dbm': DEFAULT_PD, 'channel': CH_CYCLE_ROOM[k % len(CH_CYCLE_ROOM)], 
            }
            static_template.append(ap_struct)
    
    final_ap_config = []
    for d in static_template:
        final_ap_config.append(d) if d['network_id']==1 else 1

    with open(AP_LIST, "r") as f:
        data = yaml.safe_load(f)
    aps = []
    for i in range(len(final_ap_config)):
        aps.append(f"AP_2.4G_{i}")
        
    with open(AP_LIST, "w") as f:
        data["2.4G"] = aps
        yaml.safe_dump(data, f, sort_keys=False)
    
    return static_template

TOTAL_STEPS = 48
SELECT = 0 # 0=RL Agent, 1=Event Loop

def main():
    global TOTAL_STEPS, SELECT
    print("--- RRM MASTER SIMULATION START ---")
    
    # --- 1. MATLAB Engine Setup ---
    print("Starting MATLAB Engine...")
    try:
        eng = matlab.engine.start_matlab()
    except Exception as e:
        print(f"FATAL: Error starting MATLAB engine: {e}")
        return

    project_root = os.path.dirname(src_folder)
    eng.cd(project_root)
    
    # --- 2. Static Environment Initialization (Runs ONLY ONCE) ---
    
    # Build 5 GHz static template (geometry and initial RRM state)
    print("\nInitializing 5G Static Geometry and Configuration...")
    static_template_5g = build_static_ap_template_5G(config_5g)
    
    # Build 2.4 GHz static template
    print("Initializing 2.4G Static Geometry and Configuration...")
    static_template_2g = build_static_ap_template_2g(config_2g)
    
    # Slicing constant to filter only Network 1 APs (columns 0, 3, 6, ...)
    NET1_SLICE = slice(0, None, 3) 
    episode_count = 0
    
    # ==============================================================
    # 3. INFINITE EPISODE LOOP
    # ==============================================================
    
    while True:
        episode_count += 1
        print("\n" + "#" * 80)
        print(f"### STARTING NEW RRM EPISODE: {episode_count} ###", flush=True)
        print("#" * 80)
        
        # --- A. Episode Reset ---
        
        # Reset current state to the static template (no history from previous episodes)
        current_state_5g = copy.deepcopy(static_template_5g)
        current_state_2g = copy.deepcopy(static_template_2g)

        # Reset aggregation storage for the new episode
        all_5g_final_matrices = [] 
        all_5g_rssi_matrices = []
        all_5g_overlap_matrices = []
        
        all_2g_final_matrices = []
        all_2g_rssi_matrices = []
        all_2g_overlap_matrices = []
        
        # ==============================================================
        # 4. TIME LOOP (I = 1 to 48) - Runs one full episode
        # ==============================================================
        if SELECT==0:
            globalconf2 = current_state_2g
            globalconf5 = current_state_5g

            
        print("this is before fos loop", SELECT, TOTAL_STEPS)
        k=0
        for step in range(TOTAL_STEPS):
            try:
                # --- B. RUN 5 GHz SIMULATION STEP ---
                sleep(1)
                print(SELECT, TOTAL_STEPS)
                current_state_5g, results_5g = run_5g_step(
                    eng, 
                    config_5g, 
                    globalconf5, 
                    static_template_5g, 
                    step, 
                    SELECT,
                    # Passed for RL observation aggregation (used at step 47)
                    all_5g_final_matrices, 
                    all_5g_rssi_matrices,
                    all_5g_overlap_matrices
                )
                out5, overlap5, rssi5 = get_5G_data(eng, config_5g, current_state_5g, step)
                out5 = out5.T
                embed5 = get_embeddings(out5, overlap5, rssi5)
                print(embed5)
                print("5G state check\n", current_state_5g)
                # ------------------------------------------------------------------
                # FILTER 5G RESULTS TO NETWORK 1 ONLY (12 APs / 12x12)
                # ------------------------------------------------------------------
                final_matrix_5g = np.array(results_5g['Final_Output_Matrix'])
                rssi_matrix_5g = np.array(results_5g['AP2AP_rssi_dbm'])
                overlap_matrix_5g = np.array(results_5g['Channel_Overlap_Matrix'])
                
                # Filter Final Output Matrix (107 rows, 36 columns -> 107 rows, 12 columns)
                final_matrix_12_5g = final_matrix_5g[:, NET1_SLICE]
                
                # Filter RSSI/Overlap Matrices (36x36 -> 12x12)
                rssi_matrix_12_5g = rssi_matrix_5g[NET1_SLICE, :][:, NET1_SLICE]
                overlap_matrix_12_5g = overlap_matrix_5g[NET1_SLICE, :][:, NET1_SLICE]
                
                # Store Filtered Data
                all_5g_final_matrices.append(final_matrix_12_5g)
                all_5g_rssi_matrices.append(rssi_matrix_12_5g)
                all_5g_overlap_matrices.append(overlap_matrix_12_5g)

                # Print detailed per-AP metrics 
                RRM_METRIC_ROWS_5G = {'P50_THROUGHPUT': 104, 'P95_RETRY_RATE': 105}
                p50_thr_5g = final_matrix_12_5g[RRM_METRIC_ROWS_5G['P50_THROUGHPUT'], :]
                p95_retry_5g = final_matrix_12_5g[RRM_METRIC_ROWS_5G['P95_RETRY_RATE'], :]
                
                print(f"[5G] P50 Throughput (12 APs, Mbps): {p50_thr_5g.round(2)}", flush=True)
                print(f"[5G] P95 Retry Rate (12 APs, %): {p95_retry_5g.round(2)}", flush=True)


                # --- C. RUN 2.4 GHz SIMULATION STEP ---
                
                current_state_2g, results_2g = run_2g_step(
                    eng, 
                    config_2g, 
                    globalconf2, 
                    static_template_2g, 
                    step, 
                    SELECT,
                    # Pass aggregation history for RL observation at step 48
                    all_2g_final_matrices, 
                    all_2g_rssi_matrices,
                    all_2g_overlap_matrices
                )
                out2, overlap2, rssi2 = get_2G_data(eng, config_2g, current_state_2g, step)
                out2 = out2.T
                embed2 = get_embeddings2(out2, overlap2, rssi2)
                print(embed2)
                print("2.4G state check\n", current_state_2g)
                # ------------------------------------------------------------------
                # FILTER 2.4G RESULTS TO NETWORK 1 ONLY (12 APs / 12x12)
                # ------------------------------------------------------------------
                final_matrix_2g = np.array(results_2g['Final_Output_Matrix'])
                rssi_matrix_2g = np.array(results_2g['AP2AP_rssi_dbm'])
                overlap_matrix_2g = np.array(results_2g['Channel_Overlap_Matrix'])

                # Filter Final Output Matrix (59 rows, 36 columns -> 59 rows, 12 columns)
                final_matrix_12_2g = final_matrix_2g[:, NET1_SLICE]

                # Filter RSSI/Overlap Matrices (36x36 -> 12x12)
                rssi_matrix_12_2g = rssi_matrix_2g[NET1_SLICE, :][:, NET1_SLICE]
                overlap_matrix_12_2g = overlap_matrix_2g[NET1_SLICE, :][:, NET1_SLICE]
                
                # Store Filtered Data
                all_2g_final_matrices.append(final_matrix_12_2g)
                all_2g_rssi_matrices.append(rssi_matrix_12_2g)
                all_2g_overlap_matrices.append(overlap_matrix_12_2g)

                # Print detailed per-AP metrics (P50 Thr is row 56, P95 Retry is row 57)
                RRM_METRIC_ROWS_2G = {'P50_THROUGHPUT': 56, 'P95_RETRY_RATE': 57}
                p50_thr_2g = final_matrix_12_2g[RRM_METRIC_ROWS_2G['P50_THROUGHPUT'], :]
                p95_retry_2g = final_matrix_12_2g[RRM_METRIC_ROWS_2G['P95_RETRY_RATE'], :]
                
                print(f"[2.4G] P50 Throughput (12 APs, Mbps): {p50_thr_2g.round(2)}", flush=True)
                print(f"[2.4G] P95 Retry Rate (12 APs, %): {p95_retry_2g.round(2)}", flush=True)
                

            except KeyboardInterrupt:
                # start the event loop
                SELECT = 1
                global_defaults, event_defaults, ap_list = load_defaults(DEFAULTS_YAML)
                print("\nKeyboardInterrupt → opening GUI...")
                gui = EventConfigGUI(global_defaults, event_defaults, ap_list)
                cfg = gui.result
                if cfg is None:
                    print("GUI canceled. Continuing...")
                    continue
                # SEPERATE CONFIGS FOR 2.4G AND 5G
                EVENT_TRIGGER_AP_CONFIG = cfg['AP_CONFIGS']
                # print(EVENT_TRIGGER_AP_CONFIG)
                EVENT_TRIGGER_TIME = cfg["run_until"] - NOW
                delta = datetime.timedelta(minutes = 5)
                TOTAL_STEPS = int(EVENT_TRIGGER_TIME / delta)
                print(int(EVENT_TRIGGER_TIME / delta))
                print("Config active for:", EVENT_TRIGGER_TIME)

                k=1
                CONFIG_2G = {}
                CONFIG_5G = {}
                for a in EVENT_TRIGGER_AP_CONFIG:
                    if a in ap_list["2.4G"]:
                        CONFIG_2G[a] = EVENT_TRIGGER_AP_CONFIG[a]
                    else:
                        CONFIG_5G[a] = EVENT_TRIGGER_AP_CONFIG[a]
                globalconf5 = config_conversion_5(CONFIG_5G, current_state_5g)
                globalconf2 = config_conversion(CONFIG_2G, current_state_2g)
                stat2, stat5 = globalconf2, globalconf5
                break
        if k==1:
            k=0
        elif SELECT==1:
                print("========== Event loop Done =================") 
                SELECT=0
                TOTAL_STEPS = 48
        # ==============================================================
        # 5. END OF EPISODE AGGREGATION (After 48 Steps)
        # ==============================================================
        
        print("\n--- EPISODE COMPLETE: Aggregating Final Data ---")
        
        # Set print options for visibility
        np.set_printoptions(precision=2, suppress=True, linewidth=150)
        
        # --- 5G AGGREGATION ---
        final_output_5g_stack = np.stack(all_5g_final_matrices, axis=2)
        mean_rssi_5g = np.mean(np.stack(all_5g_rssi_matrices), axis=0)
        latest_overlap_5g = all_5g_overlap_matrices[-1]
        
        print("\n" + "="*80)
        print(f"5G EPISODE {episode_count} AGGREGATED MATRICES (Network 1 Only)")
        print(f"Final Output Matrix Stack Shape (Metrics x APs x Steps): {final_output_5g_stack.shape}")
        print(f"Mean RSSI Coupling Matrix (12x12, Averaged over 48 Steps):")
        print(mean_rssi_5g)
        print(f"\nLatest Channel Overlap Matrix (12x12, From Step 48):")
        print(latest_overlap_5g)
        print("="*80)

        # --- 2.4G AGGREGATION ---
        final_output_2g_stack = np.stack(all_2g_final_matrices, axis=2)
        mean_rssi_2g = np.mean(np.stack(all_2g_rssi_matrices), axis=0)
        latest_overlap_2g = all_2g_overlap_matrices[-1]
        
        print(f"2.4G EPISODE {episode_count} AGGREGATED MATRICES (Network 1 Only)")
        print(f"Final Output Matrix Stack Shape (Metrics x APs x Steps): {final_output_2g_stack.shape}")
        print(f"Mean RSSI Coupling Matrix (12x12, Averaged over 48 Steps):")
        print(mean_rssi_2g)
        print(f"\nLatest Channel Overlap Matrix (12x12, From Step 48):")
        print(latest_overlap_2g)
        print("="*80)
        
        # --- Aggregated data (stacks and means) are now available for RL Trainer ---
        
        time.sleep(1) # Pause briefly before starting the next episode.

if __name__ == "__main__":

    main()
