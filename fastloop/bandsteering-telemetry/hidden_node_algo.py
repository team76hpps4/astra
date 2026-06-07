import json
import time
import os
import sys
from collections import deque, defaultdict
from cca_tm_algo import cca_tm_algo
from obsspd_algo import obsspd_algo

LOG_FILE_PATH = "/tmp/wifi.log"
MATRIX_FILE = "/tmp/interference_graph.json"
WINDOW_SIZE = 5 # for rolling mean of retry rate (to prevent flapping)

# Thresholds
RETRY_THRESHOLD = 50.0    

DIFF_THRESHOLD = 10.0        
# If (self - alien) pathloss is GREATER than this thresh, alien is strong -> obss useless, try cca.

ALIEN_DIFF_THRESHOLD = -10.0 
# If (self - alien) pathloss is LOWER than this thresh, alien is weak -> obsspd threshold change can help.

OBSSPD_SLOW_LOOP_THRESH = -82.0 # this value is supposed to come from slow loop (main controller) after intergration of both

def tail_log_file(filepath):
    """
    Continuously yields new lines appended to a log file (similar to 'tail -f').
    Ensures the file exists and waits when no new data is available.
    """
    try:
        if not os.path.exists(filepath): open(filepath, 'a').close()
        with open(filepath, "r") as f:
            f.seek(0, os.SEEK_END)
            while True:
                line = f.readline()
                if not line:
                    time.sleep(0.1)
                    continue
                yield line
    except KeyboardInterrupt:
        sys.exit()

def get_interference_matrix():
    """
    Reads and returns the interference matrix JSON file.
    Returns None if the file is missing or unreadable.
    """
    try:
        with open(MATRIX_FILE, 'r') as f: return json.load(f)
    except: return None

def process_client_trigger(client_mac, retry_val):
    """
    Handles a high retry-rate trigger for a client.
    Reads interference matrix, identifies strongest co-channel AP,
    and decides whether to run CCA or OBSSPD based on pathloss differences.
    """
    print(f"[Main] TRIGGER: {client_mac} Retry Rate ({retry_val:.2f}%) > Threshold")
    
    matrix_data = get_interference_matrix()
    if not matrix_data: return

    matrix = matrix_data['matrix']
    rows_clients = matrix_data['rows_clients']
    
    try:
        client_idx = rows_clients.index(client_mac)
    except ValueError:
        return

    client_row = matrix[client_idx]
    
    # self ap (column 0)
    self_entry = client_row[0]
    if not self_entry: return
    self_pathloss = self_entry[0]
    self_channel = self_entry[1]

    # find best cochannel ap
    best_co_pl = float('inf')
    best_co_idx = -1
    best_is_network = -1

    for col_idx, entry in enumerate(client_row):
        if col_idx == 0: continue 
        if entry is None: continue
        pl, ch, is_net = entry
        
        if ch == self_channel:
            if pl < best_co_pl:
                best_co_pl = pl
                best_co_idx = col_idx
                best_is_network = is_net

    if best_co_idx == -1: return

    diff1 = self_pathloss - best_co_pl
    
    if diff1 < DIFF_THRESHOLD:
    # hidden node detected
            
        if best_is_network == 1:
            # cca for network's ap
            cca_tm_algo(client_mac)
        else:
            # alien ap, try for obsspd
            diff2 = self_pathloss - best_co_pl
            
            if diff2 > ALIEN_DIFF_THRESHOLD:
                # obss useless, because alien ap is close to client
                cca_tm_algo(client_mac)
            else:
                # obss can help
                obsspd_algo(slow_loop_threshold=OBSSPD_SLOW_LOOP_THRESH)
    else:
        pass

def main():
    client_retry_history = defaultdict(lambda: deque(maxlen=WINDOW_SIZE))
    log_gen = tail_log_file(LOG_FILE_PATH)

    for line in log_gen:
        try:
            data = json.loads(line)
            if 'clients' not in data: continue

            for client in data['clients']:
                mac = client.get('client_mac')
                try:
                    retry_rate = client['packet_capture_stats']['client_to_ap']['retry_rate_percent']
                except: continue

                client_retry_history[mac].append(retry_rate)

                if len(client_retry_history[mac]) == WINDOW_SIZE:
                    avg_retry = sum(client_retry_history[mac]) / WINDOW_SIZE
                    if avg_retry > RETRY_THRESHOLD:
                        process_client_trigger(mac, avg_retry)
                        client_retry_history[mac].clear() # Reset after trigger
        except: continue

if __name__ == "__main__":
    main()