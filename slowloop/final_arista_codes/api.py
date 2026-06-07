from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs
import subprocess
import threading
import json
from datetime import datetime
from passive_acquisition import RetryMonitorPro


# --- Utility functions ---
def run_cmd(cmd):
    """Run a shell command and return parsed JSON if possible."""
    try:
        output = subprocess.check_output(cmd, shell=True, stderr=subprocess.STDOUT)
        text = output.decode().strip()

        # Try to parse as JSON (many ubus outputs are valid JSON)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text  # fallback to plain string if not JSON

    except subprocess.CalledProcessError as e:
        return {"error": e.output.decode().strip()}


def run_cmd_2(cmd):
    """Run a shell command and return EXACT raw stdout or stderr."""
    try:
        output = subprocess.check_output(cmd, shell=True, stderr=subprocess.STDOUT)
        return output.decode().rstrip("\n")
    except subprocess.CalledProcessError as e:
        return e.output.decode().rstrip("\n")


# --- API Handler ---
class PassiveInferenceHandler(BaseHTTPRequestHandler):

    # --------- GET Request Handler ---------
    def do_GET(self):
        parsed_path = urlparse(self.path)
        params = parse_qs(parsed_path.query)
        route = parsed_path.path

        # --- 1. Passive Inference (existing) ---
        if route == '/get_passive_inference':
            self.handle_passive_inference(params)

        # --- 2. Get Client Info ---
        elif route == '/get_client':
            self.handle_get_client(params)

        # --- 3. send_k_request (ubus k request) ---
        elif route == '/send_k_request':
            self.handle_ubus_request(params, mode='k')

        # --- 4. send_v_request (ubus v request) ---
        elif route == '/send_v_request':
            self.handle_ubus_request(params, mode='v')
	
        # --- 5. Delete (kick) a client ---
        elif route == '/del_client':
            self.handle_del_client(params)
        
        # --- 6. Run Telemetry + Passive Capture Together ---
        elif route == '/start_steering':
            self.handle_dual_monitor(params)

        # --- Unknown Endpoint ---
        else:
            self.send_json({"error": "Endpoint not found"}, status=404)

    #-----------------------------------------------------------------------------

    def handle_k_request(self, params):
        """Send an 802.11k RRM request."""
        method = params.get("method", [None])[0]
        client_mac = params.get("client_mac", [None])[0]

        if not method:
            self.send_json({"error": "Missing 'method'"}, status=400)
            return

        if not client_mac:
            self.send_json({"error": "Missing 'client_mac'"}, status=400)
            return

        # Map simple method names to ubus names
        valid_k_methods = {
        "beacon_req": "rrm_beacon_req",
        "link_measurement": "link_measurement_req"
        }

        if method not in valid_k_methods:
            self.send_json({"error": f"Invalid 802.11k method '{method}'"}, status=400)
            return

        ubus_method = valid_k_methods[method]

        if method == "beacon_req":
            payload = {
            "addr": client_mac,
            "mode": 0,             # active
            "op_class": 81,        # 2.4 GHz default
            "channel": 1,
            "duration": 50,
            }

        elif method == "link_measurement":
            payload = {
            "addr": client_mac,
            "tx-power-used": 15,
            "tx-power-max": 20
            }


        cmd = f"ubus call hostapd.phy0-ap0 {ubus_method} '{json.dumps(payload)}'"
        output = run_cmd_2(cmd)

        self.send_json({
        "mode": "802.11k",
        "method": method,
        "mapped_to": ubus_method,
        "payload": payload,
        "output": output
        })


 
    def handle_v_request(self, params):
        """Send an 802.11v BSS Transition request."""
        method = params.get("method", [None])[0]
        client_mac = params.get("client_mac", [None])[0]

        if not method:
            self.send_json({"error": "Missing 'method'"}, status=400)
            return

        if not client_mac:
            self.send_json({"error": "Missing 'client_mac'"}, status=400)
            return

        valid_v_methods = {
        "bss_tm_req": "bss_tm_req",
        "disassoc_imminent": "bss_disassoc_imminent",
        "candidate_list": "bss_candidate_list",
        "tim_broadcast": "tim_broadcast_req"
        }

        if method not in valid_v_methods:
            self.send_json({"error": f"Invalid 802.11v method '{method}'"}, status=400)
            return

        ubus_method = valid_v_methods[method]

        payload = {
            "addr": client_mac,
            "dialog_token": 1,
            "disassoc_timer": 0,     # 0 = no forced disassoc
            "validity_interval": 1,  # required for BTM
            "abridged": True         # common default
        }

        cmd = f"ubus call hostapd.phy0-ap0 {ubus_method} '{json.dumps(payload)}'"
        output = run_cmd_2(cmd)

        self.send_json({
        "mode": "802.11v",
        "method": method,
        "mapped_to": ubus_method,
        "payload": payload,
        "output": output
        })

    #---------------------------- Dual File Run -------------------------------

    def handle_dual_monitor(self, params):
        """
        Start telemetry_daemon.py AND passive_acquisition (RetryMonitorPro)
        simultaneously. Returns immediately while processes run in background.
        """

        # ---- Read parameters for passive acquisition ----
        client_mac = params.get('client_mac', [None])[0]
        sampling_time = int(params.get('sampling_time', [10])[0])
        hash_macs = params.get('hash', ['false'])[0].lower() == 'true'

        # ---- 1. Start telemetry_daemon.py as background process ----
        try:
            telem_proc = subprocess.Popen(
                ["python3", "/telemetry_daemon.py"],   # Modify path if needed
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            telem_pid = telem_proc.pid
        except Exception as e:
            self.send_json({"error": f"Failed to start telemetry_daemon: {str(e)}"}, status=500)
            return

        # ---- 2. Start passive monitor in background thread ----
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

        # ---- 3. Response ----
        self.send_json({
            "status": "started",
            "message": "Telemetry daemon + Passive monitor running in background",
            "telemetry_daemon_pid": telem_pid,
            "passive_monitor": {
                "client_mac": client_mac,
                "sampling_time": sampling_time,
                "hash_macs": hash_macs,
                "thread_alive": thread.is_alive()
            }
        })


    # --------------------------------------------------------------------------
    # --------------------------- Endpoint Handlers ----------------------------
    # --------------------------------------------------------------------------

    def handle_passive_inference(self, params):
        client_mac = params.get('client_mac', [None])[0]
        sampling_time = int(params.get('sampling_time', [10])[0])
        continuous = params.get('continuous', ['false'])[0].lower() == 'true'
        hash_macs = params.get('hash', ['false'])[0].lower() == 'true'

        monitor = RetryMonitorPro(
            monitor_iface='mon0',
            sampling_time=sampling_time,
            target_client=client_mac,
            hash_macs=hash_macs
        )

        if continuous:
            self.send_json({
                'status': 'started',
                'message': 'Continuous monitoring started. Check router logs for output.',
                'parameters': {
                    'client_mac': client_mac,
                    'sampling_time': sampling_time,
                    'continuous': True,
                    'hash_macs': hash_macs
                }
            })
            thread = threading.Thread(target=lambda: monitor.capture(continuous=True), daemon=True)
            thread.start()
        else:
            results = monitor.capture(continuous=False)
            self.send_json(results)

    # --------------------------------------------------------------------------
    def handle_get_client(self, params):
        """Fetch client info from ubus or iwinfo."""
        client_mac = params.get('client_mac', ['default'])[0]
        detailed = params.get('detailed', ['false'])[0].lower() == 'true'

        if detailed:
            if client_mac == 'default':
                cmd = "ubus call hostapd.phy0-ap0 get_clients"
            else:
                cmd = f"ubus call hostapd.phy0-ap0 get_clients | grep -i '{client_mac}' -A5"
        else:
            cmd = "iwinfo phy0-ap0 assoclist" if client_mac == 'default' else f"iwinfo phy0-ap0 assoclist | grep -i '{client_mac}' -A2"

        output = run_cmd(cmd)
        self.send_json({"client_mac": client_mac, "detailed": detailed, "output": output})

    # --------------------------------------------------------------------------
    def handle_ubus_request(self, params, mode):
        """Send ubus command (K or V mode)."""
        #ubus_cmd = params.get('cmd', [None])[0]

        # Example command: ubus call <object> <method> <args>
        if mode == 'k':
            self.handle_k_request(params)

        elif mode == 'v':
            self.handle_v_request(params)
        
    # --------------------------------------------------------------------------
    def handle_del_client(self, params):
        """Kick a client from the network."""
        client_mac = params.get('client_mac', [None])[0]
        if not client_mac:
            self.send_json({"error": "Missing client_mac"}, status=400)
            return

        cmd = f"ubus call hostapd.phy0-ap0 del_client '{{\"addr\": \"{client_mac}\", \"reason\": 5, \"deauth\": 1, \"ban_time\": 0}}'"
        output = run_cmd(cmd)
        self.send_json({"client_mac": client_mac, "output": output})

    # --------------------------------------------------------------------------
    # ------------------------------ Utilities ---------------------------------
    # --------------------------------------------------------------------------

    def send_json(self, data, status=200):
        """Send JSON response."""
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data, indent=2).encode())

    def log_message(self, format, *args):
        """Custom log output with timestamps."""
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {format % args}")


# --- Run API Server ---
def run_api_server(port=8080):
    server_address = ("", port)
    httpd = HTTPServer(server_address, PassiveInferenceHandler)

    print(f"🚀 Starting Passive Inference Pro API Server on port {port}\n")
    print("Available Endpoints:")
    print("  GET /get_passive_inference?client_mac=<mac_addr>&sampling_time=<integer>&continuous=<true|false>&hash=<true|false>")
    print("  GET /get_client?client_mac=<mac_addr>&detailed=<true|false>")
    print("  GET /send_k_request?client_mac<mac_addr>&method=<methods>")
    print("  GET /send_v_request?client_mac<mac_addr>&method=<methods>")
    print("  GET /del_client?client_mac=<mac_addr>")
	print("  GET /start_steering?client_mac=<mac_addr>&sampling_time=<inetger>&hash=<true|false>")
    print()
    httpd.serve_forever()


if __name__ == "__main__":
    run_api_server()

