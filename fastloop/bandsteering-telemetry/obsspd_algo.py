import json
import math
from cca_tm_algo import cca_tm_algo

MATRIX_FILE = "/tmp/interference_graph.json"

TX_POWER_DEFAULT_DBM = 20.0
OBSS_PD_MIN = -82.0   # IEEE 802.11ax min threshold
REF_TX_PWR = 21.0     # reference TX power used in SR formula
RX_SENSITIVITY = -75.0  # assumed minimum client RSSI for usable link


def calculate_max_sr_tx_power(alien_rssi):
    """
    Compute the maximum allowed TX power per SR OBSS_PD rule for a given alien AP RSSI.
    Returns a value clamped to hardware limits.
    """
    allowed_tx = REF_TX_PWR + OBSS_PD_MIN - alien_rssi

    if allowed_tx > 31.0:
        return 31.0
    if allowed_tx < 0.0:
        return 0.0
    return allowed_tx


def obsspd_algo(slow_loop_threshold):
    """
    Main OBSS_PD decision routine.
    Uses interference matrix to detect co-channel alien APs, checks slow-loop
    constraints, computes safe SR TX power, and validates client reachability.
    Falls back to CCA tuning if constraints are not met.
    """
    try:
        with open(MATRIX_FILE, 'r') as f:
            data = json.load(f)
    except Exception as e:
        print(f"[OBSSPD] Error reading matrix: {e}")
        return

    matrix = data['matrix']
    cols_aps = data['columns_aps']
    rows_clients = data['rows_clients']

    # self AP row (row 0)
    self_row = matrix[0]
    self_entry_col0 = self_row[0]

    best_interferer_pl = float('inf')
    best_interferer_idx = -1
    best_interferer_channel = -1

    # derive self AP channel
    try:
        self_channel = matrix[1][0][1]
    except Exception:
        print("[OBSSPD] Could not determine Self Channel.")
        return

    # pick best (strongest) co-channel interferer as seen by self AP
    for col_idx, entry in enumerate(self_row):
        if col_idx == 0:
            continue
        if entry is None:
            continue

        pl, ch, flag = entry
        if ch == self_channel and pl < best_interferer_pl:
            best_interferer_pl = pl
            best_interferer_idx = col_idx
            best_interferer_channel = ch

    if best_interferer_idx == -1:
        # no co-channel interferer found
        return

    interferer_entry = self_row[best_interferer_idx]
    pathloss, channel, is_same_network = interferer_entry

    interferer_rssi = TX_POWER_DEFAULT_DBM - pathloss

    # slow-loop guard: if interferer is too strong, avoid SR path and run CCA
    if interferer_rssi > slow_loop_threshold:
        run_fallback_cca(rows_clients)
        return

    # only apply OBSS_PD logic for alien APs
    if is_same_network == 1:
        run_fallback_cca(rows_clients)
        return

    max_allowed_tx_power = calculate_max_sr_tx_power(interferer_rssi)

    # verify that all clients remain reachable at computed TX level
    all_clients_reachable = True

    for row_idx in range(1, len(rows_clients)):
        client_mac = rows_clients[row_idx]
        client_row = matrix[row_idx]

        self_link_entry = client_row[0]
        if self_link_entry is None:
            continue

        pl_to_client = self_link_entry[0]
        estimated_client_rssi = max_allowed_tx_power - pl_to_client

        if estimated_client_rssi < RX_SENSITIVITY:
            all_clients_reachable = False
            break

    if not all_clients_reachable:
        # SR power cut would break some clients, fall back to CCA tuning
        run_fallback_cca(rows_clients)
    else:
        # Placeholder: further packet timing / OBSS_PD tuning would happen here
        print("packet timing logic has been called")


def run_fallback_cca(rows_clients):
    """
    Apply CCA tuning for all active clients as a fallback mitigation path.
    """
    for i in range(1, len(rows_clients)):
        client_mac = rows_clients[i]
        cca_tm_algo(client_mac)


if __name__ == "__main__":
    # simple test entrypoint
    obsspd_algo(slow_loop_threshold=-70.0)
