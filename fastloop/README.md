# Fast Loop RRM Architecture

This repository contains the **Fast Loop** components of the **Client Centric WiFi RRM** (Radio Resource Management) system developed for the Arista Inter IIT Tech Meet 14.0 problem statement. 

The Fast Loop focuses on rapidly adapting to changing network conditions on the timescale of seconds to minutes. It utilizes continuous monitoring, dynamic resource allocation, and AI-assisted decision making to maximize client Quality of Experience (QoE) and mitigate network interference.

## Directory Structure & Sub-Projects

The `fastloop` directory is organized into three major sub-projects, each handling a specialized aspect of the RRM pipeline:

### 1. Sensing Orchestrator (`/sensing-orchestrator`)
A critical out-of-band sensing pipeline that utilizes a dedicated additional radio to continuously scan the spectrum without impacting client serving traffic.
- **Adaptive Dwell & Scheduling**: Employs Multi-Armed Bandit (MAB) logic to focus dwell time on heavily interfered channels.
- **Online Change Detection**: Uses CUSUM/EWMA algorithms to quickly flag environmental shifts.
- **Non-Wi-Fi Classifier**: Evaluates spectral data to classify non-Wi-Fi interference sources (e.g., BLE, Microwave).
- **Microservices**: Includes REST API for RRM consumption, ML inference container, and redis-backed logger.

### 2. Band Steering & Telemetry (`/bandsteering-telemetry`)
A suite of tools for on-AP passive inference, telemetry, and smart band-steering decisions for Linux-based routers (e.g., OpenWrt).
- **Passive Inference**: Captures passive network data (e.g., TCP RTT monitoring, ACK variances) to gauge Client QoE.
- **Interference Graph & Hidden Node handling**: Constructs an interference graph to adapt OBSS-PD dynamically and handle hidden nodes efficiently.
- **Active Telemetry**: Can send IEEE 802.11k/v requests (e.g., Link Measurements, BSS Transition Management) to compatible clients.
- **Band Steering Daemon**: Orchestrates smart roaming and band steering using a combination of RSSI, RTT, and bandwidth utilization heuristics.

### 3. Bayesian Optimizer (`/Bayesian-Optimizer`)
A hybrid Python/MATLAB optimization engine for tuning core AP parameters (Transmit Power, Channel Width, OBSS_PD) safely.
- **Constrained Bayesian Optimization**: Employs Optuna to iteratively find optimal settings, adjusting over distinct time windows (e.g., peak vs. quiet hours).
- **Safe Evaluation**: Relies on offline simulations before attempting to push modifications online via MATLAB Engine.
- **Guardrails**: Implement robust safety checks, such as automatic rollbacks for unstable configurations, hysteresis limits, and cool-off periods triggered by client complaints.

## Integration

These three components are designed to work cooperatively within the overarching RRM ecosystem:
- The **Sensing Orchestrator** detects environmental shifts and spectral interference at low latency.
- The **Band Steering & Telemetry** module provides the nuanced "client-view" and handles rapid local steering.
- The **Bayesian Optimizer** processes this telemetry globally (or over slightly longer windows) to dictate stable, optimal configuration sets while respecting service level objectives (SLOs) and change budgets.
