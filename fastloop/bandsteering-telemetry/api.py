from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs
import subprocess
import threading
import json
import os
from datetime import datetime
from passive_acquisition import RetryMonitorPro

# --- Configuration ---
MATRIX_FILE = "/tmp/wifi_matrix.json"

# --- Utility functions ---
def run_cmd(cmd):
    """Run a shell command and return parsed JSON if possible."""
    try:
        output = subprocess.check_output(cmd, shell=True, stderr=subprocess.STDOUT)
        text = output.decode().strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text 
    except subprocess.CalledProcessError as e:
        return {"error": e.output.decode().strip()}

def run_cmd_2(cmd):
    """Run a shell command and return EXACT raw stdout or stderr."""
    try:
        output = subprocess.check_output(cmd, shell=True, stderr=subprocess.STDOUT)
        return output.decode().rstrip("\n")
    except subprocess.CalledProcessError as e:
        return e.output.decode().rstrip("\n")

def start_background_process(command, log_file):
    """Helper to start a detached background process logging to a file."""
    try:
        with open(log_file, "w") as out:
            proc = subprocess.Popen(
                command,
                stdout=out,
                stderr=out,
                shell=False
            )
        return proc.pid
    except Exception as e:
        print(f"Error starting {command}: {e}")
        return None

# --- API Handler ---
class PassiveInferenceHandler(BaseHTTPRequestHandler):

    # --------- GET Request Handler ---------
    def do_GET(self):
        parsed_path = urlparse(self.path)
        params = parse_qs(parsed_path.query)
        route = parsed_path.path

        # --- 1. Passive Inference ---
        if route == '/get_passive_inference':
            self.handle_passive_inference(params)

        # --- 2. Get Client Info ---
        elif route == '/get_client':
            self.handle_get_client(params)

        # --- 3. send_k_request ---
        elif route == '/send_k_request':
            self.handle_ubus_request(params, mode='k')

        # --- 4. send_v_request ---
        elif route == '/send_v_request':
            self.handle_ubus_request(params, mode='v')
    
        # --- 5. Delete client ---
        elif route == '/del_client':
            self.handle_del_client(params)
        
        # --- 6. Start Steering (Telemetry + Passive) ---
        elif route == '/start_steering':
            self.handle_dual_monitor(params)

        # --- 7. NEW: Get Interference Graph ---
        elif route == '/get_interference_graph':
            self.handle_get_interference_graph()

        # --- 8. NEW: Start Fast Loop (All Algorithms) ---
        elif route == '/start_fast_loop':
            self.start_fast_loop(params)

        # --- Unknown Endpoint ---
        else:
            self.send_json({"error": "Endpoint not found"}, status=404)

    # --------------------------------------------------------------------------
    # --------------------------- New Handlers ---------------------------------
    # --------------------------------------------------------------------------

    def handle_get_interference_graph(self):
        """Reads and returns the JSON content of the interference graph."""
        try:
            if not os.path.exists(MATRIX_FILE):
                self.send_json({"error": "Interference graph file not found (script not running?)"}, status=404)
                return

            with open(MATRIX_FILE, 'r') as f:
                data = json.load(f)
            self.send_json(data)
        except Exception as e:
            self.send_json({"error": f"Failed to read graph: {str(e)}"}, status=500)

    def start_fast_loop(self, params):
        """
        Starts the full autonomous loop:
        1. telemetry_daemon.py (Stats collection)
        2. Passive Acquisition (Retry Monitor)
        3. interference_graph.py (Matrix builder)
        4. hidden_node_algo.py (Decision engine)
        """
        
        # Parse Params
        client_mac = params.get('client_mac', [None])[0]
        sampling_time = int(params.get('sampling_time', [10])[0])
        hash_macs = params.get('hash', ['false'])[0].lower() == 'true'

        pids = {}

        # 1. Start Telemetry Daemon
        # Using specific log files prevents buffer blocking issues in background
        pids['telemetry'] = start_background_process(
            ["python3", "telemetry_daemon.py"], 
            "/tmp/log_telemetry.txt"
        )

        # 2. Start Interference Graph Script
        pids['interference_graph'] = start_background_process(
            ["python3", "interference_graph.py"], 
            "/tmp/log_graph.txt"
        )

        # 3. Start Hidden Node Algorithm (Decision Engine)
        pids['hidden_node_algo'] = start_background_process(
            ["python3", "hidden_node_algo.py"], 
            "/tmp/log_algo.txt"
        )

        # 4. Start Passive Monitor (In-Thread)
        # We start this last to ensure the thread is tied to the API response logic
        monitor = RetryMonitorPro(
            monitor_iface="mon0",
            sampling_time=sampling_time,
            target_client=client_mac,
            hash_macs=hash_macs
        )

        thread = threading.Thread(
            target=lambda: monitor.capture(continuous=True),
            daemon=True
        )
        thread.start()

        self.send_json({
            "status": "started",
            "mode": "fast_loop",
            "message": "All RRM subsystems started.",
            "background_pids": pids,
            "monitor_thread": {
                "client_mac": client_mac,
                "sampling_time": sampling_time,
                "alive": thread.is_alive()
            },
            "logs": {
                "telemetry": "/tmp/log_telemetry.txt",
                "graph": "/tmp/log_graph.txt",
                "algo": "/tmp/log_algo.txt"
            }
        })

    # --------------------------------------------------------------------------
    # --------------------------- Existing Handlers ----------------------------
    # --------------------------------------------------------------------------

    def handle_k_request(self, params):
        method = params.get("method", [None])[0]
        client_mac = params.get("client_mac", [None])[0]

        if not method or not client_mac:
            self.send_json({"error": "Missing method or client_mac"}, status=400)
            return

        valid_k_methods = {
            "beacon_req": "rrm_beacon_req",
            "link_measurement": "link_measurement_req"
        }

        if method not in valid_k_methods:
            self.send_json({"error": f"Invalid method '{method}'"}, status=400)
            return

        ubus_method = valid_k_methods[method]

        if method == "beacon_req":
            payload = {"addr": client_mac, "mode": 0, "op_class": 81, "channel": 1, "duration": 50}
        elif method == "link_measurement":
            payload = {"addr": client_mac, "tx-power-used": 15, "tx-power-max": 20}

        cmd = f"ubus call hostapd.phy0-ap0 {ubus_method} '{json.dumps(payload)}'"
        output = run_cmd_2(cmd)

        self.send_json({"mode": "802.11k", "method": method, "output": output})

    def handle_v_request(self, params):
        method = params.get("method", [None])[0]
        client_mac = params.get("client_mac", [None])[0]

        if not method or not client_mac:
            self.send_json({"error": "Missing method or client_mac"}, status=400)
            return

        valid_v_methods = {
            "bss_tm_req": "bss_tm_req",
            "disassoc_imminent": "bss_disassoc_imminent",
            "candidate_list": "bss_candidate_list",
            "tim_broadcast": "tim_broadcast_req"
        }

        if method not in valid_v_methods:
            self.send_json({"error": f"Invalid method '{method}'"}, status=400)
            return

        ubus_method = valid_v_methods[method]
        payload = {"addr": client_mac, "dialog_token": 1, "disassoc_timer": 0, "validity_interval": 1, "abridged": True}

        cmd = f"ubus call hostapd.phy0-ap0 {ubus_method} '{json.dumps(payload)}'"
        output = run_cmd_2(cmd)

        self.send_json({"mode": "802.11v", "method": method, "output": output})

    def handle_dual_monitor(self, params):
        client_mac = params.get('client_mac', [None])[0]
        sampling_time = int(params.get('sampling_time', [10])[0])
        hash_macs = params.get('hash', ['false'])[0].lower() == 'true'

        # Start telemetry daemon
        try:
            # Using log file redirection for safety instead of PIPE
            with open("/tmp/log_telemetry.txt", "w") as out:
                telem_proc = subprocess.Popen(
                    ["python3", "telemetry_daemon.py"],
                    stdout=out,
                    stderr=out
                )
            telem_pid = telem_proc.pid
        except Exception as e:
            self.send_json({"error": f"Failed to start telemetry: {str(e)}"}, status=500)
            return

        monitor = RetryMonitorPro(
            monitor_iface="mon0",
            sampling_time=sampling_time,
            target_client=client_mac,
            hash_macs=hash_macs
        )

        thread = threading.Thread(
            target=lambda: monitor.capture(continuous=True),
            daemon=True
        )
        thread.start()

        self.send_json({
            "status": "started",
            "message": "Telemetry daemon + Passive monitor running",
            "telemetry_daemon_pid": telem_pid,
            "monitor": {"client": client_mac, "alive": thread.is_alive()}
        })

    def handle_passive_inference(self, params):
        client_mac = params.get('client_mac', [None])[0]
        sampling_time = int(params.get('sampling_time', [10])[0])
        continuous = params.get('continuous', ['false'])[0].lower() == 'true'
        hash_macs = params.get('hash', ['false'])[0].lower() == 'true'

        monitor = RetryMonitorPro('mon0', sampling_time, client_mac, hash_macs)

        if continuous:
            thread = threading.Thread(target=lambda: monitor.capture(continuous=True), daemon=True)
            thread.start()
            self.send_json({"status": "started", "mode": "continuous", "client": client_mac})
        else:
            results = monitor.capture(continuous=False)
            self.send_json(results)

    def handle_get_client(self, params):
        client_mac = params.get('client_mac', ['default'])[0]
        detailed = params.get('detailed', ['false'])[0].lower() == 'true'

        if detailed:
            cmd = "ubus call hostapd.phy0-ap0 get_clients"
            if client_mac != 'default': cmd += f" | grep -i '{client_mac}' -A5"
        else:
            cmd = "iwinfo phy0-ap0 assoclist"
            if client_mac != 'default': cmd += f" | grep -i '{client_mac}' -A2"

        output = run_cmd(cmd)
        self.send_json({"client_mac": client_mac, "output": output})

    def handle_del_client(self, params):
        client_mac = params.get('client_mac', [None])[0]
        if not client_mac:
            self.send_json({"error": "Missing client_mac"}, status=400)
            return
        
        cmd = f"ubus call hostapd.phy0-ap0 del_client '{{\"addr\": \"{client_mac}\", \"reason\": 5, \"deauth\": 1, \"ban_time\": 0}}'"
        output = run_cmd(cmd)
        self.send_json({"client_mac": client_mac, "output": output})

    def handle_ubus_request(self, params, mode):
        # Dispatcher for common logic
        if mode == 'k': self.handle_k_request(params)
        elif mode == 'v': self.handle_v_request(params)

    def send_json(self, data, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data, indent=2).encode())

    def log_message(self, format, *args):
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {format % args}")

# --- Run API Server ---
def run_api_server(port=8080):
    server_address = ("", port)
    httpd = HTTPServer(server_address, PassiveInferenceHandler)

    print(f" Starting API Server on port {port}\n")
    print("Available Endpoints:")
    print("  GET /get_passive_inference?client_mac=..&sampling_time=..&continuous=..")
    print("  GET /get_client?client_mac=..&detailed=..")
    print("  GET /send_k_request?client_mac=..&method=..")
    print("  GET /send_v_request?client_mac=..&method=..")
    print("  GET /del_client?client_mac=..")
    print("  GET /start_steering?client_mac=..&sampling_time=..")
    print("  GET /get_interference_graph")
    print("  GET /start_fast_loop?client_mac=..&sampling_time=..")
    print()
    httpd.serve_forever()

if __name__ == "__main__":
    run_api_server()
