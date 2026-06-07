import yaml
import numpy as np
from .helper import Params
from collections import deque
from typing import Dict, List, Tuple

with open("configs/policy_guradrails.yaml", "r") as f:
    config = yaml.safe_load(f)

def map_sinr_to_rate_per(sinr_db: float, bw_mhz: float, sinr_req: np.ndarray, rates_20mhz: np.ndarray) -> Tuple[float, float]:
    """Map SINR -> rate (Mbps) and PER (packet error rate)."""
    if sinr_db < sinr_req[0]:
        return 0.0, 1.0
    idx = np.searchsorted(sinr_req, sinr_db, side="right") - 1
    idx = int(np.clip(idx, 0, len(rates_20mhz) - 1))
    rate_20 = float(rates_20mhz[idx])
    rate_mbps = rate_20 * (bw_mhz / 20.0)

    sinr_lin = 10 ** (sinr_db / 10.0)
    ber = 0.5 * np.exp(-sinr_lin)
    n_bits = 12000
    per = 1.0 - (1.0 - ber) ** n_bits
    per = float(np.clip(per, 0.001, 0.999))
    return rate_mbps, per


def rrm_sim_python(obss_threshold_dbm: float, ap_tx_power_dbm: float, channel_width_mhz: float) -> Dict[str, object]:
    """Deterministic Wi-Fi RRM simulator (keeps behavior consistent with your MATLAB sim)."""
    BT_TX_POWER_DBM = 2.0
    N_PACKETS = 50
    AP_MAIN = np.array([0.0, 0.0])
    AP_OBSS = np.array([25.0, 25.0])
    BT1 = np.array([4.0, 12.0])
    BT2 = np.array([4.0, -12.0])

    # STA grid (25 clients)
    xg, yg = np.meshgrid(np.arange(2, 23, 5), np.arange(-8, 9, 4))
    sta_locations = np.column_stack([xg.ravel(), yg.ravel()])[:25]
    n_clients = len(sta_locations)

    def pathloss(d: float) -> float:
        d0, pl_d0, n_exp = 1.0, 40.0, 3.8
        return pl_d0 + 10.0 * n_exp * np.log10(max(d, d0) / d0)

    sinr_req = np.array([0, 1.5, 3.5, 5, 8, 10, 12, 13, 15, 17, 18, 20])
    rates_20mhz = np.array([6.5, 13, 19.5, 26, 39, 52, 58.5, 65, 78, 86.7, 97.5, 108.3])

    bw_hz = channel_width_mhz * 1e6
    noise_floor_dbm = -174.0 + 10.0 * np.log10(bw_hz) + 7.0
    noise_floor_mw = 10.0 ** (noise_floor_dbm / 10.0)

    throughput_samples: List[float] = []
    per_samples: List[float] = []
    sinr_samples: List[float] = []
    rssi_samples: List[float] = []
    interf_samples: List[float] = []

    client_thr = np.zeros(n_clients)
    client_retry = np.zeros(n_clients)

    for _ in range(N_PACKETS):
        for c, rx_loc in enumerate(sta_locations):
            pl_main = pathloss(np.linalg.norm(rx_loc - AP_MAIN))
            p_sig_mw = 10 ** ((ap_tx_power_dbm - pl_main) / 10.0)

            pl_ap2 = pathloss(np.linalg.norm(rx_loc - AP_OBSS))
            p_ap2_mw = 10 ** ((12.0 - pl_ap2) / 10.0)

            p_bt1_mw = 10 ** ((BT_TX_POWER_DBM - pathloss(np.linalg.norm(rx_loc - BT1))) / 10.0)
            p_bt2_mw = 10 ** ((BT_TX_POWER_DBM - pathloss(np.linalg.norm(rx_loc - BT2))) / 10.0)

            total_interf_mw = noise_floor_mw + p_ap2_mw + p_bt1_mw + p_bt2_mw
            interf_dbm = 10.0 * np.log10(total_interf_mw)

            if interf_dbm < obss_threshold_dbm:
                interf_for_sinr = noise_floor_mw
                utilization = 0.1
            else:
                interf_for_sinr = total_interf_mw
                utilization = 0.4

            sinr_lin = p_sig_mw / interf_for_sinr
            sinr_db = 10.0 * np.log10(sinr_lin)
            rate_mbps, per = map_sinr_to_rate_per(sinr_db, channel_width_mhz, sinr_req, rates_20mhz)
            eff_thr = rate_mbps * (1.0 - per) * (1.0 - utilization)

            throughput_samples.append(eff_thr)
            per_samples.append(per)
            sinr_samples.append(sinr_db)
            rssi_samples.append(10.0 * np.log10(p_sig_mw))
            interf_samples.append(interf_dbm)

            client_thr[c] += eff_thr
            client_retry[c] += per

    throughput_arr = np.array(throughput_samples)
    per_arr = np.array(per_samples)
    sinr_arr = np.array(sinr_samples)
    rssi_arr = np.array(rssi_samples)
    interf_arr = np.array(interf_samples)

    avg_thr = client_thr / N_PACKETS
    avg_retry_pct = (client_retry / N_PACKETS) * 100.0
    flags = (avg_thr < 50.0) & (avg_retry_pct > 50.0)
    flagged_clients = int(np.sum(flags))
    # offline_logger.debug("Flagged clients: %d", flagged_clients)

    return {
        "P50_Throughput": float(np.percentile(throughput_arr, 50)),
        "P95_Throughput": float(np.percentile(throughput_arr, 95)),
        "Mean_Throughput": float(np.mean(throughput_arr)),
        "P95_Retry_Rate": float(np.percentile(per_arr, 95)),
        "Median_SINR": float(np.median(sinr_arr)),
        "Median_RSSI": float(np.median(rssi_arr)),
        "Median_Interf": float(np.median(interf_arr)),
        "Flagged_Clients": flagged_clients,
        "ClientFlags": flags.tolist(),
    }

def simulate_postproc(sim_results: Dict[str, object], params: Params, recent_p50: deque[float]) -> Dict[str, object]:
    """Turn raw sim outputs into metrics used by the optimizer."""
    retry_p95_pct = float(sim_results["P95_Retry_Rate"]) * 100.0  # original returned value assumed fractional
    thr_p50 = float(sim_results["P50_Throughput"])
    eirp_violation = params.tx_power_dbm + config['ANTENNA_GAIN_DB']
    flagged_clients = int(sim_results["Flagged_Clients"])
    client_flag_ratio = flagged_clients / max(1, len(sim_results["ClientFlags"]))

    recent_p50.append(thr_p50)
    smoothed_p50 = float(np.mean(list(recent_p50)))

    return {
        "Throughput_p50": smoothed_p50,
        "Retry_p95": retry_p95_pct,
        "EIRP_violation": eirp_violation,
        "Flag_ratio": client_flag_ratio,
    }