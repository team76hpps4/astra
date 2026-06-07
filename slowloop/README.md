# Inter-IIT Tech: Intelligent Radio Resource Management System

This repository contains the full implementation of an intelligent Wi-Fi RRM system developed for the Inter-IIT Tech Meet. The system integrates Reinforcement Learning (Soft Actor Critic), a Graph Neural Network (Graph Contrastive Representation) for topology-aware state encoding, a real-time event-driven controller, and a collection of guardrails designed to ensure safe network behavior. The design, behavior, and purpose of each module are informed directly by the detailed architecture described in the submission report.

---

# Project Overview

Traditional Wi-Fi controllers configure AP parameters statically and struggle under dynamic interference, mobility, and uneven client load. This system replaces static logic with a closed-loop controller that senses the environment, interprets the network graph through a GNN, takes actions with an RL agent, validates those actions through guardrails, and finally applies changes to the APs. Everything is modular so components can be trained, extended, or replaced independently.

---

# Core System Components

## GRACE — Graph Neural Network State Encoder

The GNN processes the raw feature vector produced by the Environment Data Sampler, which includes AP configuration, interference metrics, telemetry aggregates, and the RSSI coupling matrix. Its role is to capture the spatial and spectral dependencies between APs, encoding the interference graph into high-dimensional state embeddings. This allows the controller to understand how a configuration change at one AP affects neighboring APs and the wider BSS.

## Soft Actor-Critic (SAC) Reinforcement Learning Agent

The RL Agent operates on top of the GNN embeddings and predicts configuration adjustments for each AP. It follows domain constraints including valid transmit power ranges, allowed channels (DFS and non-DFS), and standard bandwidths. To prevent destabilizing changes, the agent uses a blast-radius control mechanism, modifying only a small subset of APs at a time through a submodular greedy selection process. Along with each proposed configuration change, the agent outputs a predicted gain, representing a confidence estimate of expected improvement.

## Event Handler

The project also supports operator overrides. During abnormal conditions, the operator may disable RL and apply predefined default configuration profiles for low, moderate, or high busy periods. After the override period ends, RL-driven control resumes normally.

These predefined profiles correspond to three operational periods defined in the system design:

- **Low Busy Period** — applied when the network experiences minimal demand, ensuring energy-efficient and interference-aware operation with conservative configurations.
- **Moderate Busy Period** — activated under typical load conditions, balancing throughput, stability, and fairness while maintaining sufficient headroom for transient spikes.
- **High Busy Period** — used during peak demand, where parameters are tuned for maximum capacity and robustness, prioritizing congestion mitigation and interference resilience.

Once the Event Handler is triggered, the system opens a GUI which gives operator full access to all the parameters to be tuned. Every configuration has some default values associated with it, which is called when the network operator doesn’t change any AP’s configuration.

## Guardrails — Stability Enforcement Layer

A sequence of guardrails validates or modifies the RL agent’s proposed actions. A hysteresis check removes micro-optimizations that do not meaningfully impact performance. A gain-weighted token-bucket mechanism enforces long-term configuration-change budgets while still allowing rapid corrective actions during high-severity events. A rollback watchdog places updates under probation and automatically reverts any change that causes KPI degradation.

## MATLAB-Inspired Environment Modeling

The environment used for simulation was originally informed by MATLAB-based models provided with the problem statement. These models shaped the assumptions used for link budget estimation, interference propagation, and spatial fading behavior. Although the final system runs entirely in Python, the conceptual design of scenarios, metric definitions, and fidelity constraints closely follow the MATLAB foundations described in the report.

---

# Repository Structure (Concise Overview)

This section briefly describes the repository layout without deep technical detail.

**GRACE/** — Contains the graph neural network model and utilities used to encode AP–client relationships.

**Guardrails/** — Implements stability mechanisms such as hysteresis, budgets, and reset logic used to filter unsafe RL actions.

**Inter_IIT_Tech/** — Houses the event loop, RL training scripts, executors, and simulation logic that run the full controller.

**logs/** — Stores training logs, event-loop traces, and experiment outputs.

**rl_weights/** — Holds final trained SAC policies and exported versions.

**rrm_training_logs/** — Contains band-specific and experiment-specific RL training logs.

**sac_rrm_checkpoints_2G/** and **sac_rrm_checkpoints_5G/** — Store intermediate model checkpoints for reproducibility.

---

# System Pipeline

The end-to-end workflow consists of environment state collection, GNN-based encoding of the AP–client graph, SAC-driven decision making, safety filtering through guardrails, and application of AP configuration changes. This mirrors the architecture diagram and stepwise controller description in the submission report.

---

# Key Contributions

The project involved implementing the full event-driven controller, integrating the SAC agent with the GNN encoder, building a structured simulation environment for multiple frequency bands, designing and implementing guardrail logic, exporting trained models, and performing detailed evaluations on throughput, interference, and network stability. These contributions reflect the major components discussed in the report.

---

# How to Run

To run the system, first move into the project root directory:

```
cd client_centric_rrm
```

Install the MATLAB Engine API for Python:
This step is crucial and is *not* handled by pip. You must install it from your local MATLAB installation.
- Find your MATLAB installation's python engine directory. Example paths:
     - **Windows**: `C:\Program Files\MATLAB\R2024a\extern\engines\python`
     - **macOS**: `/Applications/MATLAB_R2024a.app/extern/engines/python`
     - **Linux**: `/usr/local/MATLAB/R2024a/extern/engines/python`

#Navigate to that directory in your terminal and install (while your virtual environment is active):

     ```sh
     cd "C:\Program Files\MATLAB\R2024a\extern\engines\python"
     python setup.py install
     ```
After entering the directory, execute the full simulation pipeline using:

```
python -m Inter_IIT_Tech.src.deploy
```


This command launches the complete controller workflow: environment initialization, state extraction, GNN inference, SAC policy execution, and guardrail-validated AP configuration updates.

To train the SAC agent from scratch, execute:

```
python -m Inter_IIT_Tech.train_sac.py
```


or, for dual-band training:

```
python Inter_IIT_Tech.train_dual_sac.py
```


These scripts build the GNN encoder, initialize SAC networks, attach replay buffers, and begin iterative training using the designated simulation environments.

All execution logs and controller traces will appear in the `logs/` directory for inspection, debugging, and analysis.

---

# Final Summary

This repository delivers the implementation of an intelligent RRM controller. Each folder corresponds to a specific subsystem described in the submission: GRACE provides topology-aware state encoding, the SAC agent learns control behavior, guardrails enforce safety, the event loop orchestrates real-time decisions, and the logs and checkpoints enable analysis and reproducibility. The structure is designed for clarity, experimentation, and further extension.

