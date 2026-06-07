#!/usr/bin/env python3

import sys
import json
import time
import subprocess
import select
import os
import fcntl
import csv
from datetime import datetime

# --- Constants ---
# Metric calculation
THRESH = 50.0
WEIGHT_RSSI = 0.5
WEIGHT_SNR = 0.5
ACK_TIMING_VARIANCE = 0.0
WEIGHT_ACK = 0.3
WEIGHT_RETRY_ASYM = 0.4
WEIGHT_RATE_TX_RX = 0.3

# Steering logic
ASYM_THRESH = 1.5           # Asym_Score *above* this triggers steering
RSSI_STEERING_TRIGGER_THRESHOLD = 30.0 # RSSI_Score *below* this triggers steering
BSS_SCORE_THRESHOLD = 5.0   # Required score improvement to steer
CLIENT_REQUEST_TIMEOUT = 10.0 # Seconds to wait for a client report

# New AP Score Formula Constants
TLOW = -65.0                 # RSSI threshold for penalty
THIGH = -50.0                # RSSI threshold for reward
MAX_CU = 60.0                # Channel Utilization % threshold for penalty
RSSI_PENALTY_WEIGHT = 1.0    # Weight for RSSI penalty
RSSI_REWARD_WEIGHT = 1.0     # Weight for RSSI reward
CU_PENALTY_WEIGHT = 0.5      # Weight for CU penalty

# Logging
CSV_LOG_FILE = "post_transition.csv"

# --- ubus Synchronous Call ---

def _run_ubus_command(args):
    """
    Runs a synchronous ubus command and returns the parsed JSON output.
    """
    command = ['ubus'] + args
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=True, timeout=5)
        if result.stdout:
            return json.loads(result.stdout)
        return {}
    except subprocess.CalledProcessError as e:
        print(f"Error: ubus command failed: {' '.join(command)}\nStderr: {e.stderr}", file=sys.stderr)
    except json.JSONDecodeError:
        print(f"Error: Failed to decode ubus JSON: {result.stdout}", file=sys.stderr)
    except subprocess.TimeoutExpired:
        print(f"Error: ubus command timed out: {' '.join(command)}", file=sys.stderr)
    return None

# --- ubus Asynchronous Triggers ---

def _trigger_beacon_request(iface, client_mac):
    """Triggers an 802.11k beacon table request (mode 2)."""
    print(f"Info: [ubus] Triggering Beacon Request to {client_mac} on {iface}", file=sys.stderr)
    payload = json.dumps({
        'addr': client_mac, 'mode': 2, 'op_class': 0,
        'channel': 0, 'bssid': 'ff:ff:ff:ff:ff:ff'
    })
    try:
        subprocess.run(['ubus', 'call', iface, 'rrm_beacon_req', payload],
                       capture_output=True, text=True, timeout=2, check=True)
        return True
    except Exception as e:
        print(f"Warn: Failed to send beacon request: {e}", file=sys.stderr)
        return False

def _trigger_link_measurement_request(iface, client_mac):
    """Triggers an 802.11k link measurement request."""
    print(f"Info: [ubus] Triggering Link Measurement Request to {client_mac}", file=sys.stderr)
    payload = json.dumps({'addr': client_mac})
    try:
        subprocess.run(['ubus', 'call', iface, 'rrm_link_measurement_req', payload],
                       capture_output=True, text=True, timeout=2, check=True)
        return True
    except Exception as e:
        print(f"Warn: Failed to send link measurement request: {e}", file=sys.stderr)
        return False

def _trigger_bss_transition_request(iface, client_mac, neighbors):
    """Sends an 802.11v BSS transition request (synchronous command)."""
    neighbor_str = ", ".join(neighbors)
    print(f"Info: [ubus] Sending BSS Transition to {client_mac} on {iface} with neighbors: [{neighbor_str}]", file=sys.stderr)
    
    request_payload = json.dumps({
        'addr': client_mac,
        'duration': 10,
        'neighbors': neighbors
    })
    
    result = _run_ubus_command(['call', iface, 'wnm_disassoc_imminent', request_payload])
    if result is None:
        print(f"Error: Failed to send BSS transition request to {client_mac}", file=sys.stderr)
        return False
    else:
        print(f"Info: BSS transition request sent. ubus result: {result}", file=sys.stderr)
        return True


# --- Core Logic Classes ---

class ClientMonitor:
    """Manages the state and metrics for a single client."""
    def __init__(self, mac):
        self.mac = mac
        self.current_ap_bssid = None
        self.iface = None # hostapd iface
        
        # Calculated metrics
        self.asym_score = 0.0
        self.rssi_score = 0.0
        
        # State machine
        self.state = "idle"
        self.state_timestamp = 0.0
        
        # Client capabilities
        self.supports_lmr = False
        
        # Temporary data for multi-step operations
        self.steering_candidate_ap = None
        self.steering_current_ap_entry = None
        self.steering_other_neighbors = []
        self.steering_new_ap_score = 0.0
        self.last_steer_attempt_data = {}

    def update_metrics(self, client_data):
        """Updates metrics from the JSON log."""
        try:
            packet_stats = client_data.get('packet_capture_stats', {})
            client_to_ap = packet_stats.get('client_to_ap', {})
            ap_to_client = packet_stats.get('ap_to_client', {})
            
            rx_packet = client_to_ap.get('total_packets', 0)
            tx_packet = ap_to_client.get('total_packets', 0)
            rx_retry_asym = client_to_ap.get('retry_rate_percent', 0.0)
            tx_retry_asym = ap_to_client.get('retry_rate_percent', 0.0)

            phy_stats = client_data.get('phy_layer_snapshot_stats', {})
            rssi = phy_stats.get('rssi_dbm', -100.0)
            snr = phy_stats.get('snr_db', 0)
            rate_tx_rx = float(phy_stats.get('tx_rx_rate_delta_percent', "0.0"))

            # 1. Retry Asymmetry
            rx_comp = (rx_retry_asym * ((rx_packet / THRESH) / ((rx_packet / THRESH) + 1))) if THRESH > 0 else 0
            tx_comp = (tx_retry_asym * ((tx_packet / THRESH) / ((tx_packet / THRESH) + 1))) if THRESH > 0 else 0
            self.asym_score = (WEIGHT_ACK * ACK_TIMING_VARIANCE) + \
                              (WEIGHT_RETRY_ASYM * (rx_comp + tx_comp)) + \
                              (WEIGHT_RATE_TX_RX * rate_tx_rx)

            # 2. RSSI Score (from JSON log)
            self.rssi_score = (WEIGHT_RSSI * (100 + rssi)) + (WEIGHT_SNR * snr)
            
        except Exception as e:
            print(f"Error updating metrics for {self.mac}: {e}", file=sys.stderr)

    def set_state(self, new_state):
        self.state = new_state
        self.state_timestamp = time.time()
        print(f"Info: Client {self.mac} state -> {new_state}", file=sys.stderr)

    def clear_steering_data(self):
        self.steering_candidate_ap = None
        self.steering_current_ap_entry = None
        self.steering_other_neighbors = []
        self.steering_new_ap_score = 0.0


class NetworkOrchestrator:
    """Manages clients and orchestrates steering decisions."""
    def __init__(self, ap_mac, csv_writer, csv_file):
        self.clients = {}  # {mac: ClientMonitor}
        self.ap_mac = ap_mac
        self.csv_writer = csv_writer
        self.csv_file = csv_file
        self.hostapd_ifaces = self._get_hostapd_ifaces()
        if not self.hostapd_ifaces:
            print("CRITICAL: No hostapd interfaces found. Exiting.", file=sys.stderr)
            sys.exit(1)
        print(f"Info: Orchestrator started for AP: {self.ap_mac} on {self.hostapd_ifaces}", file=sys.stderr)

    def _get_hostapd_ifaces(self):
        ifaces = _run_ubus_command(['list', 'hostapd.*'])
        return list(ifaces.keys()) if ifaces else []

    def _find_client_hostapd_iface(self, client_mac):
        """Finds the hostapd interface and client data for a given MAC."""
        for iface in self.hostapd_ifaces:
            clients_data = _run_ubus_command(['call', iface, 'get_clients'])
            if clients_data and 'clients' in clients_data:
                for mac, info in clients_data['clients'].items():
                    if mac.lower() == client_mac.lower():
                        return iface, info
        return None, None

    def _check_client_capabilities(self, client_info):
        """Helper to parse 802.11k/v capabilities."""
        rrm_caps = client_info.get('rrm_caps', [])
        wnm_caps = client_info.get('wnm_caps', {})

        supports_k = len(rrm_caps) > 0
        supports_v = wnm_caps.get('bss_transition', False)
        
        # Check for Link Measurement support (RRM Cap Byte 0, Bit 0)
        supports_lmr = False
        if rrm_caps and (rrm_caps[0] & 0x01):
            supports_lmr = True
            
        return supports_k, supports_v, supports_lmr

    def _calculate_ap_score(self, rssi, channel_utilization=None):
        """
        Calculates the score for a single AP based on new formula.
        """
        score = 0.0

        if rssi is None:
            return 0.0 # Cannot score without RSSI
            
        # Base score from RSSI (e.g., -70dBm = 30 points)
        score += (100 + rssi)

        # Apply RSSI penalty
        if rssi < TLOW:
            score -= (TLOW - rssi) * RSSI_PENALTY_WEIGHT

        # Apply RSSI reward
        if rssi > THIGH:
            score += (rssi - THIGH) * RSSI_REWARD_WEIGHT
            
        # Apply Channel Utilization penalty
        if channel_utilization is not None and channel_utilization > MAX_CU:
            score -= (channel_utilization - MAX_CU) * CU_PENALTY_WEIGHT

        return score

    def _parse_link_report(self, report_data):
        """
        Parses the raw link measurement report body (hex string)
        to extract RCPI and convert it to RSSI.
        Returns RSSI (float) or None.
        """
        try:
            # report_data is a hex string like "3c00c0...".
            # The RCPI is byte 10 (index 9) of the report body.
            rcpi_hex = report_data[18:20]
            rcpi = int(rcpi_hex, 16)
            
            if rcpi > 0: # RCPI is not 0 (undefined)
                # Convert RCPI to RSSI: RSSI = (RCPI / 2) - 110
                rssi = (rcpi / 2.0) - 110.0
                print(f"Info: Parsed Link Report: RCPI={rcpi}, RSSI={rssi:.2f}dBm", file=sys.stderr)
                return rssi
        except Exception as e:
            print(f"Error: Failed to parse link report body: {e}", file=sys.stderr)
        
        return None # Default

    def log_transition_attempt(self, client_mac, status, prev_ap, prev_rssi, 
                               new_ap, new_rssi, disassoc_imm, lmr_supported):
        """Writes a BSS transition attempt to the CSV log."""
        try:
            timestamp = datetime.now().isoformat()
            self.csv_writer.writerow([
                timestamp, client_mac,
                timestamp, # disassoc_time (using current time)
                prev_ap, new_ap,
                f"{prev_rssi:.2f}" if prev_rssi is not None else 'nan',
                f"{new_rssi:.2f}" if new_rssi is not None else 'nan',
                disassoc_imm,
                status, 
                1 if lmr_supported else 0
            ])
            self.csv_file.flush() # Ensure it's written immediately
        except Exception as e:
            print(f"Error: Failed to write to CSV log: {e}", file=sys.stderr)

    def check_client_timeouts(self):
        """Time out stale client requests."""
        now = time.time()
        for client in self.clients.values():
            if client.state == "idle":
                continue

            if (now - client.state_timestamp > CLIENT_REQUEST_TIMEOUT):
                print(f"Warn: Client {client.mac} timed out in state {client.state}", file=sys.stderr)
                
                if client.state == "awaiting_bss_tm_response":
                    # Log timeout
                    data = client.last_steer_attempt_data
                    self.log_transition_attempt(
                        client.mac, "timeout_no_response",
                        data.get('prev_ap'), data.get('prev_ap_rssi'),
                        data.get('new_ap'), data.get('new_ap_rssi'),
                        True, client.supports_lmr
                    )
                
                elif client.state == "awaiting_link_measurement_for_dawn":
                    # DAWN logic timed out, fallback to JSON RSSI
                    print(f"Info: DAWN Link Measurement timed out. Falling back to JSON RSSI.", file=sys.stderr)
                    current_ap_score = client.rssi_score # Use score from log
                    new_ap_score = client.steering_new_ap_score
                    self.finalize_steering_decision(client, new_ap_score, current_ap_score, None) # No RSSI available

                client.set_state("idle")
                client.clear_steering_data()

    def process_json_log(self, data):
        """Handles a new JSON log object from stdin."""
        self.ap_mac = data.get("ap_mac", self.ap_mac)
        
        for client_data in data.get('clients', []):
            client_mac = client_data.get("client_mac")
            if not client_mac: continue

            if client_mac not in self.clients:
                self.clients[client_mac] = ClientMonitor(client_mac)
                print(f"Info: New client detected: {client_mac}", file=sys.stderr)
            
            client = self.clients[client_mac]
            client.current_ap_bssid = self.ap_mac
            client.update_metrics(client_data)

            # --- Steering Logic Triggers ---
            if client.state != "idle":
                continue # Client is busy with another operation

            # Trigger 1: High Asymmetry Score
            if client.asym_score > ASYM_THRESH:
                print(f"Info: Client {client.mac} crossed Asym_Score threshold ({client.asym_score:.2f} > {ASYM_THRESH}).", file=sys.stderr)
                self.start_k_steering_evaluation(client)
            
            # Trigger 2: Low RSSI Score
            elif client.rssi_score < RSSI_STEERING_TRIGGER_THRESHOLD:
                print(f"Info: Client {client.mac} crossed RSSI_Score threshold ({client.rssi_score:.2f} < {RSSI_STEERING_TRIGGER_THRESHOLD}).", file=sys.stderr)
                self.start_dawn_steering_evaluation(client)

    def start_k_steering_evaluation(self, client):
        """(Asym. Score) Step 1: Check caps and send beacon request."""
        iface, client_info = self._find_client_hostapd_iface(client.mac)
        if not iface:
            print(f"Warn: (Asym) Could not find {client.mac} on any iface.", file=sys.stderr)
            return

        client.iface = iface
        supports_k, supports_v, supports_lmr = self._check_client_capabilities(client_info)
        client.supports_lmr = supports_lmr # Store for logging

        if not (supports_k and supports_v):
            print(f"Info: (Asym) Client {client.mac} does not support 802.11k/v. Ignoring.", file=sys.stderr)
            return

        if _trigger_beacon_request(client.iface, client.mac):
            client.set_state("awaiting_beacon_report")
        else:
            print(f"Error: (Asym) Failed to send beacon request to {client.mac}.", file=sys.stderr)

    def start_dawn_steering_evaluation(self, client):
        """(RSSI Score) Step 1: Get DAWN map and find best AP."""
        iface, client_info = self._find_client_hostapd_iface(client.mac)
        if not iface:
            print(f"Warn: (DAWN) Could not find {client.mac} on any iface.", file=sys.stderr)
            return
        
        client.iface = iface
        supports_k, supports_v, supports_lmr = self._check_client_capabilities(client_info)
        client.supports_lmr = supports_lmr # Store for logging
        
        if not supports_v: # Only need 11v for DAWN steering
            print(f"Info: (DAWN) Client {client.mac} does not support 802.11v. Ignoring.", file=sys.stderr)
            return

        hearing_map = _run_ubus_command(['call', 'dawn', 'get_hearing_map'])
        if not hearing_map:
            print("Warn: (DAWN) Failed to get DAWN hearing map.", file=sys.stderr)
            return

        best_ap = None
        best_rssi = -100

        for bssid, data in hearing_map.get('clients', {}).get(client.mac, {}).items():
            if bssid.lower() == client.current_ap_bssid.lower():
                continue # Skip current AP
            
            rssi = data.get('rssi', -100)
            if rssi > best_rssi:
                best_rssi = rssi
                best_ap = bssid
        
        if not best_ap:
            print(f"Info: (DAWN) No better AP found for {client.mac} in hearing map.", file=sys.stderr)
            return
        
        print(f"Info: (DAWN) Found candidate AP {best_ap} for {client.mac} at {best_rssi}dBm.", file=sys.stderr)
        # Score candidate AP (No CU available from DAWN)
        new_ap_score = self._calculate_ap_score(best_rssi, None)
        
        client.steering_candidate_ap = {'bssid': best_ap, 'rssi': best_rssi, 'cu': None}
        client.steering_new_ap_score = new_ap_score
        
        # Get current AP score via Link Measurement (if supported)
        if client.supports_lmr and _trigger_link_measurement_request(client.iface, client.mac):
            client.set_state("awaiting_link_measurement_for_dawn")
        else:
            # Fallback
            print(f"Warn: (DAWN) No LMR support or failed to send. Falling back to JSON RSSI.", file=sys.stderr)
            current_ap_score = client.rssi_score # From JSON log
            self.finalize_steering_decision(client, new_ap_score, current_ap_score, None)

    def process_ubus_event(self, event_data):
        """Handles a new ubus event."""
        if "hostapd.beacon_rep_rx" in event_data:
            data = event_data["hostapd.beacon_rep_rx"]
            client = self.clients.get(data.get("addr"))
            if client and client.state == "awaiting_beacon_report":
                print(f"Info: (Asym) Received beacon report from {client.mac}", file=sys.stderr)
                self.handle_beacon_report(client, data.get("report", []))
            
        elif "hostapd.link_measurement_rep_rx" in event_data:
            data = event_data["hostapd.link_measurement_rep_rx"]
            client = self.clients.get(data.get("addr"))
            if client and client.state == "awaiting_link_measurement":
                print(f"Info: (Asym) Received link measurement from {client.mac}", file=sys.stderr)
                self.handle_link_report(client, data.get("report"))
            elif client and client.state == "awaiting_link_measurement_for_dawn":
                print(f"Info: (DAWN) Received link measurement from {client.mac}", file=sys.stderr)
                self.handle_dawn_link_report(client, data.get("report"))

        elif "hostapd.bss_tm_resp" in event_data:
            data = event_data["hostapd.bss_tm_resp"]
            client = self.clients.get(data.get("addr"))
            if client and client.state == "awaiting_bss_tm_response":
                self.handle_bss_tm_response(client, data)

    def handle_beacon_report(self, client, beacon_table):
        """(Asym. Score) Step 2: Process beacon report."""
        current_ap_entry = None
        new_ap_entry = None
        other_neighbors = []
        
        beacon_table.sort(key=lambda x: x.get('rssi', -100), reverse=True)

        for entry in beacon_table:
            bssid = entry.get('bssid')
            if not bssid: continue
            
            # Extract Channel Util
            bss_load = entry.get('bss_load', {})
            cu = bss_load.get('channel_utilization') # Can be None
            entry['cu'] = cu # Store it
            
            if bssid.lower() == client.current_ap_bssid.lower():
                current_ap_entry = entry
            elif not new_ap_entry:
                new_ap_entry = entry
            else:
                other_neighbors.append(entry)

        if not new_ap_entry:
            print(f"Info: (Asym) No alternative APs found for {client.mac}. Aborting.", file=sys.stderr)
            client.set_state("idle")
            return

        client.steering_candidate_ap = new_ap_entry
        client.steering_current_ap_entry = current_ap_entry
        client.steering_other_neighbors = other_neighbors
        
        # Calculate new AP score using RSSI and CU
        client.steering_new_ap_score = self._calculate_ap_score(
            new_ap_entry.get('rssi'), new_ap_entry.get('cu')
        )

        # Step 3: Get current AP score via Link Measurement
        if client.supports_lmr and _trigger_link_measurement_request(client.iface, client.mac):
            client.set_state("awaiting_link_measurement")
        else:
            print(f"Warn: (Asym) No LMR support or failed to send. Falling back to beacon RSSI.", file=sys.stderr)
            current_ap_rssi = None
            current_ap_cu = None
            if current_ap_entry:
                current_ap_rssi = current_ap_entry.get('rssi')
                current_ap_cu = current_ap_entry.get('cu')
                
            current_ap_score = self._calculate_ap_score(current_ap_rssi, current_ap_cu)
            self.finalize_steering_decision(client, client.steering_new_ap_score, current_ap_score, current_ap_rssi)

    def handle_link_report(self, client, report_data):
        """(Asym. Score) Step 3b: Process link report."""
        current_ap_rssi = self._parse_link_report(report_data)
        current_ap_score = self._calculate_ap_score(current_ap_rssi, None) # No CU from link report
        new_ap_score = client.steering_new_ap_score
        self.finalize_steering_decision(client, new_ap_score, current_ap_score, current_ap_rssi)

    def handle_dawn_link_report(self, client, report_data):
        """(RSSI Score) Step 2: Process link report."""
        current_ap_rssi = self._parse_link_report(report_data)
        current_ap_score = self._calculate_ap_score(current_ap_rssi, None) # No CU from link report
        new_ap_score = client.steering_new_ap_score
        self.finalize_steering_decision(client, new_ap_score, current_ap_score, current_ap_rssi)

    def handle_bss_tm_response(self, client, response_data):
        """Log the result of the BSS transition."""
        status_code = response_data.get('status_code', -1) # -1 = We got event, but no code
        
        status_map = {
            0: "accept",
            1: "reject_unspecified",
            2: "reject_insufficient_beacon",
            3: "reject_insufficient_capacity",
            4: "reject_bss_termination_undesired",
            5: "reject_bss_termination_delay",
            6: "reject_sta_not_associated",
            7: "reject_invalid_neighbor_list",
            8: "reject_no_80211v",
            9: "reject_not_authenticated",
            10: "reject_roaming_in_progress",
            11: "reject_max_retries",
        }
        status_str = status_map.get(status_code, f"reject_code_{status_code}")
        
        print(f"Info: Received BSS TM Response from {client.mac}: Status={status_str}", file=sys.stderr)

        data = client.last_steer_attempt_data
        self.log_transition_attempt(
            client.mac, status_str,
            data.get('prev_ap'), data.get('prev_ap_rssi'),
            data.get('new_ap'), data.get('new_ap_rssi'),
            True, client.supports_lmr
        )
        client.set_state("idle")
        client.clear_steering_data()

    def finalize_steering_decision(self, client, new_score, current_score, current_rssi):
        """Step 4: Compare scores and send BSS transition if needed."""
        score_diff = new_score - current_score
        new_ap_data = client.steering_candidate_ap
        
        print(f"Info: Final check for {client.mac}: NewAP_Score={new_score:.2f}, CurrentAP_Score={current_score:.2f}, Diff={score_diff:.2f}", file=sys.stderr)

        if score_diff > BSS_SCORE_THRESHOLD:
            neighbor_list = [new_ap_data['bssid']]
            for entry in client.steering_other_neighbors[:2]:
                if entry.get('bssid'):
                    neighbor_list.append(entry['bssid'])
            
            # Store data for logging
            client.last_steer_attempt_data = {
                'prev_ap': client.current_ap_bssid,
                'prev_ap_rssi': current_rssi,
                'new_ap': new_ap_data['bssid'],
                'new_ap_rssi': new_ap_data.get('rssi')
            }
            
            if _trigger_bss_transition_request(client.iface, client.mac, neighbor_list):
                client.set_state("awaiting_bss_tm_response")
            else:
                client.set_state("idle") # Request failed
        else:
            print(f"Info: Steering condition NOT met for {client.mac} (Diff: {score_diff:.2f} <= {BSS_SCORE_THRESHOLD})", file=sys.stderr)
            client.set_state("idle")
        
        client.clear_steering_data()


def init_csv_log():
    """Initializes the CSV log file and returns the writer and file object."""
    file_exists = os.path.isfile(CSV_LOG_FILE)
    print(f"Info: Logging BSS transitions to {CSV_LOG_FILE}", file=sys.stderr)
    
    csv_file = open(CSV_LOG_FILE, 'a', newline='')
    csv_writer = csv.writer(csv_file)
    
    if not file_exists:
        # Write header
        csv_writer.writerow([
            "timestamp", "client_mac", "disassoc_time",
            "prev_ap_bssid", "new_ap_bssid", "prev_ap_rssi", "new_ap_rssi",
            "disassoc_imminent", "status_code", "lmr_supported"
        ])
        csv_file.flush()
        
    return csv_writer, csv_file

def main():
    """Main event loop."""
    try:
        fcntl.fcntl(sys.stdin, fcntl.F_SETFL, os.O_NONBLOCK)
    except Exception as e:
        print(f"Error setting stdin to non-blocking: {e}", file=sys.stderr)
        sys.exit(1)

    print("Info: Starting ubus listen subprocess...", file=sys.stderr)
    ubus_proc = subprocess.Popen(['ubus', 'listen'], 
                                 stdout=subprocess.PIPE, 
                                 stderr=subprocess.PIPE, 
                                 text=True)
    fcntl.fcntl(ubus_proc.stdout, fcntl.F_SETFL, os.O_NONBLOCK)

    try:
        csv_writer, csv_file = init_csv_log()
    except Exception as e:
        print(f"CRITICAL: Failed to open log file {CSV_LOG_FILE}: {e}", file=sys.stderr)
        ubus_proc.terminate()
        sys.exit(1)

    read_streams = [sys.stdin, ubus_proc.stdout]
    stdin_buffer = ""
    ubus_buffer = ""
    json_buffer = ""
    in_json = False
    orchestrator = None
    last_timeout_check = time.time()

    print("Info: Steering daemon started. Reading from stdin...", file=sys.stderr)

    try:
        while True:
            readable, _, _ = select.select(read_streams, [], [], 1.0)
            now = time.time()
            
            for stream in readable:
                try:
                    data = stream.read()
                    if not data:
                        print(f"Info: Stream {stream.name} closed.", file=sys.stderr)
                        read_streams.remove(stream)
                        if stream == sys.stdin:
                            print("Info: stdin closed. Exiting.", file=sys.stderr)
                            return
                        continue

                    if stream == sys.stdin:
                        stdin_buffer += data
                        lines = stdin_buffer.split('\n')
                        stdin_buffer = lines.pop()
                        
                        for line in lines:
                            stripped = line.strip()
                            if not stripped: continue
                            if not in_json and stripped.startswith('{'):
                                in_json = True
                                json_buffer = line
                            elif in_json:
                                json_buffer += line
                            if not in_json:
                                print(line) # Echo header
                            if in_json and stripped == '}':
                                in_json = False
                                try:
                                    json_data = json.loads(json_buffer)
                                    if not orchestrator:
                                        ap_mac = json_data.get("ap_mac")
                                        if ap_mac:
                                            orchestrator = NetworkOrchestrator(ap_mac, csv_writer, csv_file)
                                        else:
                                            print("Error: 'ap_mac' not in first JSON. Waiting...", file=sys.stderr)
                                            continue
                                    if orchestrator:
                                        print(f"Info: Processing JSON log @ {json_data.get('timestamp')}", file=sys.stderr)
                                        orchestrator.process_json_log(json_data)
                                        print(json.dumps(json_data, indent=2)) # Echo JSON
                                except json.JSONDecodeError as e:
                                    print(f"Error: Failed to decode JSON:\n{json_buffer}", file=sys.stderr)
                                json_buffer = ""

                    elif stream == ubus_proc.stdout:
                        ubus_buffer += data
                        lines = ubus_buffer.split('\n')
                        ubus_buffer = lines.pop()
                        for line in lines:
                            if not line.strip(): continue
                            try:
                                event_data = json.loads(line)
                                if orchestrator:
                                    orchestrator.process_ubus_event(event_data)
                            except json.JSONDecodeError:
                                print(f"Warn: Failed to decode ubus event JSON: {line}", file=sys.stderr)
                except Exception as e:
                    print(f"Error reading from stream: {e}", file=sys.stderr)

            # --- Periodic Tasks (every 1s) ---
            if orchestrator and (now - last_timeout_check >= 1.0):
                orchestrator.check_client_timeouts()
                last_timeout_check = now

            if ubus_proc.poll() is not None:
                print("CRITICAL: ubus listen process died. Exiting.", file=sys.stderr)
                break
                
    except KeyboardInterrupt:
        print("\nInfo: Shutting down daemon.", file=sys.stderr)
    except Exception as e:
        print(f"CRITICAL: Unhandled exception in main loop: {e}", file=sys.stderr)
    finally:
        ubus_proc.terminate()
        ubus_proc.wait()
        csv_file.close()
        print("Info: Daemon stopped. Log file closed.", file=sys.stderr)

if __name__ == "__main__":
    main()
