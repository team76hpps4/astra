import json
import subprocess
import random
import math

MATRIX_FILE = "/tmp/interference_graph.json"
TX_POWER_DBM = 20.0      # default tx power to calculate rssi from pathloss
SCORE_THRESHOLD = 10.0   # hysteresis; target must be this much better to trigger roam

TLOW = -65.0
THIGH = -50.0
MAX_CU = 60.0
RSSI_PENALTY_WEIGHT = 1.0
RSSI_REWARD_WEIGHT = 1.0
CU_PENALTY_WEIGHT = 0.5


class MockRfeqm:
    """
    Placeholder RF-equipment model used for computing synthetic AQI scores
    until the real SDR/measurement pipeline is wired up.
    """

    @staticmethod
    def compute_rfeqm(params, noise_floor):
        """
        Return a synthetic RF quality score in [0, 100] based on the provided
        parameter structure. Currently just random for testing.
        """
        return random.uniform(40, 90)


def frequency_aware_smoothing(scores, alpha_up, alpha_down):
    """
    Apply frequency-aware exponential smoothing to a time series of RF scores.
    For now this is a no-op passthrough used as a placeholder.
    """
    if not scores:
        return [0]
    return scores


rfeqm = MockRfeqm()


def construct_neighbor_hex(bssid, channel):
    """
    Encode a neighbor BSSID and channel into the hex blob expected by
    hostapd's BSS transition request API.
    """
    clean_bssid = bssid.replace(":", "").lower()
    channel_hex = f"{int(channel):02x}"
    suffix = f"ef19000080{channel_hex}090603022a00"
    return f"{clean_bssid}{suffix}"


def calculate_ap_score(rssi, channel_utilization=None):
    """
    Compute a composite AP score from RSSI, channel utilization, and a synthetic
    RF environment metric. Higher scores are better.
    """
    score = 0.0

    if rssi is None:
        return 0.0

    # base: map RSSI into a 0–100-ish scale
    score += (100 + rssi)

    if rssi < TLOW:
        score -= (TLOW - rssi) * RSSI_PENALTY_WEIGHT

    if rssi > THIGH:
        score += (rssi - THIGH) * RSSI_REWARD_WEIGHT

    if channel_utilization is not None and channel_utilization > MAX_CU:
        score -= (channel_utilization - MAX_CU) * CU_PENALTY_WEIGHT

    rfeqm_scores_list = []

    rfeqm_score_raw = rfeqm.compute_rfeqm(
        [{"type": "bluetooth",
          "prob": random.uniform(0.8, 1),
          "duty": random.random(),
          "power": random.random() * 1e-4}],
        1e-8
    )
    rfeqm_scores_list.append(rfeqm_score_raw)

    scores = frequency_aware_smoothing(
        rfeqm_scores_list,
        alpha_up=0.0125,
        alpha_down=0.45,
    )
    aqi_score = scores[-1]

    # penalize heavy interference
    if aqi_score >= 55:
        aqi_score = 0

    return score * 0.45 + 0.55 * aqi_score


def cca_tm_algo(client_mac, current_cu=50.0):
    """
    CCA-based transition manager.
    Reads the interference matrix, scores self vs adjacent APs for a client,
    and triggers a BSS transition request if a better AP exceeds the
    hysteresis threshold.
    """
    try:
        with open(MATRIX_FILE, 'r') as f:
            data = json.load(f)
    except Exception as e:
        print(f"[CCA_TM] Error reading matrix: {e}")
        return

    rows_clients = data['rows_clients']
    cols_aps = data['columns_aps']
    matrix = data['matrix']

    try:
        client_idx = rows_clients.index(client_mac)
    except ValueError:
        print(f"[CCA_TM] Client {client_mac} not found in graph.")
        return

    client_row = matrix[client_idx]

    # self AP (column 0)
    self_entry = client_row[0]
    if not self_entry:
        return

    self_pl, self_channel, _ = self_entry
    self_rssi = TX_POWER_DBM - self_pl

    # find best adjacent-channel AP from same network
    best_adj_pl = float('inf')
    best_adj_idx = -1

    for col_idx, entry in enumerate(client_row):
        if col_idx == 0:
            continue  # skip self AP
        if entry is None:
            continue

        pl, ch, is_same_network = entry

        if is_same_network == 1 and ch != self_channel:
            if pl < best_adj_pl:
                best_adj_pl = pl
                best_adj_idx = col_idx

    if best_adj_idx == -1:
        # no eligible AP to roam to
        return

    best_adj_rssi = TX_POWER_DBM - best_adj_pl

    score_self = calculate_ap_score(self_rssi, current_cu)
    score_target = calculate_ap_score(best_adj_rssi, current_cu)

    # trigger roam if target is sufficiently better
    if (score_target - score_self) > SCORE_THRESHOLD:
        target_bssid = cols_aps[best_adj_idx]
        target_entry = client_row[best_adj_idx]
        target_channel = target_entry[1]

        neighbor_report = construct_neighbor_hex(target_bssid, target_channel)

        payload = {
            "addr": client_mac,
            "disassociation_imminent": True,
            "disassociation_timer": 10,
            "neighbors": [neighbor_report],
        }

        cmd = [
            'ubus',
            'call',
            'hostapd.phy0-ap0',
            'bss_transition_request',
            json.dumps(payload),
        ]

        try:
            subprocess.run(cmd, check=True)
        except subprocess.CalledProcessError:
            pass
    else:
        # CCA-only path; driver handles backoff and contention.
        pass


if __name__ == "__main__":
    # for testing the code separately
    cca_tm_algo("96:49:2F:12:77:E2")
