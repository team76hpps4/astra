#!/usr/bin/env python3

import subprocess
import json
import time
import logging
import re
import csv
import statistics
from pathlib import Path
from typing import Dict, Optional, Tuple, List
from collections import deque


CONFIG = {
    # Interfaces
    'WLAN_24': 'phy0-ap0',
    'WLAN_5': 'phy1-ap0',
    
    # RSSI Thresholds (dBm)
    'RSSI_5G_THRESHOLD': -75,
    'RSSI_DROP_THRESHOLD': -80,
    'RSSI_MIN_CONNECT': -85,
    
    # Timing
    'LOW_RSSI_DURATION': 30,
    'CHECK_INTERVAL': 10,
    'MIN_STEER_INTERVAL': 60,
    
    # Bandwidth Detection
    'BW_INTENSIVE_THRESHOLD': 5000000,
    
    # RTT Thresholds (NEW)
    'RTT_HIGH_THRESHOLD': 100.0,       # ms - Poor RTT
    'RTT_VARIANCE_THRESHOLD': 1000.0,  # ms^2 - High jitter
    'RTT_TARGET': 20.0,                # ms - Target RTT
    'RTT_STEER_IMPROVEMENT': 30.0,     # ms - Min improvement to steer
    'RTT_UPDATE_INTERVAL': 5.0,        # seconds - How often to read RTT stats
    'RTT_SAMPLE_WINDOW': 60,           # seconds - RTT history window
    'RTT_MIN_SAMPLES': 5,              # Min samples for valid RTT stats
    
    # Fail-safes
    'MAX_STEER_ATTEMPTS': 3,
    'STATE_FILE': '/tmp/band_steering_state.json',
    'LOG_FILE': '/var/log/band_steering.log',
    'BAND_STEERING_INTERVAL': 10,
    
    # RTT Data Sources (NEW)
    'RTT_CSV_FILE': './rtt_stats.csv',
    'RTT_LOG_FILE': '/log/rtt_steering.log'
}


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(CONFIG['LOG_FILE']),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger('band_steering')


class StateManager:
    """Manages persistent state for client tracking"""
    
    def __init__(self, state_file: str):
        self.state_file = Path(state_file)
        self.state = self._load_state()
    
    def _load_state(self) -> Dict:
        """Load state from JSON file"""
        if self.state_file.exists():
            try:
                with open(self.state_file, 'r') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                logger.error(f"Failed to load state: {e}")
                return {}
        return {}
    
    def _save_state(self):
        """Save state to JSON file"""
        try:
            with open(self.state_file, 'w') as f:
                json.dump(self.state, f, indent=2)
        except IOError as e:
            logger.error(f"Failed to save state: {e}")
    
    def get_client(self, mac: str) -> Dict:
        """Get client state"""
        return self.state.get(mac, {})
    
    def update_client(self, mac: str, **kwargs):
        """Update client state"""
        if mac not in self.state:
            self.state[mac] = {}
        self.state[mac].update(kwargs)
        self.state[mac]['last_updated'] = time.time()
        self._save_state()
    
    def remove_client(self, mac: str):
        """Remove client from state"""
        if mac in self.state:
            del self.state[mac]
            self._save_state()
    
    def cleanup_stale_clients(self, max_age: int = 3600):
        """Remove clients not seen in max_age seconds"""
        current_time = time.time()
        stale = [
            mac for mac, data in self.state.items()
            if current_time - data.get('last_updated', 0) > max_age
        ]
        
        for mac in stale:
            self.remove_client(mac)
            logger.info(f"Removed stale client {mac}")


class RTTStatsManager:
    """Manages TCP RTT statistics from tcp_rtt.py output"""
    
    def __init__(self, config: Dict):
        self.config = config
        self.rtt_data = {}
        self.last_update = 0.0
        self.csv_read_position = 0
        
    def update_rtt_stats(self):
        """Read new RTT measurements from CSV"""
        if time.time() - self.last_update < self.config['RTT_UPDATE_INTERVAL']:
            return
        
        csv_file = Path(self.config['RTT_CSV_FILE'])
        if not csv_file.exists():
            return
        
        try:
            cutoff_time = time.time() - self.config['RTT_SAMPLE_WINDOW']
            
            with open(csv_file, 'r') as f:
                for _ in range(self.csv_read_position):
                    next(f, None)
                
                reader = csv.reader(f)
                lines_read = 0
                
                for row in reader:
                    lines_read += 1
                    try:
                        if len(row) < 3:
                            continue
                        
                        ts = float(row[0])
                        mac = row[1].lower()
                        rtt_ms = float(row[2])
                        
                        if ts < cutoff_time:
                            continue
                        
                        if mac not in self.rtt_data:
                            self.rtt_data[mac] = deque(maxlen=200)
                        
                        self.rtt_data[mac].append((ts, rtt_ms))
                        
                    except (ValueError, IndexError) as e:
                        logger.debug(f"Failed to parse RTT CSV row: {row} - {e}")
                        continue
                
                self.csv_read_position += lines_read
            
            for mac in list(self.rtt_data.keys()):
                self.rtt_data[mac] = deque(
                    [(ts, rtt) for ts, rtt in self.rtt_data[mac] if ts >= cutoff_time],
                    maxlen=200
                )
                if len(self.rtt_data[mac]) == 0:
                    del self.rtt_data[mac]
            
            self.last_update = time.time()
            
        except Exception as e:
            logger.error(f"Error reading RTT stats: {e}")
    
    def get_client_rtt_metrics(self, mac: str) -> Optional[Dict]:
        """Calculate RTT statistics for a client"""
        mac = mac.lower()
        
        if mac not in self.rtt_data:
            return None
        
        samples = [rtt for _, rtt in self.rtt_data[mac]]
        
        if len(samples) < self.config['RTT_MIN_SAMPLES']:
            return None
        
        mean_rtt = statistics.mean(samples)
        variance = statistics.variance(samples) if len(samples) > 1 else 0.0
        min_rtt = min(samples)
        max_rtt = max(samples)
        
        return {
            'mean_rtt_ms': mean_rtt,
            'variance_ms2': variance,
            'min_rtt_ms': min_rtt,
            'max_rtt_ms': max_rtt,
            'sample_count': len(samples),
            'rtt_quality_score': self._calculate_rtt_quality(mean_rtt, variance)
        }
    
    def _calculate_rtt_quality(self, mean_rtt: float, variance: float) -> float:
        """Calculate RTT quality score (0-100, higher is better)"""
        rtt_score = max(0, 100 - (mean_rtt / self.config['RTT_HIGH_THRESHOLD']) * 100)
        variance_penalty = min((variance / self.config['RTT_VARIANCE_THRESHOLD']) * 50, 50)
        
        return max(0, rtt_score - variance_penalty)


class WiFiInterface:
    """Handles WiFi operations via iw, hostapd, and ubus"""
    
    @staticmethod
    def run_command(cmd: list, check: bool = True) -> Tuple[bool, str]:
        """Run shell command and return success, output"""
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=check,
                timeout=5
            )
            return True, result.stdout
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            logger.error(f"Command failed: {' '.join(cmd)} - {e}")
            return False, ""
    
    @staticmethod
    def get_bssid(interface: str) -> Optional[str]:
        """Get BSSID for interface"""
        success, output = WiFiInterface.run_command(['iw', 'dev', interface, 'info'])
        if success:
            match = re.search(r'addr\s+([0-9a-f:]{17})', output, re.IGNORECASE)
            if match:
                return match.group(1)
        return None
    
    @staticmethod
    def get_client_rssi(mac: str, interface: str) -> Optional[int]:
        """Get RSSI for client on interface"""
        success, output = WiFiInterface.run_command(
            ['iw', 'dev', interface, 'station', 'get', mac],
            check=False
        )
        if success:
            match = re.search(r'signal:\s+(-?\d+)', output)
            if match:
                return int(match.group(1))
        return None
    
    @staticmethod
    def get_clients(interface: str) -> list:
        """Get list of connected client MACs"""
        success, output = WiFiInterface.run_command(
            ['iw', 'dev', interface, 'station', 'dump']
        )
        if success:
            return re.findall(r'Station\s+([0-9a-f:]{17})', output, re.IGNORECASE)
        return []
    
    @staticmethod
    def get_client_stats(mac: str, interface: str) -> Dict:
        """Get detailed stats for client"""
        success, output = WiFiInterface.run_command(
            ['iw', 'dev', interface, 'station', 'get', mac],
            check=False
        )
        stats = {}
        if success:
            for line in output.split('\n'):
                if 'rx bytes:' in line:
                    stats['rx_bytes'] = int(re.search(r'(\d+)', line).group(1))
                elif 'tx bytes:' in line:
                    stats['tx_bytes'] = int(re.search(r'(\d+)', line).group(1))
        return stats
    
    @staticmethod
    def send_bss_transition(mac: str, from_interface: str, to_bssid: str) -> bool:
        """Send BSS transition request via ubus"""
        cmd = [
            'ubus', 'call', f'hostapd.{from_interface}',
            'bss_transition_request',
            json.dumps({
                'addr': mac,
                'disassociation_imminent': False,
                'abridged': 1,
                'neighbors': [to_bssid]
            })
        ]
        success, _ = WiFiInterface.run_command(cmd, check=False)
        return success
    
    @staticmethod
    def supports_5ghz(mac: str, wlan5: str) -> bool:
        """Check if client has ever attempted 5 GHz connection"""
        cmd = ['ubus', 'call', f'hostapd.{wlan5}', 'get_clients']
        success, output = WiFiInterface.run_command(cmd, check=False)
        if success:
            try:
                clients = json.loads(output)
                for client in clients.get('clients', []):
                    if client.get('address', '').lower() == mac.lower():
                        return True
            except json.JSONDecodeError:
                pass
        return False


class BandSteeringManager:
    """Main band steering logic with RTT awareness"""
    
    def __init__(self, config: Dict):
        self.config = config
        self.state = StateManager(config['STATE_FILE'])
        self.wifi = WiFiInterface()
        self.rtt_manager = RTTStatsManager(config)
        
        self.bssid_24 = self.wifi.get_bssid(config['WLAN_24'])
        self.bssid_5 = self.wifi.get_bssid(config['WLAN_5'])
        self.prev_time = time.time()
        
        self.rtt_log_file = self._init_rtt_log()
        
        if not self.bssid_24 or not self.bssid_5:
            raise RuntimeError("Failed to get BSSIDs for interfaces")
        
        logger.info(f"Initialized: 2.4G={self.bssid_24}, 5G={self.bssid_5}")
        logger.info(f"RTT monitoring enabled: CSV={config['RTT_CSV_FILE']}")
    
    def _init_rtt_log(self) -> object:
        """Initialize RTT steering log file"""
        try:
            log_file = open(self.config['RTT_LOG_FILE'], 'a', newline='')
            writer = csv.writer(log_file)
            if Path(self.config['RTT_LOG_FILE']).stat().st_size == 0:
                writer.writerow([
                    'timestamp', 'client_mac', 'action', 'from_band', 'to_band',
                    'pre_rtt_ms', 'pre_rtt_variance', 'post_rtt_ms', 'post_rtt_variance',
                    'rtt_improvement_ms', 'reason'
                ])
                log_file.flush()
            return log_file
        except Exception as e:
            logger.error(f"Failed to open RTT log: {e}")
            return None
    
    def _log_rtt_steering(self, mac: str, action: str, from_band: str, 
                          to_band: str, pre_rtt: Optional[Dict], 
                          post_rtt: Optional[Dict], reason: str):
        """Log RTT-related steering decisions"""
        if not self.rtt_log_file:
            return
        
        try:
            writer = csv.writer(self.rtt_log_file)
            pre_mean = pre_rtt['mean_rtt_ms'] if pre_rtt else None
            pre_var = pre_rtt['variance_ms2'] if pre_rtt else None
            post_mean = post_rtt['mean_rtt_ms'] if post_rtt else None
            post_var = post_rtt['variance_ms2'] if post_rtt else None
            
            improvement = (pre_mean - post_mean) if (pre_mean and post_mean) else None
            
            writer.writerow([
                time.time(), mac, action, from_band, to_band,
                f"{pre_mean:.2f}" if pre_mean else 'N/A',
                f"{pre_var:.2f}" if pre_var else 'N/A',
                f"{post_mean:.2f}" if post_mean else 'N/A',
                f"{post_var:.2f}" if post_var else 'N/A',
                f"{improvement:.2f}" if improvement else 'N/A',
                reason
            ])
            self.rtt_log_file.flush()
        except Exception as e:
            logger.error(f"Failed to log RTT steering: {e}")
    
    def should_steer_to_5g(self, mac: str, rssi_5g: Optional[int],
                          current_band: str, rtt_metrics: Optional[Dict] = None) -> Tuple[bool, str]:
        """Determine if client should be steered to 5 GHz (RTT-enhanced)"""
        if rssi_5g is None or rssi_5g < self.config['RSSI_5G_THRESHOLD']:
            return False, f"5G RSSI insufficient ({rssi_5g} dBm)"
        
        if not self.wifi.supports_5ghz(mac, self.config['WLAN_5']):
            return False, "Client doesn't support 5 GHz"
        
        client_state = self.state.get_client(mac)
        last_steer = client_state.get('last_steer_attempt', 0)
        if time.time() - last_steer < self.config['MIN_STEER_INTERVAL']:
            return False, "Too soon since last steering attempt"
        
        attempts = client_state.get('steer_attempts_24_to_5', 0)
        if attempts >= self.config['MAX_STEER_ATTEMPTS']:
            return False, f"Max steering attempts reached ({attempts})"
        
        if rtt_metrics:
            mean_rtt = rtt_metrics.get('mean_rtt_ms', 0)
            variance = rtt_metrics.get('variance_ms2', 0)
            
            if mean_rtt > self.config['RTT_HIGH_THRESHOLD']:
                return True, f"High RTT on 2.4G ({mean_rtt:.1f}ms) - steering to 5G"
            
            if variance > self.config['RTT_VARIANCE_THRESHOLD']:
                return True, f"High RTT variance on 2.4G ({variance:.1f}ms²) - steering to 5G"
        
        return True, "All conditions met"
    
    def should_downsteer_to_24g(self, mac: str, rssi_5g: int,
                                rtt_metrics: Optional[Dict] = None) -> Tuple[bool, str]:
        """Determine if client should be downsteered to 2.4 GHz (RTT-protected)"""
        if rssi_5g >= self.config['RSSI_DROP_THRESHOLD']:
            self.state.update_client(mac, low_rssi_start=None)
            return False, "5G RSSI is acceptable"
        
        if rtt_metrics:
            mean_rtt = rtt_metrics.get('mean_rtt_ms', float('inf'))
            quality_score = rtt_metrics.get('rtt_quality_score', 0)
            
            if mean_rtt < self.config['RTT_TARGET'] and quality_score > 80:
                logger.info(f"Client {mac}: Low RSSI but excellent RTT ({mean_rtt:.1f}ms), delaying downsteer")
                return False, f"RTT excellent ({mean_rtt:.1f}ms) despite low RSSI"
        
        client_state = self.state.get_client(mac)
        low_rssi_start = client_state.get('low_rssi_start')
        
        if low_rssi_start is None:
            self.state.update_client(mac, low_rssi_start=time.time())
            return False, "Low RSSI detected, monitoring"
        
        duration = time.time() - low_rssi_start
        if duration < self.config['LOW_RSSI_DURATION']:
            return False, f"Low RSSI duration insufficient ({duration:.0f}s)"
        
        return True, f"Sustained low RSSI for {duration:.0f}s"
    
    def should_steer_based_on_rtt(self, mac: str, current_band: str, 
                                  rtt_metrics: Optional[Dict]) -> Tuple[bool, str, str]:
        """NEW: RTT-only steering trigger"""
        if not rtt_metrics:
            return False, "", ""
        
        mean_rtt = rtt_metrics.get('mean_rtt_ms', 0)
        variance = rtt_metrics.get('variance_ms2', 0)
        quality_score = rtt_metrics.get('rtt_quality_score', 100)
        
        if mean_rtt > self.config['RTT_HIGH_THRESHOLD'] or variance > self.config['RTT_VARIANCE_THRESHOLD']:
            target_band = '5' if current_band == '24' else '24'
            
            if current_band == '24':
                if self.wifi.supports_5ghz(mac, self.config['WLAN_5']):
                    rssi_5 = self.wifi.get_client_rssi(mac, self.config['WLAN_5'])
                    if rssi_5 and rssi_5 > self.config['RSSI_5G_THRESHOLD']:
                        return True, target_band, f"RTT degraded: {mean_rtt:.1f}ms (var: {variance:.1f})"
            else:
                rssi_24 = self.wifi.get_client_rssi(mac, self.config['WLAN_24'])
                if rssi_24 and rssi_24 > self.config['RSSI_MIN_CONNECT']:
                    return True, target_band, f"RTT degraded on 5G: {mean_rtt:.1f}ms"
        
        return False, "", ""
    
    def is_bandwidth_intensive(self, mac: str, interface: str) -> bool:
        """Check if client is using high bandwidth"""
        stats = self.wifi.get_client_stats(mac, interface)
        if not stats:
            return False
        
        current_bytes = stats.get('rx_bytes', 0) + stats.get('tx_bytes', 0)
        client_state = self.state.get_client(mac)
        prev_bytes = client_state.get('prev_bytes', 0)
        prev_time = client_state.get('prev_time', time.time())
        
        self.state.update_client(
            mac,
            prev_bytes=current_bytes,
            prev_time=time.time()
        )
        
        if prev_bytes > 0:
            time_diff = time.time() - prev_time
            if time_diff > 0:
                bandwidth = (current_bytes - prev_bytes) / time_diff
                if bandwidth > self.config['BW_INTENSIVE_THRESHOLD']:
                    logger.info(f"Client {mac} bandwidth: {bandwidth/1e6:.2f} Mbps")
                    return True
        
        return False
    
    def steer_client(self, mac: str, from_band: str, to_band: str,
                    to_bssid: str, reason: str, pre_rtt: Optional[Dict] = None):
        """Execute steering action"""
        from_interface = self.config[f'WLAN_{from_band}']
        logger.info(f"Steering {mac}: {from_band} -> {to_band} ({reason})")
        
        success = self.wifi.send_bss_transition(mac, from_interface, to_bssid)
        
        if success:
            key = f'steer_attempts_{from_band}_to_{to_band}'
            client_state = self.state.get_client(mac)
            attempts = client_state.get(key, 0) + 1
            
            self.state.update_client(
                mac,
                last_steer_attempt=time.time(),
                last_steer_reason=reason,
                pre_steer_rtt=pre_rtt,  
                steer_timestamp=time.time(),
                **{key: attempts}
            )
            
            logger.info(f"BSS transition sent successfully (attempt {attempts})")
            
            self._log_rtt_steering(mac, 'steer', from_band, to_band, pre_rtt, None, reason)
        else:
            logger.error(f"Failed to send BSS transition for {mac}")
    
    def validate_post_steer_rtt(self, mac: str):
        """NEW: Validate RTT after steering and rollback if degraded"""
        client_state = self.state.get_client(mac)
        steer_time = client_state.get('steer_timestamp', 0)
        pre_rtt = client_state.get('pre_steer_rtt')
        
        if time.time() - steer_time < 30 or time.time() - steer_time > 120:
            return
        
        if not pre_rtt:
            return
        
        post_rtt = self.rtt_manager.get_client_rtt_metrics(mac)
        
        if not post_rtt:
            return
        
        pre_mean = pre_rtt.get('mean_rtt_ms', 0)
        post_mean = post_rtt.get('mean_rtt_ms', 0)
        
        if post_mean > pre_mean * 1.5:
            logger.warning(f"Client {mac} RTT degraded after steering: {pre_mean:.1f} -> {post_mean:.1f}ms")
            self._log_rtt_steering(mac, 'validation_failed', '', '', pre_rtt, post_rtt, 
                                  "RTT degraded post-steering")
        else:
            logger.info(f"Client {mac} RTT post-steering validation passed: {post_mean:.1f}ms")
            self._log_rtt_steering(mac, 'validation_passed', '', '', pre_rtt, post_rtt, 
                                  "RTT maintained/improved")
        
        self.state.update_client(mac, steer_timestamp=0, pre_steer_rtt=None)
    
    def process_24g_clients(self, orchestrator=None):
        """Process clients on 2.4 GHz band (RTT-enhanced)"""
        self.rtt_manager.update_rtt_stats()
        
        clients = self.wifi.get_clients(self.config['WLAN_24'])
        
        for mac in clients:
            try:
                is_busy, reason = self._is_client_busy(mac, orchestrator)
                if is_busy:
                    logger.info(f"Skipping {mac}: telemetry_daemon has it in state '{reason}'")
                    continue
                
                rssi_24 = self.wifi.get_client_rssi(mac, self.config['WLAN_24'])
                rssi_5 = self.wifi.get_client_rssi(mac, self.config['WLAN_5'])
                
                rtt_metrics = self.rtt_manager.get_client_rtt_metrics(mac)
                if rtt_metrics:
                    logger.debug(f"Client {mac} RTT: {rtt_metrics['mean_rtt_ms']:.1f}ms "
                               f"(quality: {rtt_metrics['rtt_quality_score']:.0f})")
                
                should_steer, reason = self.should_steer_to_5g(mac, rssi_5, '24', rtt_metrics)
                if should_steer:
                    self.steer_client(mac, '24', '5', self.bssid_5, reason, rtt_metrics)
                    continue
                
                should_steer_rtt, target_band, rtt_reason = self.should_steer_based_on_rtt(
                    mac, '24', rtt_metrics
                )
                if should_steer_rtt and target_band == '5':
                    self.steer_client(mac, '24', '5', self.bssid_5, rtt_reason, rtt_metrics)
                    continue
                
                if rssi_5 and rssi_5 > self.config['RSSI_5G_THRESHOLD']:
                    if self.is_bandwidth_intensive(mac, self.config['WLAN_24']):
                        self.steer_client(
                            mac, '24', '5', self.bssid_5,
                            "Bandwidth intensive task detected",
                            rtt_metrics
                        )
                        continue
                
                self.state.update_client(mac, rssi_24=rssi_24, rssi_5=rssi_5)
                
                self.validate_post_steer_rtt(mac)
                
            except Exception as e:
                logger.error(f"Error processing 2.4G client {mac}: {e}")
    
    def process_5g_clients(self, orchestrator=None):
        """Process clients on 5 GHz band (RTT-protected)"""
        self.rtt_manager.update_rtt_stats()
        
        clients = self.wifi.get_clients(self.config['WLAN_5'])
        
        for mac in clients:
            try:
                is_busy, reason = self._is_client_busy(mac, orchestrator)
                if is_busy:
                    logger.info(f"Skipping {mac}: telemetry_daemon has it in state '{reason}'")
                    continue
                
                rssi_5 = self.wifi.get_client_rssi(mac, self.config['WLAN_5'])
                if rssi_5 is None:
                    continue
                
                rtt_metrics = self.rtt_manager.get_client_rtt_metrics(mac)
                if rtt_metrics:
                    logger.debug(f"Client {mac} RTT on 5G: {rtt_metrics['mean_rtt_ms']:.1f}ms")
                
                should_downsteer, reason = self.should_downsteer_to_24g(mac, rssi_5, rtt_metrics)
                if should_downsteer:
                    self.steer_client(mac, '5', '24', self.bssid_24, reason, rtt_metrics)
                    self.state.update_client(mac, low_rssi_start=None)
                    continue
                
                should_steer_rtt, target_band, rtt_reason = self.should_steer_based_on_rtt(
                    mac, '5', rtt_metrics
                )
                if should_steer_rtt and target_band == '24':
                    self.steer_client(mac, '5', '24', self.bssid_24, rtt_reason, rtt_metrics)
                    continue
                
                self.state.update_client(mac, rssi_5=rssi_5)
                
                self.validate_post_steer_rtt(mac)
                
            except Exception as e:
                logger.error(f"Error processing 5G client {mac}: {e}")
    
    def run(self, orchestrator=None):
        """Main loop"""
        logger.info("Band steering manager started with RTT monitoring")
        
        try:
            while True:
                self.process_24g_clients(orchestrator)
                self.process_5g_clients(orchestrator)
                self.state.cleanup_stale_clients()
                time.sleep(self.config['CHECK_INTERVAL'])
                logger.info("One iteration done")
        except KeyboardInterrupt:
            logger.info("Shutting down gracefully")
        except Exception as e:
            logger.error(f"Fatal error: {e}", exc_info=True)
        finally:
            if self.rtt_log_file:
                self.rtt_log_file.close()
    
    def run_once(self, orchestrator):
        """Single iteration (for integration with telemetry_daemon)"""
        if time.time() - self.prev_time < self.config['BAND_STEERING_INTERVAL']:
            return
        
        self.prev_time = time.time()
        
        try:
            self.process_24g_clients(orchestrator)
            self.process_5g_clients(orchestrator)
            self.state.cleanup_stale_clients()
        except KeyboardInterrupt:
            logger.info("Shutting down")
        except Exception as e:
            logger.error(f"Fatal error: {e}", exc_info=True)
    
    def _is_client_busy(self, mac: str, orchestrator) -> tuple[bool, str]:
        """Check if client is busy in telemetry_daemon's workflow"""
        if orchestrator is None:
            return False, "no_orchestrator"
        
        client_monitor = orchestrator.clients.get(mac)
        if not client_monitor:
            return False, "not_tracked"
        
        if client_monitor.state != "idle":
            return True, client_monitor.state
        
        now = time.time()
        if hasattr(client_monitor, 'last_steer_attempt_data'):
            last_attempt = client_monitor.last_steer_attempt_data.get('timestamp', 0)
            if (now - last_attempt) < 60:
                return True, "recent_telemetry_steer"
        
        return False, "idle"


if __name__ == '__main__':
    try:
        manager = BandSteeringManager(CONFIG)
        manager.run()
    except Exception as e:
        logger.error(f"Failed to start: {e}", exc_info=True)
        exit(1)