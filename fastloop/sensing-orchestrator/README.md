# Sensing Orchestrator (Fast Loop)

The **Sensing Orchestrator** is a critical component of the **Client Centric WiFi RRM** (Radio Resource Management) system. Designed to run as part of the "Fast Loop" (seconds to minutes timescale), it leverages an additional dedicated radio to perform continuous, low-latency spectrum sensing and inference.

This repository fulfills the **Mid-Term** objective of the Arista Inter IIT Tech Meet 14.0 problem statement by providing an AI-assisted, client-aware sensing pipeline.

## Overview

The Sensing Orchestrator dynamically schedules scans, processes spectrum intelligence, identifies non-Wi-Fi interference, and exposes these findings via a downstream API to the RRM logic, all while ensuring zero-impact to client serving.

## Microservices Architecture

The system is deployed using `docker-compose` and is composed of several specialized microservices:

### 1. Bandit (`/bandit`)
This service is responsible for **Adaptive Dwell & Scheduling** and **Change Detection**.
- **Multi-Armed Bandit (MAB)**: Implements dynamic per-channel dwell times. It focuses scanning time on likely-noisy channels while respecting DFS pre-scan requirements and SLA bounds.
- **CUSUM/EWMA Change Detection**: Runs online change detection (CUSUM) on metrics like airtime, CCA busy, and Noise Floor to flag meaningful shifts in seconds.
- **SDR Integration**: Interfaces with USRP (Software Defined Radio) to fetch real-world radio data.

### 2. ML Classifier (`/ml`)
This service acts as the **Non-Wi-Fi Classifier**.
- Evaluates captured spectral data using lightweight CNN/feature engines to classify interferers (e.g., BLE, Zigbee, microwave).
- Computes metrics such as confidence, duty cycle, center frequency, and bandwidth.

### 3. API (`/api`)
Provides the **Downstream RRM API**.
- Exposes sensing events and telemetry to downstream RRM planners and controllers.
- Exposes the `/sensing` endpoints as required by the RRM reference architecture.

### 4. Logger (`/logger`)
Handles data persistence and event streaming.
- Captures logs and events.
- Interacts with a Redis instance used as a fast message broker/state store between the services.

### 5. Dashboard (`/dashboard`)
Visualizes metrics, classifier precision/recall, and the state of the spectrum for evaluation purposes.

## Key Features

* **Adaptive Dwell**: MAB implementation (`mab.py`) ensures intelligent allocation of dwell time to heavily interfered channels.
* **Online Change Detection**: Uses CUSUM (`cusum.py`) to react rapidly to environmental changes.
* **Zero-Impact Serving**: Designed as an out-of-band pipeline utilizing the additional dedicated radio.
* **Dockerized Setup**: Seamless scaling and deployment using `docker-compose`.

## Running the Application

Ensure you have Docker and Docker Compose installed.

```bash
docker-compose up --build
```

### Microservice Endpoints (Default Ports)
- **API**: `http://localhost:8000`
- **ML Service**: `http://localhost:8080`
- **Logger**: `http://localhost:8090`
- **Redis Cache**: `localhost:6379`
