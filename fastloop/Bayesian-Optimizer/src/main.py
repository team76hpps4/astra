import os
import time
import yaml
import optuna
import numpy as np
from datetime import datetime
from collections import deque, defaultdict
from .logger_config import offline_logger, online_logger, main_logger
from .helper import Params, get_current_window_index
from .bayes_optimizer import optuna_constraints, check_hysteresis
from .matlab_interface import start_engine, run_matlab_online
from .rollback_manager import rollback_if_unstable
from .AB_toggle_controller import load_ab_config
from .offline_sim import rrm_sim_python, simulate_postproc

# ==============================
# CONFIG LOAD
# ==============================
with open("configs/policy_guradrails.yaml", "r") as f:
    config = yaml.safe_load(f)

PER_CHANGE_LIMITS = {
    "tx_power_dbm": 0.15 * (config['TX_POWER_MAX_DBM'] - config['TX_POWER_MIN_DBM']),
    "obss_pd_dbm": 0.2 * (config['MAX_OBSS_PD_DBM'] - config['NOISE_FLOOR_DBM']),
    "channel_width_mhz": 20,
}

# ==============================
# MAIN LOOP
# ==============================
def main():
    sampler = optuna.samplers.GPSampler(constraints_func=optuna_constraints)
    eng = start_engine()

    # Initialize persistent variables
    recent_p50 = deque(maxlen=3)
    prev_params = None
    safe_cfg = defaultdict(lambda: None)

    last_window = None
    global_trial_counter = 0
    window_trial_counter = 0

    dashboard_dir = os.path.join(os.path.dirname(__file__), "..", "dashboard")
    os.makedirs(dashboard_dir, exist_ok=True)

    try:
        while True:
            current_window = get_current_window_index()

            # Handle window switch
            if last_window != current_window:
                main_logger.info(f"=== Switching to window {current_window} ===")

                # Reset per-window state
                prev_params = None
                recent_p50.clear()
                window_trial_counter = 0
                safe_cfg[current_window] = None

                # Create a separate database file for each window
                optuna_db_path = os.path.join(dashboard_dir, f"optuna_window_{current_window}.db")

                # Create load study for this specific window
                study_name = f"wifi_optimization_window_{current_window}"
                study = optuna.create_study(
                    study_name=study_name,
                    storage=f"sqlite:///{optuna_db_path}",
                    load_if_exists=True,
                    sampler=sampler,
                    direction="maximize",
                )

                last_window = current_window

            # increment counters
            global_trial_counter += 1
            window_trial_counter += 1

            # parameter bounds (adaptive per prev_params)
            tx_min, tx_max = config['TX_POWER_MIN_DBM'], config['TX_POWER_MAX_DBM']
            obsspd_min, obsspd_max = config['NOISE_FLOOR_DBM'], config['MAX_OBSS_PD_DBM']

            if prev_params is not None:
                tx_min = max(tx_min, prev_params.tx_power_dbm - PER_CHANGE_LIMITS['tx_power_dbm'])
                tx_max = min(tx_max, prev_params.tx_power_dbm + PER_CHANGE_LIMITS['tx_power_dbm'])
                obsspd_min = max(obsspd_min, prev_params.obss_pd_dbm - PER_CHANGE_LIMITS['obss_pd_dbm'])
                obsspd_max = min(obsspd_max, prev_params.obss_pd_dbm + PER_CHANGE_LIMITS['obss_pd_dbm'])

            trial = study.ask()
            tx = trial.suggest_float("tx_power_dbm", tx_min, tx_max)
            obss = trial.suggest_float("obss_pd_dbm", obsspd_min, obsspd_max)
            ch = trial.suggest_categorical("channel_width_mhz", config['CHANNEL_WIDTHS_MHZ'])
            params = Params(float(tx), float(obss), float(ch))

            # ====================================
            # OFFLINE PHASE
            # ====================================
            if window_trial_counter <= config['INITIAL_OFFLINE_TRIALS']:
                sim = rrm_sim_python(params.obss_pd_dbm, params.tx_power_dbm, params.channel_width_mhz)
                sim_metrics = simulate_postproc(sim, params, recent_p50)
                params.objective = sim_metrics["Throughput_p50"]

                trial.set_user_attr("retry_rate_p95", sim_metrics["Retry_p95"])
                trial.set_user_attr("eirp_violation", sim_metrics["EIRP_violation"])
                study.tell(trial, params.objective)

                offline_logger.info(
                    "%s | Window=%d | Trial=%d | tx_power_dbm=%.2f | obss_pd_dbm=%.2f | ch_width=%d | "
                    "Throughput_p50=%.3f | Retry_p95=%.3f | Client_flags=%.3f",
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    current_window,
                    window_trial_counter,
                    params.tx_power_dbm,
                    params.obss_pd_dbm,
                    params.channel_width_mhz,
                    sim_metrics.get("Throughput_p50", float('nan')),
                    sim_metrics.get("Retry_p95", float('nan')),
                    sim_metrics.get("Flag_ratio", 0.0),
                )
                time.sleep(config['OFFLINE_SLEEP_DELAY_SEC'])
                continue

            # ====================================
            # ONLINE PHASE
            # ====================================
            if not check_hysteresis(study, trial, params, prev_params):
                continue

            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            online_logger.info(
                "%s | Window=%d | Trial=%d | tx_power_dbm=%.2f | obss_pd_dbm=%.2f | ch_width=%d",
                timestamp,
                current_window,
                window_trial_counter,
                params.tx_power_dbm,
                params.obss_pd_dbm,
                params.channel_width_mhz,
            )

            p50, retry, flags = run_matlab_online(eng, params, config['MIN_ONLINE_OBSERVE_TIME_MINS'])
            eirp_violation = params.tx_power_dbm + config['ANTENNA_GAIN_DBM']

            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            online_logger.info(
                "%s | Window=%d | Trial=%d | Throughput_p50=%.3f | Retry_p95=%.3f | Client_flags=%.3f",
                timestamp,
                current_window,
                window_trial_counter,
                p50,
                retry,
                flags,
            )

            forced = rollback_if_unstable(retry, eirp_violation, safe_cfg, current_window)
            if forced:
                main_logger.warning('Unstable Configuration: Rolling back to safe config.')
                p50, retry, flags = run_matlab_online(eng, forced, config['MIN_ONLINE_OBSERVE_TIME_MINS'])
                params = forced

            recent_p50.append(p50)
            params.objective = float(np.mean(list(recent_p50)))

            trial.set_user_attr("retry_rate_p95", retry)
            trial.set_user_attr("eirp_violation", eirp_violation)
            study.tell(trial, params.objective)

            if flags > config['CLIENT_COOL_OFF_THRESHOLD']:
                main_logger.warning(
                    "Client flag rate high (%.3f) → applying complaint cooloff and switching to IEEE rule-based params",
                    flags * 100,
                )
                params = load_ab_config()
                time.sleep(config['COMPLAINT_COOL_OFF_MIN'] * 60)
                continue

            prev_params = params.copy()
            safe_cfg[current_window] = params.copy()
            time.sleep(60)

    except KeyboardInterrupt:
        main_logger.info("Stopped manually")
    finally:
        eng.quit()
        main_logger.info("MATLAB engine stopped")

if __name__ == "__main__":
    main()