import numpy as np
import random
import sys
import os
import yaml
from Inter_IIT_Tech.src import DEFAULTS_YAML, AP_LIST

# --- PATH SETUP ---
src_folder = os.path.dirname(os.path.abspath(__file__))
if src_folder not in sys.path:
    sys.path.append(src_folder)

# --- PLANNER & RL IMPORTS (Closed Loop Integration) ---
from planner_2 import validate_and_commit_changes_2G, NUM_NETWORK_1_APS, RL_SPARSE_SIZE

# RL Agent Interface Import
from RL_interface2 import get_action_2G

# Import constants from the event module
try:
    from event import EVENT_DEFAULTS 
except ImportError:
    EVENT_DEFAULTS = {
        "moderate_busy": {
            "tx_power_dbm": 18.0, "min_obss_pd_dbm": -82.0, "channel_width_mhz": 40.0,
        }
    }

# -----------------------------------------------------------
# EVENT LOOP SUGGESTIONS (select = 1) 
# -----------------------------------------------------------

def get_event_suggestion(num_rooms_int, cfg):
    # """
    # Returns configuration derived from event defaults for 2.4G.
    # """
    
    # defaults = EVENT_DEFAULTS.get(event_type, EVENT_DEFAULTS['moderate_busy'])
    
    # tx_power = float(defaults['tx_power_dbm'])
    # obss_pd = float(defaults['min_obss_pd_dbm'])
    # cw = float(defaults['channel_width_mhz'])
    # channel = 6.0 # Default central non-overlapping channel
    
    # print(f"MUX Selection: 1 (Event RRM: {event_type} applied globally.)")
    
    # return (
    #     np.full(num_rooms_int, tx_power),
    #     np.full(num_rooms_int, obss_pd),
    #     np.full(num_rooms_int, cw),
    #     np.full(num_rooms_int, channel)
    # )
    
    # with open(AP_LIST, "r") as f:
    #     config = yaml.safe_load(f)
    # ap24_list = config.get("2.4G")
    # ap5_list = config.get("5G")
    # # print(ap5_list)
    # # print(cfg)
    
    # num2 = len(ap24_list)
    # num5 = len(ap5_list)
    
    tx_power = []
    obss_pd = []
    cw = []
    channel = []
    cfg2 = []
    for i in cfg:
        if i['network_id']==1: cfg2.append(i)
    
    for a in range(len(cfg2)):
        tx_power.append(cfg2[a]['tx_power_dbm'])
        cw.append(cfg2[a]['channel_width_mhz'])
        obss_pd.append(cfg2[a]['obss_pd_dbm'])
        channel.append(cfg2[a]['channel'])
    return (
        tx_power,
        obss_pd,
        cw,
        channel
    )

# -----------------------------------------------------------
# MUX FUNCTION (Main Export) - Executes RL/Planner Flow
# -----------------------------------------------------------

def generate_rrm_arrays(num_rooms_int, select, current_full_ap_configs, step, aggregation_history):
    """
    Muxing function to select AP configuration source based on the 'select' flag.
    
    Args:
        current_full_ap_configs (list): List of 36 AP dictionaries from the previous step.
        step (int): Current simulation step number (0 to 47).
        aggregation_history (tuple): Full list of historical matrices for RL aggregation at step 47.

    Returns:
        tuple: (room_tx_array, room_pd_array, room_cw_array, room_channel) 
    """
    
    # CRITICAL STEP 1: Filter the full 36 AP list down to the 12 managed APs (Network 1)
    current_net1_configs = [ap for ap in current_full_ap_configs if ap['network_id'] == 1.0]

    if select == 1:
        # --- PATH 1: EVENT LOOP ---
        return get_event_suggestion(num_rooms_int, current_full_ap_configs)
    
    else:
        # --- PATH 0: RL AGENT (Closed Loop) ---
        print("MUX Selection: 0 (RL Agent Suggested Configuration)", flush=True)
        
        # 2. RL PREDICTION: Get sparse proposed actions
        # (This is where the RL agent uses the state data and proposes changes)
        rl_ap_indices_sparse, rl_tx_dbm_sparse, rl_pd_dbm_sparse, rl_channel_sparse, rl_cw_mhz_sparse = \
            get_action_2G(current_net1_configs, step, aggregation_history)

        # 3. PLANNER VALIDATION AND COMMIT (The Safety Gate)
        # The planner checks hysteresis and guardrails against the current configuration.
        committed_matrix = validate_and_commit_changes_2G(
            current_net1_configs, 
            rl_ap_indices_sparse,
            rl_tx_dbm_sparse,
            rl_pd_dbm_sparse,
            rl_channel_sparse,
            rl_cw_mhz_sparse
        )
        
        # 4. Restructure Output (4x12 Committed Matrix -> 4 Size 12 Room Arrays)
        room_tx_array = committed_matrix[0, :]
        room_pd_array = committed_matrix[1, :]
        room_channel = committed_matrix[2, :]
        room_cw_array = committed_matrix[3, :]

        return room_tx_array, room_pd_array, room_cw_array, room_channel
    
    
def config_conversion(EVENT_STATE, static_template):
    '''
    Docstring for config_conversion
    [{'pos': matlab.double([[30.56735647797323,90.30637770136039]]), 'network_id': 1.0, 'tx_power_dbm': 21.0, 'channel_width_mhz': 80.0, 'obss_pd_dbm': -65.0, 'channel': 36.0}, 
    {'pos': matlab.double([[40.567356477973235,110.30637770136039]]), 'network_id': 2.0, 'tx_power_dbm': 21.0, 'channel_width_mhz': 80.0, 'obss_pd_dbm': -65.0, 'channel': 48.0}, 
    {'pos': matlab.double([[50.567356477973235,90.30637770136039]]), 'network_id': 3.0, 'tx_power_dbm': 21.0, 'channel_width_mhz': 80.0, 'obss_pd_dbm': -65.0, 'channel': 161.0}, 
    {'pos': matlab.double([[57.537853305734295,-6.6258771663384195]]), 'network_id': 1.0, 'tx_power_dbm': 21.0, 'channel_width_mhz': 80.0, 'obss_pd_dbm': -65.0, 'channel': 36.0}, 
    {'pos': matlab.double([[67.5378533057343,13.37412283366158]]), 'network_id': 2.0, 'tx_power_dbm': 21.0, 'channel_width_mhz': 80.0, 'obss_pd_dbm': -65.0, 'channel': 48.0}, {'pos': matlab.double([[77.5378533057343,-6.6258771663384195]]), 'network_id': 3.0, 'tx_power_dbm': 21.0, 'channel_width_mhz': 80.0, 'obss_pd_dbm': -65.0, 'channel': 161.0}, {'pos': matlab.double([[88.13542299761993,122.9882541447571]]), 'network_id': 1.0, 'tx_power_dbm': 21.0, 'channel_width_mhz': 80.0, 'obss_pd_dbm': -65.0, 'channel': 36.0}, {'pos': matlab.double([[98.13542299761993,142.9882541447571]]), 'network_id': 2.0, 'tx_power_dbm': 21.0, 'channel_width_mhz': 80.0, 'obss_pd_dbm': -65.0, 'channel': 48.0}, {'pos': matlab.double([[108.13542299761993,122.9882541447571]]), 'network_id': 3.0, 'tx_power_dbm': 21.0, 'channel_width_mhz': 80.0, 'obss_pd_dbm': -65.0, 'channel': 161.0}, {'pos': matlab.double([[-32.502547006862486,37.88316219974699]]), 'network_id': 1.0, 'tx_power_dbm': 21.0, 'channel_width_mhz': 80.0, 'obss_pd_dbm': -65.0, 'channel': 36.0}, {'pos': matlab.double([[-22.502547006862486,57.88316219974699]]), 'network_id': 2.0, 'tx_power_dbm': 21.0, 'channel_width_mhz': 80.0, 'obss_pd_dbm': -65.0, 'channel': 48.0}, {'pos': matlab.double([[-12.502547006862486,37.88316219974699]]), 'network_id': 3.0, 'tx_power_dbm': 21.0, 'channel_width_mhz': 80.0, 'obss_pd_dbm': -65.0, 'channel': 161.0}, {'pos': matlab.double([[146.47403632040863,17.34447830590279]]), 'network_id': 1.0, 'tx_power_dbm': 21.0, 'channel_width_mhz': 80.0, 'obss_pd_dbm': -65.0, 'channel': 36.0}, {'pos': matlab.double([[156.47403632040863,37.34447830590279]]), 'network_id': 2.0, 'tx_power_dbm': 21.0, 'channel_width_mhz': 80.0, 'obss_pd_dbm': -65.0, 'channel': 48.0}, {'pos': matlab.double([[166.47403632040863,17.34447830590279]]), 'network_id': 3.0, 'tx_power_dbm': 21.0, 'channel_width_mhz': 80.0, 'obss_pd_dbm': -65.0, 'channel': 161.0}, {'pos': matlab.double([[35.28350246745303,162.60459564560216]]), 'network_id': 1.0, 'tx_power_dbm': 21.0, 'channel_width_mhz': 80.0, 'obss_pd_dbm': -65.0, 'channel': 36.0}, {'pos': matlab.double([[45.28350246745303,182.60459564560216]]), 'network_id': 2.0, 'tx_power_dbm': 21.0, 'channel_width_mhz': 80.0, 'obss_pd_dbm': -65.0, 'channel': 48.0}, {'pos': matlab.double([[55.28350246745303,162.60459564560216]]), 'network_id': 3.0, 'tx_power_dbm': 21.0, 'channel_width_mhz': 80.0, 'obss_pd_dbm': -65.0, 'channel': 161.0}, {'pos': matlab.double([[-11.4365254839675,-40.78147672568507]]), 'network_id': 1.0, 'tx_power_dbm': 21.0, 'channel_width_mhz': 80.0, 'obss_pd_dbm': -65.0, 'channel': 36.0}, {'pos': matlab.double([[-1.4365254839675003,-20.781476725685067]]), 'network_id': 2.0, 'tx_power_dbm': 21.0, 'channel_width_mhz': 80.0, 'obss_pd_dbm': -65.0, 'channel': 48.0}, {'pos': matlab.double([[8.5634745160325,-40.78147672568507]]), 'network_id': 3.0, 'tx_power_dbm': 21.0, 'channel_width_mhz': 80.0, 'obss_pd_dbm': -65.0, 'channel': 161.0}, {'pos': matlab.double([[173.92795220220563,94.18560229467352]]), 'network_id': 1.0, 'tx_power_dbm': 21.0, 'channel_width_mhz': 80.0, 'obss_pd_dbm': -65.0, 'channel': 36.0}, {'pos': matlab.double([[183.92795220220563,114.18560229467352]]), 'network_id': 2.0, 'tx_power_dbm': 21.0, 'channel_width_mhz': 80.0, 'obss_pd_dbm': -65.0, 'channel': 48.0}, {'pos': matlab.double([[193.92795220220563,94.18560229467352]]), 'network_id': 3.0, 'tx_power_dbm': 21.0, 'channel_width_mhz': 80.0, 'obss_pd_dbm': -65.0, 'channel': 161.0}, {'pos': matlab.double([[-70.12520420615652,99.63902234642482]]), 'network_id': 1.0, 'tx_power_dbm': 21.0, 'channel_width_mhz': 80.0, 'obss_pd_dbm': -65.0, 'channel': 36.0}, {'pos': matlab.double([[-60.125204206156525,119.63902234642482]]), 'network_id': 2.0, 'tx_power_dbm': 21.0, 'channel_width_mhz': 80.0, 'obss_pd_dbm': -65.0, 'channel': 48.0}, {'pos': matlab.double([[-50.125204206156525,99.63902234642482]]), 'network_id': 3.0, 'tx_power_dbm': 21.0, 'channel_width_mhz': 80.0, 'obss_pd_dbm': -65.0, 'channel': 161.0}, {'pos': matlab.double([[103.09456597206716,-78.65418059979572]]), 'network_id': 1.0, 'tx_power_dbm': 21.0, 'channel_width_mhz': 80.0, 'obss_pd_dbm': -65.0, 'channel': 36.0}, {'pos': matlab.double([[113.09456597206716,-58.65418059979572]]), 'network_id': 2.0, 'tx_power_dbm': 21.0, 'channel_width_mhz': 80.0, 'obss_pd_dbm': -65.0, 'channel': 48.0}, {'pos': matlab.double([[123.09456597206716,-78.65418059979572]]), 'network_id': 3.0, 'tx_power_dbm': 21.0, 'channel_width_mhz': 80.0, 'obss_pd_dbm': -65.0, 'channel': 161.0}, {'pos': matlab.double([[69.87868606552144,201.45811517449584]]), 'network_id': 1.0, 'tx_power_dbm': 21.0, 'channel_width_mhz': 80.0, 'obss_pd_dbm': -65.0, 'channel': 36.0}, {'pos': matlab.double([[79.87868606552144,221.45811517449584]]), 'network_id': 2.0, 'tx_power_dbm': 21.0, 'channel_width_mhz': 80.0, 'obss_pd_dbm': -65.0, 'channel': 48.0}, {'pos': matlab.double([[89.87868606552144,201.45811517449584]]), 'network_id': 3.0, 'tx_power_dbm': 21.0, 'channel_width_mhz': 80.0, 'obss_pd_dbm': -65.0, 'channel': 161.0}, {'pos': matlab.double([[-92.99408140156649,1.5955744621669936]]), 'network_id': 1.0, 'tx_power_dbm': 21.0, 'channel_width_mhz': 80.0, 'obss_pd_dbm': -65.0, 'channel': 36.0}, {'pos': matlab.double([[-82.99408140156649,21.595574462166994]]), 'network_id': 2.0, 'tx_power_dbm': 21.0, 'channel_width_mhz': 80.0, 'obss_pd_dbm': -65.0, 'channel': 48.0}, {'pos': matlab.double([[-72.99408140156649,1.5955744621669936]]), 'network_id': 3.0, 'tx_power_dbm': 21.0, 'channel_width_mhz': 80.0, 'obss_pd_dbm': -65.0, 'channel': 161.0}]  
    :param EVENT_STATE: Description
    '''
    event_list = list(EVENT_STATE.values())
    for i in range(0, len(static_template), 3):
        static_template[i]['tx_power_dbm'] = event_list[i%3]['tx_power_dbm']
        static_template[i]['channel_width_mhz'] = event_list[i%3]['channel_width_mhz']
        static_template[i]['obss_pd_dbm'] = event_list[i%3]['obss_pd_dbm']
        static_template[i]['channel'] = event_list[i%3]['channel']
    return static_template