#!/usr/bin/env python3

import subprocess
import re
import json
import time
import numpy as np
import threading
from collections import defaultdict
from datetime import datetime

SELF_SCAN_INTERVAL = 20
DEFAULT_POWER = 20 


class WiFiMatrix:
    """
    Maintains a dynamic interference and path-loss matrix between the local AP,
    associated clients, and detected neighboring APs. Handles live scanning,
    log parsing, and persistence of matrix data.
    """

    def __init__(self, output_file="interference_graph.json"):
        """
        Initialize the matrix state and collect baseline device/network info.
        """
        self.output_file = output_file
        self.matrix_data = {}  # {row_mac: {col_mac: [path_loss, channel, is_own_network]}}
        self.row_order = []
        self.col_order = []
        self.self_ap_mac = None
        self.connected_clients = set()
        self.own_network_aps = set()
        self.ap_channels = {}
        self.lock = threading.Lock()

        self._get_self_ap_info()
        self._get_dawn_network_info()

    def _get_self_ap_info(self):
        """
        Detect local AP MAC and TX power from system utilities.
        """
        try:
            result = subprocess.run(['uci', 'show', 'wireless'],
                                    capture_output=True, text=True, timeout=5)

            result = subprocess.run(['ip', 'link', 'show'],
                                    capture_output=True, text=True, timeout=5)

            for line in result.stdout.split('\n'):
                if 'wlan' in line or 'ath' in line:
                    mac_match = re.search(r'([0-9a-fA-F]{2}(:[0-9a-fA-F]{2}){5})', line)
                    if mac_match:
                        self.self_ap_mac = mac_match.group(1).lower()
                        print(f"Self AP MAC: {self.self_ap_mac}")
                        break

            if self.self_ap_mac:
                result = subprocess.run(['iwinfo'], capture_output=True, text=True, timeout=5)
                tx_match = re.search(r'Tx-Power:\s*(\d+)\s*dBm', result.stdout)
                self.ap_tx_power = {self.self_ap_mac: int(tx_match.group(1)) if tx_match else DEFAULT_POWER}

        except Exception as e:
            print(f"Error getting self AP info: {e}")
            self.self_ap_mac = "00:00:00:00:00:00"

    def _get_dawn_network_info(self):
        """
        Pull known network AP information from the DAWN controller, including
        their TX power and operating channels.
        """
        try:
            result = subprocess.run(['ubus', 'call', 'dawn', 'get_network'],
                                    capture_output=True, text=True, timeout=5)

            if result.returncode == 0:
                data = json.loads(result.stdout)

                if isinstance(data, dict):
                    for ap_info in data.get('aps', []):
                        mac = ap_info.get('bssid', '').lower()
                        if mac:
                            self.own_network_aps.add(mac)
                            if 'tx_power' in ap_info:
                                self.ap_tx_power[mac] = ap_info['tx_power']
                            if 'channel' in ap_info:
                                self.ap_channels[mac] = ap_info['channel']

            if self.self_ap_mac:
                self.own_network_aps.add(self.self_ap_mac)

            print(f"Own network APs: {self.own_network_aps}")

        except Exception as e:
            print(f"Error getting DAWN info: {e}")

    def _get_connected_clients(self):
        """
        Query hostapd for currently connected client MAC IDs.
        """
        try:
            result = subprocess.run(['hostapd_cli', 'all_sta'],
                                    capture_output=True, text=True, timeout=5)

            clients = set()
            for line in result.stdout.split('\n'):
                m = re.match(r'^([0-9a-fA-F:]{17})', line)
                if m:
                    clients.add(m.group(1).lower())
            return clients

        except Exception as e:
            print(f"Error getting connected clients: {e}")
            return set()

    def perform_ap_scan(self):
        """
        Execute Wi-Fi scan via `iw` and update detected AP signal readings into matrix.
        """
        try:
            result = subprocess.run(['iw', 'dev'],
                                    capture_output=True, text=True, timeout=2)

            iface_match = re.search(r'Interface\s+(\S+)', result.stdout)
            if not iface_match:
                return

            iface = iface_match.group(1)

            subprocess.run(['iw', 'dev', iface, 'scan', 'trigger'],
                           capture_output=True, timeout=2)
            time.sleep(2)

            result = subprocess.run(['iw', 'dev', iface, 'scan', 'dump'],
                                    capture_output=True, text=True, timeout=5)

            current_bssid = current_rssi = current_channel = None

            for line in result.stdout.split('\n'):
                bssid_match = re.search(r'BSS\s+([0-9a-fA-F:]{17})', line)
                if bssid_match:
                    if current_bssid and current_rssi is not None:
                        self._process_scan_result(self.self_ap_mac, current_bssid, current_rssi, current_channel)

                    current_bssid = bssid_match.group(1).lower()
                    current_rssi = None
                    current_channel = None

                sig = re.search(r'signal:\s*([-\d.]+)\s*dBm', line)
                if sig:
                    current_rssi = float(sig.group(1))

                ch = re.search(r'DS Parameter set: channel\s+(\d+)', line)
                if ch:
                    current_channel = int(ch.group(1))

            if current_bssid and current_rssi is not None:
                self._process_scan_result(self.self_ap_mac, current_bssid, current_rssi, current_channel)

        except Exception as e:
            print(f"Error performing AP scan: {e}")

    def _process_scan_result(self, scanner_mac, detected_ap_mac, rssi, channel):
        """
        Insert/update path loss values and channel metadata for a discovered AP.
        """
        with self.lock:
            tx_power = self.ap_tx_power.get(detected_ap_mac, DEFAULT_POWER)
            path_loss = tx_power - rssi
            is_own = 1 if detected_ap_mac in self.own_network_aps else 0

            if channel:
                self.ap_channels[detected_ap_mac] = channel

            ap_channel = self.ap_channels.get(detected_ap_mac, 0)

            if scanner_mac not in self.matrix_data:
                self.matrix_data[scanner_mac] = {}

            self.matrix_data[scanner_mac][detected_ap_mac] = [path_loss, ap_channel, is_own]

            if detected_ap_mac not in self.col_order:
                self.col_order.append(detected_ap_mac)

    def parse_logread_line(self, line):
        """
        Parse live log messages from `logread -f` for association events or RSSI scan patterns.
        Returns a structured event tuple or None.
        """
        signal_match = re.search(r'STA\s+([0-9a-fA-F:]{17}).*signal\s*([-\d.]+)\s*dBm', line, re.IGNORECASE)
        if signal_match:
            return None

        scan_match = re.search(r'scan.*?([0-9a-fA-F:]{17}).*?([-\d.]+).*?ch.*(\d+)', line, re.IGNORECASE)
        if scan_match:
            return ('scan', None, scan_match.group(1).lower(), float(scan_match.group(2)), int(scan_match.group(3)))

        assoc_match = re.search(r'(associated|authenticated).*?STA\s+([0-9a-fA-F:]{17})', line, re.IGNORECASE)
        if assoc_match:
            return ('assoc', assoc_match.group(2).lower())

        disassoc_match = re.search(r'(disassociated|deauthenticated).*?STA\s+([0-9a-fA-F:]{17})', line, re.IGNORECASE)
        if disassoc_match:
            return ('disassoc', disassoc_match.group(2).lower())

        return None

    def handle_log_event(self, event):
        """
        Apply parsed log event to update matrix, connection list, or remove stale clients.
        """
        if not event:
            return

        with self.lock:
            if event[0] == 'scan':
                _, client_mac, ap_mac, rssi, channel = event
                if client_mac:
                    self._process_scan_result(client_mac, ap_mac, rssi, channel)

            elif event[0] == 'assoc':
                self.connected_clients.add(event[1])
                self._update_row_order()

            elif event[0] == 'disassoc':
                mac = event[1]
                self.connected_clients.discard(mac)
                self.matrix_data.pop(mac, None)
                self._update_row_order()

    def _update_row_order(self):
        """
        Refresh row ordering to ensure matrix aligns with active devices.
        """
        self.row_order = [self.self_ap_mac] if self.self_ap_mac else []
        self.connected_clients = self._get_connected_clients()
        self.row_order.extend(sorted(self.connected_clients))

    def get_matrix(self):
        """
        Convert collected matrix metadata into a fixed NumPy 3D array format.
        Returns None if empty.
        """
        with self.lock:
            if not self.row_order or not self.col_order:
                return None

            m, n = len(self.row_order), len(self.col_order)
            matrix = np.full((m, n, 3), np.nan)

            for i, row_mac in enumerate(self.row_order):
                for j, col_mac in enumerate(self.col_order):
                    if row_mac in self.matrix_data and col_mac in self.matrix_data[row_mac]:
                        matrix[i, j, :] = self.matrix_data[row_mac][col_mac]

            return matrix

    def save_matrix(self):
        """
        Persist current matrix state to JSON and a matching .npy file.
        """
        with self.lock:
            data = {
                'timestamp': datetime.now().isoformat(),
                'self_ap_mac': self.self_ap_mac,
                'row_order': self.row_order,
                'col_order': self.col_order,
                'matrix_data': self.matrix_data,
                'shape': f"{len(self.row_order)}x{len(self.col_order)}x3"
            }

            try:
                with open(self.output_file, 'w') as f:
                    json.dump(data, f, indent=2)

                matrix = self.get_matrix()
                if matrix is not None:
                    np.save(self.output_file.replace('.json', '.npy'), matrix)

            except Exception as e:
                print(f"Error saving matrix: {e}")

    def monitor_logread(self):
        """
        Stream system logs in real-time and update matrix based on events.
        """
        try:
            proc = subprocess.Popen(['logread', '-f'],
                                   stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE,
                                   text=True, bufsize=1)

            for line in proc.stdout:
                event = self.parse_logread_line(line)
                if event:
                    self.handle_log_event(event)
                    self.save_matrix()

        except Exception as e:
            print(f"Error monitoring logread: {e}")

    def periodic_scan(self, interval=SELF_SCAN_INTERVAL):
        """
        Execute recurring Wi-Fi scanning and persist results.
        """
        print(f"Starting periodic AP scan (every {interval}s)...")
        while True:
            try:
                self._update_row_order()
                self.perform_ap_scan()
                self._get_dawn_network_info()
                self.save_matrix()
                time.sleep(interval)

            except Exception as e:
                print(f"Error in periodic scan: {e}")
                time.sleep(interval)


def main():
    """
    Entry point: initializes WiFiMatrix, starts log monitor thread, and runs scan loop.
    """
    matrix = WiFiMatrix(output_file="/tmp/interference_graph.json")

    t = threading.Thread(target=matrix.monitor_logread, daemon=True)
    t.start()

    try:
        matrix.periodic_scan(interval=20)
    except KeyboardInterrupt:
        matrix.save_matrix()


if __name__ == "__main__":
    main()
