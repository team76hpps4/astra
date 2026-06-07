# Adaptive Wi-Fi RRM with Constrained Bayesian Optimization

This project is a hybrid Python/MATLAB framework for the dynamic optimization of Wi-Fi network parameters. It uses Bayesian optimization (via Optuna) to intelligently tune settings like Transmit Power, OBSS_PD, and Channel Width, adapting to changing network conditions to maximize throughput.

The system is designed for continuous operation, breaking optimization into distinct time windows (e.g., day vs. night) and running separate studies for each. It features a "warm-up" offline simulation phase before transitioning to live, online optimization on a real network via MATLAB.

---

## Key Features

- **Hybrid Optimization**: Leverages Python for high-level optimization logic (Optuna) and MATLAB for domain-specific online testing and simulation.
- **Bayesian Optimization**: Employs `optuna.samplers.GPSampler` to efficiently explore the parameter space and find optimal configurations with minimal trials.
- **Time-Windowed Studies**: Automatically creates separate optimization studies for different times of day (e.g., `optuna_window_0.db`, `optuna_window_1.db`). This allows the system to learn and apply the best policies for different traffic patterns (e.g., busy office hours vs. quiet nighttime).
- **Offline Warm-up**: Runs `INITIAL_OFFLINE_TRIALS` using an internal Python simulation (`rrm_sim_python`) to build an initial performance model before applying any changes to the live network.
- **Online Adaptation**: After the warm-up, the system applies suggested parameters to the live network using MATLAB (`run_matlab_online`), measures real-world P50 throughput, and feeds the results back to the optimizer.

---

### Robust Safety Guardrails

- **Rollback**: Automatically reverts to a last-known-good configuration (`safe_cfg`) if a new trial results in unstable network performance.
- **Hysteresis**: Prevents the optimizer from making rapid, oscillating changes to network parameters.
- **Client Complaint Handling**: Monitors a "client flag" metric and enters a cool-off period if it exceeds a threshold, temporarily reverting to a default IEEE-rules-based configuration.

---

### Live Visualization

All optimization data is stored in sqlite databases, which can be visualized in real-time using [Optuna Dashboard](https://github.com/optuna/optuna-dashboard).

---

## How It Works: The Optimization Loop

The `main()` function operates in a continuous loop, broken into these key phases:

1. **Initialization**: The script loads configuration from `policy_guradrails.yaml` and starts the MATLAB engine.
2. **Window Check**: Determines the current time window (e.g., window 0 for 00:00-03:00, 1 for 03:00-6:00, etc.).
3. **Study Management**: If it's a new window, resets the trial state and loads/creates the specific Optuna study for that window (e.g., `dashboard/optuna_window_1.db`).
4. **Offline Phase (Warm-up)**: For the first N trials (`INITIAL_OFFLINE_TRIALS`) in a window:
    - `Optuna study.ask()`s for a new set of parameters.
    - These parameters are tested against the Python simulation (`rrm_sim_python`).
    - The simulated results are reported back via `study.tell()`.
5. **Online Phase (Live Tuning)**: After the warm-up trials:
    - `Optuna study.ask()`s for new parameters.
    - Safety checks (like hysteresis) are performed.
    - The parameters are applied to the live network via `run_matlab_online(eng, ...)`.
    - Real metrics (P50 Throughput, Retry Rate) are returned.
6. **Stability Check**: `rollback_if_unstable` checks the metrics. If they are poor, the system discards the trial and reverts to the last `safe_cfg`.
7. **Objective Reporting**: The objective (a running mean of P50 throughput) is reported via `study.tell()`.
8. **Client Flag Check**: If client complaints are high, the system enters a cool-off period.
9. **Configuration Update**: The new, successful configuration is stored as the next `safe_cfg`.
10. **Sleep & Repeat**: The system sleeps for a configured duration (`ONLINE_OBSERVE_TIME`) before starting the next trial.

---

## Project Structure

```
.
│   README.md
│   
├───Comparison
│       Channel Width.jpeg
│       Flagged Client.jpeg
│       OBSS.jpeg
│       Throughput.jpeg
│       Tx_Power.jpeg
│       
├───configs
│       ab_test_config.json
│       policy_guradrails.yaml
│
├───dashboard
│   │   optuna_study.db
│   │   optuna_window_0.db
│   │   optuna_window_1.db
│   │   optuna_window_2.db
│   │   optuna_window_3.db
│   │   optuna_window_4.db
│   │   optuna_window_5.db
│   │   optuna_window_6.db
│   │   optuna_window_7.db
│   │   run_visualization.py
│   │   __init__.py
│   │
│   ├───window_0
│   │       contour_plot_window0.png
│   │       optimization_history_window0.png
│   │       parallel_coordinates_window0.png
│   │       param_importances_window0.png
│   │       slice_plot_window0.png
│   │
│   ├───window_1
│   │       contour_plot_window1.png
│   │       optimization_history_window1.png
│   │       parallel_coordinates_window1.png
│   │       param_importances_window1.png
│   │       slice_plot_window1.png
│   │
│   ├───window_2
│   │       contour_plot_window2.png
│   │       optimization_history_window2.png
│   │       parallel_coordinates_window2.png
│   │       param_importances_window2.png
│   │       slice_plot_window2.png
│   │
│   ├───window_3
│   │       contour_plot_window3.png
│   │       optimization_history_window3.png
│   │       parallel_coordinates_window3.png
│   │       param_importances_window3.png
│   │       slice_plot_window3.png
│   │
│   ├───window_4
│   │       contour_plot_window4.png
│   │       optimization_history_window4.png
│   │       parallel_coordinates_window4.png
│   │       param_importances_window4.png
│   │       slice_plot_window4.png
│   │
│   ├───window_5
│   │       contour_plot_window5.png
│   │       optimization_history_window5.png
│   │       parallel_coordinates_window5.png
│   │       param_importances_window5.png
│   │       slice_plot_window5.png
│   │
│   ├───window_6
│   │       contour_plot_window6.png
│   │       optimization_history_window6.png
│   │       parallel_coordinates_window6.png
│   │       param_importances_window6.png
│   │       slice_plot_window6.png
│   │
│   ├───window_7
│   │       contour_plot_window7.png
│   │       optimization_history_window7.png
│   │       parallel_coordinates_window7.png
│   │       param_importances_window7.png
│   │       slice_plot_window7.png
│   │
│   └───__pycache__
│           run_visualization.cpython-314.pyc
│           __init__.cpython-314.pyc
│
├───logs
│       offlline_simulations.log
│       online_logger.log
│       wifi_main.log
│
├───Requirements
│       Requirements.txt
│
└───src
    │   AB_toggle_controller.py
    │   bayes_optimizer.py
    │   helper.py
    │   logger_config.py
    │   dfs_manager.py
    │   main.py
    │   matlab_interface.py
    │   offline_sim.py
    │   rollback_manager.py
    │   rrm_sim.m
    │   test.py
    │   __init__.py
    │
    └───__pycache__
            AB_toggle_controller.cpython-314.pyc
            bayes_optimizer.cpython-314.pyc
            helper.cpython-314.pyc
            logger_config.cpython-314.pyc
            main.cpython-314.pyc
            matlab_interface.cpython-314.pyc
            offline_sim.cpython-314.pyc
            rollback_manager.cpython-314.pyc
            test.cpython-314.pyc
            __init__.cpython-314.pyc
```

---

## Getting Started

### Prerequisites

- **Python 3.8+**
- **A licensed installation of MATLAB** (R2021b or newer recommended).
    - Your custom MATLAB functions (like `run_matlab_online`) must be available on the MATLAB search path.

---

### Installation

1. **Clone the Repository:**
   ```sh
   git clone https://github.com/team76hpps4/BO.git
   cd BO
   ```

2. **Create and Activate a Python Virtual Environment:**
   ```sh
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```

3. **Install Python Dependencies:**

   ```sh
   pip install -r requirements.txt
   ```

4. **Install the MATLAB Engine API for Python:**

   This step is crucial and is *not* handled by pip. You must install it from your local MATLAB installation.

   - Find your MATLAB installation's python engine directory. Example paths:
     - **Windows**: `C:\Program Files\MATLAB\R2024a\extern\engines\python`
     - **macOS**: `/Applications/MATLAB_R2024a.app/extern/engines/python`
     - **Linux**: `/usr/local/MATLAB/R2024a/extern/engines/python`
   - Navigate to that directory in your terminal and install (while your virtual environment is active):

     ```sh
     cd "C:\Program Files\MATLAB\R2024a\extern\engines\python"
     python setup.py install
     ```

---

### Configuration

All system parameters are defined in `configs/policy_guradrails.yaml`. Key parameters to review include:

- `TX_POWER_MIN_DBM`, `TX_POWER_MAX_DBM`: Guardrails for transmit power.
- `NOISE_FLOOR_DBM`, `MAX_OBSS_PD_DBM`: Guardrails for OBSS_PD.
- `CHANNEL_WIDTHS_MHZ`: List of allowed channel widths (e.g., `[20, 40, 80]`).
- `INITIAL_OFFLINE_TRIALS`: Number of simulation trials to run before going online.
- `MIN_ONLINE_OBSERVE_TIME_MINS`: Duration to wait after applying a new online configuration.
- `CLIENT_COOL_OFF_THRESHOLD`: Fraction of "client flags" that triggers a cool-off.
- `COMPLAINT_COOL_OFF_MIN`: Number of minutes to wait during a cool-off period.

---

### How to Run

1. Ensure all settings in `configs/policy_guradrails.yaml` are correct.
2. Ensure your MATLAB license is active and your custom .m files are on its path.
3. Run the main script:
   ```sh
   python -m src.main
   ```

The script will start logging to its log files. You will see it move from the "OFFLINE PHASE" to the "ONLINE PHASE" after `INITIAL_OFFLINE_TRIALS`.

---

## Visualizing the Results

This project is built to be monitored. When the script has completed, you can launch the Optuna dashboard to see the optimization results.

1. **Install the dashboard:**
   ```sh
   pip install optuna-dashboard
   ```

2. **Run the dashboard:**
    - Point it at the database file for the window you want to observe:
      ```sh
      python -m dashboard.run_visualization.py --study-name wifi_optimization_window_0 --show
      ```
    - Or for a different window:
      ```sh
      python -m dashboard.run_visualization.py --study-name wifi_optimization_window_7 --show
      ```

This will open a web interface in your browser showing the objective value (Throughput_p50) over time, parameter importance, and the relationship between different parameters.

---
