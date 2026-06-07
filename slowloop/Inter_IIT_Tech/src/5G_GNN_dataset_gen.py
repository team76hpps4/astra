import matlab.engine
import math
import random
import numpy as np
import time
import os
import copy

# ==========================================
# CONSTANTS & CONFIG (5 GHz)
# ==========================================
ROOM_COUNTS = [8, 10, 12, 14, 16, 26] 
GEOMS_PER_N = 6
RUNS_PER_GEOM = 50
DATASET_DIR = "dataset_output_5G"

# Standard 5 GHz Channels (UNII-1, 2A, 2C, 3)
CHANNELS_5G = [36, 40, 44, 48, 52, 56, 60, 64, 
               100, 104, 108, 112, 116, 120, 124, 128, 132, 136, 140, 144, 
               149, 153, 157, 161, 165]

def get_base_geometry_5G(num_rooms, seed):
    """ Generates AP positions (Golden Spiral). """
    random.seed(seed)
    np.random.seed(seed)
    
    ap_configs_list = []
    # Slightly larger spacing for 5G rooms usually, but keeping consistent with physics model
    center_x, center_y = 50.0, 50.0
    spread_factor = 45.0
    golden_angle = math.pi * (3 - math.sqrt(5))
    rng = random.Random(seed)

    idx = 1
    for r in range(1, num_rooms + 1):
        radius = spread_factor * math.sqrt(r)
        theta = r * golden_angle
        theta_jit = theta + (rng.random() - 0.5) * 0.5
        radius_jit = radius + (rng.random() - 0.5) * 5.0
        
        room_x = center_x + radius_jit * math.cos(theta_jit)
        room_y = center_y + radius_jit * math.sin(theta_jit)
        
        # 3 APs per room
        offsets = [(5, 5), (15, 25), (25, 5)]

        for k in range(3):
            ap_struct = {
                'pos': matlab.double([room_x + offsets[k][0], room_y + offsets[k][1]]),
                'network_id': float((idx - 1) % 3 + 1),
                # Placeholders
                'tx_power_dbm': 0.0, 
                'channel_width_mhz': 0.0, 
                'obss_pd_dbm': 0.0, 
                'channel': 36.0 
            }
            ap_configs_list.append(ap_struct)
            idx += 1
            
    return ap_configs_list

def randomize_parameters_5G(ap_configs, num_rooms, seed):
    """ Randomizes 5G Params: Higher BW options, 5G Channels. """
    np.random.seed(seed)
    
    # 1. Generate Per-Room Parameters
    # 5 GHz Tx Power typically higher (14 to 23 dBm)
    room_tx = np.random.uniform(14.0, 23.0, num_rooms)
    
    # OBSS PD (-82 to -62)
    room_pd = np.random.uniform(-82.0, -62.0, num_rooms)
    
    # 5G Bandwidths: 20, 40, 80, 160 MHz
    room_cw = np.random.choice([20.0, 40.0, 80.0, 160.0], num_rooms, p=[0.1, 0.2, 0.5, 0.2])
    
    new_configs = copy.deepcopy(ap_configs)
    
    for r_idx in range(num_rooms):
        # Pick 3 random channels for this room from the 5G list
        # We pick indices to ensure we stay within list bounds
        ch_indices = np.random.choice(len(CHANNELS_5G), 3, replace=False)
        room_channels = [CHANNELS_5G[i] for i in ch_indices]
        
        for k in range(3):
            ap_idx = (r_idx * 3) + k
            new_configs[ap_idx]['tx_power_dbm'] = float(room_tx[r_idx])
            new_configs[ap_idx]['obss_pd_dbm'] = float(room_pd[r_idx])
            new_configs[ap_idx]['channel_width_mhz'] = float(room_cw[r_idx])
            new_configs[ap_idx]['channel'] = float(room_channels[k])
            
    return new_configs

def main():
    print("==================================================")
    print("      5GHz DATASET GENERATOR (PYTHON -> MATLAB)   ")
    print("==================================================")
    
    # 1. SETUP PATHS
    src_folder = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(src_folder)
    
    # 2. START ENGINE
    print("Starting MATLAB Engine...")
    eng = matlab.engine.start_matlab()
    print(f"Navigating to: {project_root}")
    eng.cd(project_root)
    
    # 3. 5G CONFIGURATION (Matches default_config_5G structure)
    config = {
        'random_seed': 123,
        
        # Speed Optimizations
        'sim_duration_s': 0.5, 
        'dt_ms': 20.0,         
        
        # 5G Specifics
        'channel_width_mhz': 80.0, 
        'noise_figure_db': 7.0,
        'noise_floor_dbm': -95.0,
        'noise_variation_frac': 0.03,
        'short_term_shadowing_sigma': 6.0,
        'shadowing_sigma': 4.0,
        'cca_threshold_dbm': -72.0, # Generally higher in 5G
        'room_size': matlab.double([20, 20]),
        'num_rooms': 0.0,
        'ap_per_room': 3.0,
        'client_grid_spacing': 5.0,
        
        # Interferers (BT/ZB less prevalent in 5G, but we keep logic just in case or set to 0)
        'bt': {'count': 0.0, 'tx_power_dbm': 0.0, 'duty_cycle': 0.0},
        'zb': {'count': 0.0, 'tx_power_dbm': 0.0, 'duty_cycle': 0.0},
        
        # 5G Pathloss (n=4.0)
        'pathloss': {'n_exp': 4.0, 'wall_loss_db': 15.0, 'PL_d0_dB': 36.0, 'd0': 1.0}
    }

    # Pass 5G Channel List to Config (though logic uses AP config mostly)
    config['channels'] = matlab.double(CHANNELS_5G)

    total_runs = len(ROOM_COUNTS) * GEOMS_PER_N * RUNS_PER_GEOM
    current_run = 0
    start_time = time.time()

    # ==========================================
    # 4. HIERARCHICAL LOOPS
    # ==========================================
    for N in ROOM_COUNTS:
        print(f"\n---> Processing Room Count: {N}")
        
        n_dir = os.path.join(project_root, DATASET_DIR, f"rooms_{N:02d}")
        
        for G in range(GEOMS_PER_N):
            print(f"  |--> Geometry {G+1}/{GEOMS_PER_N}")
            
            g_dir = os.path.join(n_dir, f"geom_{G}")
            os.makedirs(g_dir, exist_ok=True)
            
            geom_seed = hash((N, G)) % (2**32)
            base_ap_configs = get_base_geometry_5G(N, geom_seed)
            
            for R in range(RUNS_PER_GEOM):
                current_run += 1
                
                # B. Randomize Parameters
                run_seed = hash((N, G, R)) % (2**32)
                final_ap_configs = randomize_parameters_5G(base_ap_configs, N, run_seed)
                
                # Update Config Num Rooms
                config['num_rooms'] = float(N)

                # D. Send to MATLAB
                eng.workspace['temp_config_cell'] = final_ap_configs
                eng.eval("ap_configs = [temp_config_cell{:}];", nargout=0)
                eng.workspace['config'] = config
                
                # E. Run Simulation (CALLING 5G FUNCTION)
                eng.eval("res = simulate_environment_5G(config, ap_configs);", nargout=0)
                
                # F. Extract and Save
                try:
                    rssi_mat = np.array(eng.eval("res.AP2AP_rssi_dbm"))
                    output_mat = np.array(eng.eval("res.Final_Output_Matrix"))
                    overlap_mat = np.array(eng.eval("res.Channel_Overlap_Matrix"))
                    
                    np.save(os.path.join(g_dir, f"snapshot_{R:03d}_output.npy"), output_mat)
                    np.save(os.path.join(g_dir, f"snapshot_{R:03d}_rssi.npy"), rssi_mat)
                    np.save(os.path.join(g_dir, f"snapshot_{R:03d}_overlap.npy"), overlap_mat)
                    
                    if current_run % 10 == 0:
                        elapsed = time.time() - start_time
                        avg_time = elapsed / current_run
                        remaining = (total_runs - current_run) * avg_time
                        print(f"      Run {R+1}/{RUNS_PER_GEOM} (Total {current_run}/{total_runs}) - ETA: {remaining/60:.1f} min")
                        
                except Exception as e:
                    print(f"      [ERROR] Run {R} failed: {e}")

    print("\n5G Dataset Generation Complete.")
    eng.quit()

if __name__ == "__main__":
    main()