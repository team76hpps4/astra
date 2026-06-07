# Arista Inter-IIT Tech Meet 14.0: Client Centric WiFi RRM

Welcome to the repository for the **Client Centric WiFi Radio Resource Management (RRM)** system, developed for the Arista Inter-IIT Tech Meet 14.0 problem statement. 

This project tackles the challenge of optimizing enterprise Wi-Fi networks in dense, high-variance environments. By moving away from traditional static, AP-centric RRM policies, our solution implements a closed-loop, AI-assisted, and client-aware architecture. It continuously monitors the environment, adapts to interference, and steers clients intelligently to guarantee a superior Quality of Experience (QoE).

## System Architecture

The overall system is divided into two distinct timescales: the **Fast Loop** (reacting in seconds/minutes) and the **Slow Loop** (reacting over hours/days).

### 1. Fast Loop (`/fastloop`)
The Fast Loop focuses on rapid, reactive control against transient issues, immediate interference bursts, and short-term mobility events.
- **Sensing Orchestrator (`/fastloop/sensing-orchestrator`)**: Utilizes a dedicated additional radio for continuous spectrum sensing. Uses a Multi-Armed Bandit (MAB) for adaptive dwell scheduling, lightweight CNNs for non-Wi-Fi classification (e.g., BLE, microwave), and CUSUM algorithms for online change detection.
- **Band Steering & Telemetry (`/fastloop/bandsteering-telemetry`)**: Performs on-AP passive inference, maintains local interference graphs, manages hidden nodes, and executes client-aware band steering via TCP RTT tracking and IEEE 802.11k/v requests.
- **Bayesian Optimizer (`/fastloop/Bayesian-Optimizer`)**: A hybrid Python/MATLAB optimization engine for tuning core AP parameters (Transmit Power, Channel Width, OBSS_PD) over specific time windows, with strict guardrails and automated rollbacks.

### 2. Slow Loop (`/slowloop`)
The Slow Loop provides global planning, learning long-term topology patterns, and executing robust reinforcement learning policies across the network.
- **GRACE (Graph Neural Network)**: Encodes the spatial and spectral dependencies (interference graph) between APs and clients into high-dimensional embeddings to inform topology-aware decisions.
- **Soft Actor-Critic (SAC) RL Agent**: Predicts and applies network-wide configuration adjustments based on GNN embeddings. Operates within defined constraints and employs submodular greedy selection for safe blast-radius control.
- **Event Handler**: Handles operator overrides and applies predefined baseline profiles during "Low", "Moderate", and "High" busy periods when the ML system requires manual intervention or stabilization.
- **Guardrails**: Enforces long-term configuration change budgets, applying hysteresis to eliminate noisy micro-optimizations and ensuring safe rollback if KPIs degrade.

## Getting Started

To explore the specific components, navigate to their respective directories. Detailed deployment and execution instructions are available inside each module.

- **Fast Loop Overview**: See [`fastloop/README.md`](fastloop/README.md)
- **Slow Loop Overview**: See [`slowloop/README.md`](slowloop/README.md)

### General Prerequisites
- **Python 3.8+**
- **Docker & Docker Compose** (for deploying the sensing orchestrator microservices)
- **MATLAB R2021b+** with the MATLAB Engine API for Python installed (for running Bayesian Optimizer and specific simulated environments)

### Key Deliverables Achieved
- Continuous, zero-impact environmental visibility via the dedicated radio.
- Client-view telemetry blended seamlessly with AP-side metrics.
- Multi-timescale control combining reactive fast-loop corrections and proactive slow-loop global planning.
- Safety-first AI tuning with strict guardrails, budget limits, and rollback mechanisms.
