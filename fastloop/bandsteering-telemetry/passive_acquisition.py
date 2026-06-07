#!/usr/bin/env python3

import socket
import struct
import time
import json
import re
import hmac
import hashlib
import subprocess
from collections import defaultdict
from datetime import datetime
import sys
import os
import math
import statistics



with open("var.csv", "w") as file:
    file.write("timestamp,client_mac,variance_s2,uplink_bytes_per_s,downlink_bytes_per_s\n")

with open("delay.csv", "w") as file:
    file.write("timestamp,client_mac,delay_ms\n")



def get_keys(filepath=".env"):
    def load_env(filepath):
        env = {}
        if os.path.exists(filepath):
            with open(filepath, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, value = line.split("=", 1)
                    env[key.strip()] = value.strip()
        return env

    env_vars = load_env(filepath)
    secret_key = env_vars.get("SECRET_KEY")
    fernet_key = env_vars.get("FERNET_KEY")

    if not os.path.exists(filepath) or secret_key is None or fernet_key is None:
        if secret_key is None:
            secret_key = subprocess.run(
                ['openssl', 'rand', '-hex', '32'],
                capture_output=True, text=True
            ).stdout.strip()

        if fernet_key is None:
            try:
                from cryptography.fernet import Fernet
                fernet_key = Fernet.generate_key().decode()
            except Exception:
                fernet_key = "dummy_fernet_key"

        with open(filepath, "w") as f:
            f.write(f"SECRET_KEY={secret_key}\n")
            f.write(f"FERNET_KEY={fernet_key}\n")

    os.environ["SECRET_KEY"] = secret_key
    os.environ["FERNET_KEY"] = fernet_key

    return tuple([secret_key.encode(), fernet_key.encode()])

SECRET_KEY, FERNET_KEY = get_keys()

try:
    from cryptography.fernet import Fernet
    HAS_CRYPTO = True
except ImportError:
    HAS_CRYPTO = False

class RetryMonitorPro:
    MAX_RATE_MBPS = 866.67

    def __init__(self, monitor_iface="mon0", sampling_time=10, target_client=None, hash_macs=False):
        self.monitor_iface = monitor_iface
        self.sampling_time = sampling_time
        self.target_client = target_client.lower().replace('-', ':') if target_client else None
        self.hash_macs = hash_macs

        self.stats = defaultdict(lambda: {
            'ap_to_client': {'total': 0, 'retries': 0, 'total_bytes':0},
            'client_to_ap': {'total': 0, 'retries': 0, 'total_bytes':0}
        })

        self.data_frames = []
        self.client_ack_delays = defaultdict(list)

        self.ap_iface = self._find_ap_interface()
        self.associated_clients = set()
        self._update_associated_clients()
        self.ap_mac = self._get_ap_mac()
        if self.ap_mac:
            self.ap_mac = self.ap_mac.lower()

    def _sha256_hash(self, value: str) -> str:
        if not value:
            return None
        return hmac.new(SECRET_KEY, value.encode("utf-8"), hashlib.sha256).hexdigest()

    def _find_ap_interface(self):
        possible_names = ['ap0', 'phy0-ap0', 'wlan0', 'wlan0-1']
        try:
            result = subprocess.run(['iw', 'dev'], capture_output=True, text=True, timeout=2)
            current_iface = None
            for line in result.stdout.split('\n'):
                line = line.strip()
                if line.startswith('Interface '):
                    current_iface = line.split()[1]
                elif 'type AP' in line and current_iface:
                    return current_iface
        except Exception:
            pass
        for name in possible_names:
            try:
                if os.path.exists(f'/sys/class/net/{name}/address'):
                    return name
            except Exception:
                continue
        print("Warning: Could not auto-detect AP interface. Defaulting to 'phy0-ap0'.", file=sys.stderr)
        return 'phy0-ap0'

    def _get_ap_mac(self):
        try:
            with open(f'/sys/class/net/{self.ap_iface}/address', 'r') as f:
                return f.read().strip().lower()
        except Exception as e:
            print(f"Warning: Could not get AP MAC for {self.ap_iface}. {e}", file=sys.stderr)
            return None

    def _update_associated_clients(self):
        try:
            result = subprocess.run(['iw', 'dev', self.ap_iface, 'station', 'dump'],
                                    capture_output=True, text=True, timeout=2)
            clients = set()
            for line in result.stdout.split('\n'):
                if line.startswith('Station '):
                    mac = line.split()[1].lower()
                    clients.add(mac)
            self.associated_clients = clients
            return clients
        except Exception as e:
            print(f"Warning: Could not update associated clients. {e}", file=sys.stderr)
            return set()

    def _is_multicast_broadcast(self, mac):
        if not mac or len(mac) < 2:
            return True
        if mac == 'ff:ff:ff:ff:ff:ff':
            return True
        try:
            first_octet = int(mac.split(':')[0], 16)
            return bool(first_octet & 0x01)
        except Exception:
            return True

    def _parse_radiotap_header(self, packet):
        """
        Parses the Radiotap header and returns (header_length, payload, tsft_us or None)
        Follows Radiotap spec: checks presence bitmaps dynamically to locate TSFT.
        """
        if len(packet) < 8:
            return None, None, None

        version = packet[0]
        pad = packet[1]
        rt_len = struct.unpack_from("<H", packet, 2)[0]
        if rt_len > len(packet):
            return None, None, None

        # Read presence bitmaps (each 4 bytes, possibly extended)
        offset = 4
        presence_flags = []
        while True:
            if offset + 4 > len(packet):
                break
            present = struct.unpack_from("<I", packet, offset)[0]
            presence_flags.append(present)
            offset += 4
            # If highest bit (bit 31) is not set, no more bitmaps follow
            if not (present & 0x80000000):
                break

        tsft_us = None
        field_offset = offset
        # If first bitmap's bit 0 (TSFT present)
        if len(presence_flags) > 0 and (presence_flags[0] & 0x1):
            try:
                # TSFT is 8 bytes starting at 'field_offset'
                if field_offset + 8 <= len(packet):
                    tsft_us = struct.unpack_from("<Q", packet, field_offset)[0]
            except Exception:
                tsft_us = None
            field_offset += 8

        # Return payload (after full radiotap header)
        payload = packet[rt_len:] if rt_len <= len(packet) else None
        return rt_len, payload, tsft_us


    def _format_mac(self, mac_bytes):
        return ':'.join(f'{b:02x}' for b in mac_bytes).lower()

    def _parse_80211_header(self, packet):
        if len(packet) < 10:
            return None
        fc = struct.unpack('<H', packet[0:2])[0]
        frame_type = (fc >> 2) & 0x3
        subtype = (fc >> 4) & 0xF
        retry = bool(fc & 0x0800)
        to_ds = bool(fc & 0x0100)
        from_ds = bool(fc & 0x0200)

        def safe_slice(b, a, bidx):
            return b[a:bidx] if len(b) >= bidx else None

        addr1_bytes = safe_slice(packet, 4, 10)
        addr2_bytes = safe_slice(packet, 10, 16)
        addr3_bytes = safe_slice(packet, 16, 22)

        if frame_type == 2:
            if addr1_bytes is None or addr2_bytes is None:
                return None
            addr1 = self._format_mac(addr1_bytes)
            addr2 = self._format_mac(addr2_bytes)

            if not to_ds and from_ds:
                direction = 'ap_to_client'
                client_mac = addr1
            elif to_ds and not from_ds:
                direction = 'client_to_ap'
                client_mac = addr2
            else:
                return None

            sa = self._format_mac(addr2_bytes) if addr2_bytes else None
            da = self._format_mac(addr1_bytes) if addr1_bytes else None
            ta = self._format_mac(addr3_bytes) if addr3_bytes else sa

            return {
                'kind': 'data',
                'retry': retry,
                'direction': direction,
                'client_mac': client_mac,
                'sa': sa,
                'da': da,
                'ta': ta
            }

        elif frame_type == 1 and subtype == 13:
            if addr1_bytes is None:
                return None
            ra = self._format_mac(addr1_bytes)
            return {
                'kind': 'ack',
                'ra': ra
            }

        return None

    def process_packet(self, packet):
        rt_len, dot11_packet, tsft_us = self._parse_radiotap_header(packet)
        if not dot11_packet:
            return

        frame_info = self._parse_80211_header(dot11_packet)
        if not frame_info:
            return

        # Use TSFT if available, fallback to monotonic
        t_ref = tsft_us / 1e6 if tsft_us is not None else time.monotonic()

        if frame_info['kind'] == 'data':
            client_mac = frame_info['client_mac']
            if self._is_multicast_broadcast(client_mac):
                return
            if client_mac not in self.associated_clients:
                return
            if self.target_client and client_mac != self.target_client:
                return

            direction = frame_info['direction']
            is_retry = frame_info['retry']

            self.stats[client_mac][direction]['total'] += 1
            self.stats[client_mac][direction]['total_bytes'] += len(packet)
            if is_retry:
                self.stats[client_mac][direction]['retries'] += 1

            self.data_frames.append({
                'timestamp': t_ref,
                'sa': frame_info.get('sa'),
                'da': frame_info.get('da'),
                'direction': direction,
                'used': False
            })

        elif frame_info['kind'] == 'ack':
            ra = frame_info['ra']
            if not self.ap_mac or ra != self.ap_mac:
                return

            t_ack = t_ref

            unpaired = sorted(
                [d for d in self.data_frames if not d['used'] and d.get('sa') and d.get('direction') == 'ap_to_client'],
                key=lambda x: x['timestamp']
            )

            matched = None
            for d in unpaired:
                if d.get('sa') and d.get('sa') == ra:
                    matched = d
                    break

            if not matched:
                return

            delay_us = (t_ack - matched['timestamp']) * 1e6
            matched['used'] = True
            client_mac = matched.get('da')
            if not client_mac:
                return

            client_mac = client_mac.lower()
            self.client_ack_delays[client_mac].append(delay_us)

            try:
                with open("delay.csv", "a") as df:
                    ts = datetime.now().isoformat()
                    delay_ms = delay_us / 1000.0
                    df.write(f"{ts},{client_mac},{delay_ms:.6f}\n")
            except Exception as e:
                print(f"[WARN] Failed to write delay.csv: {e}", file=sys.stderr)

    def parse_all_station_data(self, interface: str) -> dict:
        """
            parse iw/iwinfo to gather station/final stat
        """
        clients = {}
        try:
            cmd_iw = ['iw', 'dev', interface, 'station', 'dump']
            result_iw = subprocess.run(cmd_iw, capture_output=True, text=True, check=True, timeout=3)
            current_mac = None
            for line in result_iw.stdout.splitlines():
                line = line.strip()
                if line.startswith('Station'):
                    current_mac = line.split()[1].lower()
                    clients[current_mac] = {
                        "rssi_dbm": None,
                        "tx_rate_mbps": None,
                        "rx_rate_mbps": None,
                        "tx_retries_count": None,
                        "tx_packets_count": None
                    }
                    continue
                if not current_mac or current_mac not in clients:
                    continue
                if line.startswith('signal:'):
                    clients[current_mac]['rssi_dbm'] = float(line.split(':')[1].strip().split()[0])
                elif line.startswith('tx retries:'):
                    try:
                        clients[current_mac]['tx_retries_count'] = int(line.split(':')[1].strip())
                    except Exception:
                        pass
                elif line.startswith('tx packets:'):
                    try:
                        clients[current_mac]['tx_packets_count'] = int(line.split(':')[1].strip())
                    except Exception:
                        pass
                elif line.startswith('tx bitrate:'):
                    match = re.search(r'([\d\.]+)\s*MBit/s', line)
                    if match:
                        clients[current_mac]['tx_rate_mbps'] = float(match.group(1))
                elif line.startswith('rx bitrate:'):
                    match = re.search(r'([\d\.]+)\s*MBit/s', line)
                    if match:
                        clients[current_mac]['rx_rate_mbps'] = float(match.group(1))
        except Exception as e:
            print(f"Error parsing 'iw' data: {e}", file=sys.stderr)

        try:
            cmd_iwinfo = ['iwinfo', interface, 'assoclist']
            result_iwinfo = subprocess.run(cmd_iwinfo, capture_output=True, text=True, check=True, timeout=3)
            for line in result_iwinfo.stdout.splitlines():
                mac_match = re.match(r'([0-9A-F:]{17})', line, re.IGNORECASE)
                if not mac_match:
                    continue
                mac = mac_match.group(1).lower()
                if mac in clients:
                    snr_match = re.search(r'\(SNR\s*(\d+)\)', line)
                    if snr_match:
                        clients[mac]['snr_db'] = int(snr_match.group(1))
        except Exception as e:
            pass

        return clients

    def calculate_qoe_score_A(self, snapshot_stats: dict) -> float:
        WEIGHT_SNR = 0.5
        WEIGHT_RSSI = 0.5
        score = 0.0
        snr = snapshot_stats.get('snr_db')
        if snr is not None:
            score += WEIGHT_SNR * snr
        rssi = snapshot_stats.get('rssi_dbm')
        if rssi is not None:
            rssi_score = 100 + rssi
            score += WEIGHT_RSSI * rssi_score
        return round(score, 2)

    def calculate_qoe_score_B(self, snapshot_stats: dict, packet_capture_stats: dict) -> float:
        VERY_LOW_WEIGHT = 0.01
        score = 0.0
        try:
            tx_packets = packet_capture_stats.get('client_to_ap', {}).get('total_packets', 0)
            tx_retries = packet_capture_stats.get('client_to_ap', {}).get('retry_packets', 0)
            rx_packets = packet_capture_stats.get('ap_to_client', {}).get('total_packets', 0)
            rx_retries = packet_capture_stats.get('ap_to_client', {}).get('retry_packets', 0)
            ar = packet_capture_stats.get('retry_asymmetry', 0)

            rx_weight = (rx_packets/10) / (1.0 + (rx_packets/10))
            tx_weight = (tx_packets/10) /(1.0 + (tx_packets/10))
            score += rx_weight*tx_weight*abs(ar)

            delta_percent_str = snapshot_stats.get('tx_rx_rate_delta_percent')
            if delta_percent_str is not None:
                delta_percent = float(delta_percent_str)
                score += VERY_LOW_WEIGHT * delta_percent
        except Exception as e:
            return None
        return round(score, 2)

    def get_results(self):
        """
        Get Results: add ack variance stats for clients 
        """
        self._update_associated_clients()
        all_client_stats = self.parse_all_station_data(self.ap_iface)
        results = {
            'timestamp': datetime.now().isoformat(),
            'sampling_time': self.sampling_time,
            'ap_mac': self._sha256_hash(self.ap_mac) if self.hash_macs else self.ap_mac,
            'associated_clients_count': len(self.associated_clients),
            'clients': []
        }

        all_known_clients = set(all_client_stats.keys()).union(self.stats.keys()).union(self.client_ack_delays.keys())

        if self.target_client:
            target = self.target_client.lower()
            all_known_clients = {c for c in all_known_clients if c == target}

        for client_mac in all_known_clients:
            data = self.stats.get(client_mac, {
                'ap_to_client': {'total': 0, 'retries': 0, 'total_bytes': 0},
                'client_to_ap': {'total': 0, 'retries': 0, 'total_bytes': 0}
            })
            ap_to_client = data['ap_to_client']
            client_to_ap = data['client_to_ap']

            ap_retry_rate = (ap_to_client['retries'] / ap_to_client['total'] * 100
                             if ap_to_client['total'] > 0 else 0)
            client_retry_rate = (client_to_ap['retries'] / client_to_ap['total'] * 100
                                 if client_to_ap['total'] > 0 else 0)
            asymmetry = ap_retry_rate - client_retry_rate

            packet_capture_stats = {
                'ap_to_client': {
                    'total_packets': ap_to_client['total'],
                    'retry_packets': ap_to_client['retries'],
                    'retry_rate_percent': round(ap_retry_rate, 2)
                },
                'client_to_ap': {
                    'total_packets': client_to_ap['total'],
                    'retry_packets': client_to_ap['retries'],
                    'retry_rate_percent': round(client_retry_rate, 2)
                },
                'throughput (ap side view)': {
                    'uplink': client_to_ap.get('total_bytes', 0) / max(1, self.sampling_time),
                    'downlink': ap_to_client.get('total_bytes', 0) / max(1, self.sampling_time)
                },
                'retry_asymmetry': round(asymmetry, 2)
            }

            client_details = all_client_stats.get(client_mac, {})

            tx_rx_rate_delta_percent = None
            tx_retry_rate_percent = None

            tx_rate = client_details.get('tx_rate_mbps')
            rx_rate = client_details.get('rx_rate_mbps')
            if tx_rate is not None and rx_rate is not None:
                delta = abs(tx_rate - rx_rate)
                tx_rx_rate_delta_percent = (100 * delta) / self.MAX_RATE_MBPS

            tx_packets = client_details.get('tx_packets_count')
            tx_retries = client_details.get('tx_retries_count')
            if tx_packets is not None and tx_retries is not None:
                total_tx = tx_packets + tx_retries
                if total_tx > 0:
                    tx_retry_rate_percent = (tx_retries / total_tx) * 100
                else:
                    tx_retry_rate_percent = 0.0

            snapshot_stats = {
                'rssi_dbm': client_details.get('rssi_dbm'),
                'snr_db': client_details.get('snr_db'),
                'tx_rate_mbps': tx_rate,
                'rx_rate_mbps': rx_rate,
                'tx_retry_rate_percent': (f"{tx_retry_rate_percent:.2f}" if tx_retry_rate_percent is not None else None),
                'tx_rx_rate_delta_percent': (f"{tx_rx_rate_delta_percent:.2f}" if tx_rx_rate_delta_percent is not None else None)
            }

            qoe_score_A = self.calculate_qoe_score_A(snapshot_stats)
            qoe_score_B = self.calculate_qoe_score_B(snapshot_stats, packet_capture_stats)

            ack_stats = None
            if client_mac in self.client_ack_delays and len(self.client_ack_delays[client_mac]) > 0:
                delays = self.client_ack_delays[client_mac]
                mean_delay_us = statistics.mean(delays)
                var_delay_us2 = statistics.variance(delays) if len(delays) > 1 else 0.0
                # Provide both µs and ms units plus s^2 for CSV convenience
                ack_stats = {
                    'samples': len(delays),
                    'mean_delay_us': round(mean_delay_us, 2),
                    'variance_us2': round(var_delay_us2, 2),
                    'mean_delay_ms': round(mean_delay_us / 1000.0, 4),
                    'variance_ms2': round(var_delay_us2 / 1e6, 6),
                    'variance_s2': round(var_delay_us2 / (1e6**2), 12)
                }

            client_result = {
                'client_mac': self._sha256_hash(client_mac) if self.hash_macs else client_mac,
                'qoe_score_A_snr_rssi': qoe_score_A,
                'qoe_score_B_formula': qoe_score_B,
                'phy_layer_snapshot_stats': snapshot_stats,
                'packet_capture_stats': packet_capture_stats,
                'ack_variance_stats': ack_stats
            }

            results['clients'].append(client_result)

        return results


    def capture(self, continuous=False):
        """
        collects packets and outputs JSON every sampling_time
        """
        try:
            sock = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(0x0003))
            sock.bind((self.monitor_iface, 0))
            sock.settimeout(0.1)
        except Exception as e:
            return {'error': f'Failed to create socket on {self.monitor_iface}: {str(e)}'}

        try:
            if continuous:
                start_time = time.time()
                while True:
                    try:
                        packet, _ = sock.recvfrom(4096)
                        self.process_packet(packet)
                    except socket.timeout:
                        pass

                    if time.time() - start_time >= self.sampling_time:
                        results = self.get_results()
                        print(json.dumps(results, indent=2))

                        # --- Save variance (in seconds^2) + throughput to var.csv ---
                        try:
                            with open("var.csv", "a") as f:
                                ts = datetime.now().isoformat()
                                for client in results.get("clients", []):
                                    ack_stats = client.get("ack_variance_stats")
                                    pkt_stats = client.get("packet_capture_stats", {})
                                    thr = pkt_stats.get("throughput (ap side view)", {})
                                    uplink = thr.get("uplink", 0.0)     # bytes/sec
                                    downlink = thr.get("downlink", 0.0)

                                    if ack_stats and ack_stats.get("variance_s2") is not None:
                                        # variance_s2 is in seconds^2 already
                                        var_s2 = ack_stats["variance_s2"]
                                        f.write(f"{ts},{client['client_mac']},{var_s2:.12e},{uplink:.2f},{downlink:.2f}\n")
                        except Exception as e:
                            print(f"[WARN] Failed to write var.csv: {e}", file=sys.stderr)

                        # reset stats & ack buffers for next interval
                        self.stats.clear()
                        self.data_frames.clear()
                        self.client_ack_delays.clear()
                        start_time = time.time()
            else:
                end_time = time.time() + self.sampling_time
                while time.time() < end_time:
                    try:
                        packet, _ = sock.recvfrom(4096)
                        self.process_packet(packet)
                    except socket.timeout:
                        pass
                return self.get_results()

        except KeyboardInterrupt:
            if continuous:
                results = self.get_results()
                print(json.dumps(results, indent=2))
            return {'status': 'stopped'}
        finally:
            sock.close()


if __name__ == '__main__':
        client_mac = sys.argv[4] if len(sys.argv) > 4 else None
        sampling_time = int(sys.argv[3]) if len(sys.argv) > 3 else 10
        continuous = sys.argv[2].lower() == 'true' if len(sys.argv) > 2 else False
        hash_macs = sys.argv[1].lower() == 'true' if len(sys.argv) > 1 else False

        print(f"Starting retry monitor (CLI mode)")
        print(f"Sampling time: {sampling_time} seconds")
        print(f"Target client: {client_mac if client_mac else 'All clients'}")
        print(f"Continuous: {continuous}")
        print(f"Hash MACs: {hash_macs}\n")

        monitor = RetryMonitorPro(
            monitor_iface='mon0',
            sampling_time=sampling_time,
            target_client=client_mac,
            hash_macs=hash_macs
        )

        results = monitor.capture(continuous=continuous)
        if results:
            print(json.dumps(results, indent=2))
