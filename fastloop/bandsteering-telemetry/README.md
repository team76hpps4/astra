# WiFi Passive Inference and Band Steering System

This project provides a suite of tools for monitoring WiFi client performance, measuring TCP RTT, computing quality metrics, and performing band steering on Linux-based routers (e.g., OpenWrt). It uses passive packet capture, ubus integration, and heuristic-based decisions to optimize client connections across 2.4GHz and 5GHz bands.

## Setup Instructions

1. **Environment Requirements**:
   - Linux system with WiFi interfaces (e.g., OpenWrt router).
   - Python 3.8+ installed.
   - Required packages: Install via `pip install numpy statistics cryptography` (for hashing and encryption in passive_acquisition.py).
   - Tools: Ensure `tcpdump`, `iw`, `ubus`, `ip`, `arp`, and `hostapd` are available.
   - Monitor interface: Set up a monitor mode interface (e.g., `mon0`) using `iw phy phy0 interface add mon0 type monitor` and bring it up with `ifconfig mon0 up`.
   - AP interfaces: Assumes interfaces like `phy0-ap0` (2.4GHz) and `phy1-ap0` (5GHz); adjust in config files if needed.

2. **Configuration**:
   - Create a `.env` file in the project root with `SECRET_KEY=<your-secret>` and `FERNET_KEY=<your-fernet-key>` for MAC hashing (generated automatically on first run if missing).
   - Ensure write permissions for log/CSV files (e.g., `/tmp/rtt_stats.csv`, `/var/log/band_steering.log`).
   - For RTT monitoring, ensure ARP cache is accessible.

3. **Starting Services**:
   - Run `tcp_rtt.py` in background: `python3 tcp_rtt.py -i br-lan -o /tmp/rtt_stats.csv &`.
   - Start API server: `python3 api.py` (listens on port 8080).
   - Run telemetry daemon: `python3 telemetry_daemon.py &` (reads from stdin, integrates with ubus).
   - Run fast action loop: `python3 interference_graph.py &` along with `python3 hidden_node_algorithm.py &` (make sure `cca_tm_algo.py` and `obsspd_algo.py` are in the same directory)
   - For band steering: Integrate via `basic_band_steering.py` or call from telemetry_daemon.
   - Passive capture: Use API endpoint `/get_passive_inference` or run `python3 passive_acquisition.py true/false <sampling_time> <client_mac>`.

4. **Testing**:
   - Verify monitor mode: `tcpdump -i mon0 -c 10`.
   - Check ubus: `ubus list hostapd.*`.
   - Logs: Monitor `/var/log/band_steering.log` and CSV outputs.

## File Descriptions
- **interference_graph.py**: Runs as a deamon on AP and constructs the interference graph passively. Results are stored in `/tmp/interference_graph.json`.

- **hidden_node_algorithm.py**: Runs the main reflexive fast loop algotithm. Leverages `/tmp/interference_graph.json` to identiy and handle hidden nodes. Also triggers OBSS-PD threshold change when neighbour AP packets are received (requires `interference_graph.py` to run in background)

- **cca_tm_algo.py**: Decides whether transitioning to adjacent channel AP is better than performing CCA. Used by `hidden_node_algorithm.py`.

- **obsspd_algo.py**: Performs dynamic OBSSPD threshold adaptation. Called by `hidden_node_algorithm.py`.

- **tcp_rtt.py**: Monitors TCP round-trip times using tcpdump on a specified interface. Outputs RTT samples to CSV for use in steering decisions, associating IPs to MACs via ARP cache.

- **api.py**: Implements an HTTP server for API endpoints to control passive inference, fetch client info, send 802.11k/v requests, kick clients, and start dual monitoring (telemetry + passive capture).

- **telemetry_daemon.py**: Runs as a daemon to process JSON logs from stdin, monitor client states, compute asymmetry/RSSI scores, and orchestrate band steering via ubus calls; logs transitions to CSV.

- **ewma.py**: Provides frequency-aware exponential weighted moving average filtering for smoothing metrics like RFEQM, handling spikes with adaptive alpha based on severity and frequency.

- **rfeqm.py**: Calculates RF Environment Quality Metric (RFEQM) scores based on interference types, probabilities, duty cycles, and power levels; converts watts to dBm for severity computation.

- **basic_band_steering.py**: Manages band steering logic using RSSI, RTT metrics, and bandwidth usage; processes clients on 2.4/5GHz, steers based on thresholds, and validates post-steer RTT.

- **passive_acquisition.py**: Captures packets in monitor mode to compute retry rates, throughput, ACK variances, and QoE scores; supports targeting specific clients and hashing MACs for privacy.

## APIs

All API endpoints are handled by `api.py`. Start the API server with:

```bash
python3 api.py
```

The server listens on port 8080 by default.

### Available Endpoints

#### `/get_passive_inference`
Starts passive monitoring and acquires network data via the monitor interface set up on the AP antenna.

**Parameters:**
- `client_mac` (optional, default ff:ff:ff:ff:ff:ff): Target client MAC address
- `sampling_time` (optional, default: 10): Capture duration in seconds
- `continuous` (optional, default: true): Enable continuous monitoring
- `hash_macs` (optional, default: false): Hash MAC addresses for privacy

**Example:**
```bash
curl "http://localhost:8080/get_passive_inference?client_mac=aa:bb:cc:dd:ee:ff&continuous=true&hash_macs=false&sampling_time=15" -o output.json
```

#### `/get_client`
Retrieves information about clients connected to the access point.

**Parameters:**
- `client_mac` (optional, default ff:ff:ff:ff:ff:ff): Target client MAC address
- `detailed` (optional, default: false): Show detailed client information

**Example:**
```bash
curl "http://localhost:8080/get_client?client_mac=aa:bb:cc:dd:ee:ff&detailed=true"
```

#### `/send_k_request`
Sends an IEEE 802.11k request to the specified client for link measurement reporting.

**Parameters:**
- `client_mac` (required): Target client MAC address
- `method` (required): Request type (`beacon_req` | `link_measurement`)

**Example:**
```bash
curl "http://localhost:8080/send_k_request?method=link_measurement&client_mac=aa:bb:cc:dd:ee:ff"
```

#### `/send_v_request`
Sends an IEEE 802.11v BSS Transition Management request to the client.

**Parameters:**
- `client_mac` (required): Target client MAC address
- `method` (required): Request type (`bss_tm_req` | `dissociation_imminent` | `candidate_list` | `tim_broadcast`)

**Example:**
```bash
curl "http://localhost:8080/send_v_request?method=bss_tm_req&client_mac=aa:bb:cc:dd:ee:ff"
```

#### `/del_client`
Forcibly removes a client from the network using its MAC address.

**Parameters:**
- `client_mac` (required): Target client MAC address to disconnect

**Example:**
```bash
curl "http://localhost:8080/del_client?client_mac=aa:bb:cc:dd:ee:ff"
```

#### `/start_steering`
Runs both `telemetry_daemon.py` and `passive_acquisition.py` simultaneously, returning combined results in JSON format.

**Parameters:**
- `client_mac` (optional): Target client MAC address. If omitted, returns data for all associated clients
- `sampling_time` (optional, default: 10): Monitoring duration in seconds
- `hash_macs` (optional, default: false): Hash MAC addresses for privacy

**Example:**
```bash
# Monitor specific client
curl "http://localhost:8080/start_steering?client_mac=aa:bb:cc:dd:ee:ff&sampling_time=15&hash_macs=false"

# Monitor all clients
curl "http://localhost:8080/start_steering?sampling_time=20"
```

#### `/get_interference_graph`
Acquire on-AP Interference Graph

**Example:**
```bash
curl "http://localhost:8080/get_interference_graph"
```

#### `/start_fast_loop`
Start the on-AP fast reflexive loop. This starts Telemetry, Interference Graph with other algorithms.

**Parameters:**
- `client_mac` (optional, default ff:ff:ff:ff:ff:ff): Target client MAC address to acquire data
- `sampling_time` (optional, default: 10): Sampling time for passive acquisition

**Example:**
```bash
curl "http://localhost:8080/start_fast_loop?client_mac=aa:bb:cc:dd:ee:ff&sampling_time=15"
```

---

**Notes:**
- Replace `localhost` with your router's IP address when calling from a remote client
- Ensure the monitor interface (`mon0`) is active before using passive inference endpoints
- API responses are in JSON format unless specified otherwise

## Usage

- For standalone RTT monitoring: `python3 tcp_rtt.py -i <interface> -o <csv_output>`.
- API example: `curl "http://localhost:8080/get_passive_inference?client_mac=xx:xx:xx:xx:xx:xx&sampling_time=10&continuous=true"`.
- Integrate telemetry with band steering: Run `telemetry_daemon.py` and feed JSON logs via pipe or stdin.
- Customize thresholds in `telemetry_daemon.py` and `basic_band_steering.py` configs for your network.
