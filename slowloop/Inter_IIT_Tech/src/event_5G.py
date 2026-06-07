from dataclasses import dataclass, asdict
from typing import List, Dict, Any, Optional
import time
import uuid
import json
import copy
from datetime import datetime

# -----------------------------------------------------------
# GLOBAL THRESHOLDS (5G)
# -----------------------------------------------------------

GLOBAL_DEFAULTS = {
    "cu_trigger_threshold": 0.70,
    "max_width_changes_per_4h": 2, # 5G allows more flexibility
}

# -----------------------------------------------------------
# EVENT-SPECIFIC DEFAULTS (5G VERSION)
# -----------------------------------------------------------

EVENT_DEFAULTS = {
    "very_busy": {
        # High Demand: Maximize Throughput
        "tx_power_dbm": 25,          # Higher power for 5G
        "channel_width_mhz": 80,     # Standard high-throughput width
        "min_rssi_dbm": -72,
        "min_obss_pd_dbm": -72,      # Looser PD to allow more simultaneous Tx
        "min_cca_dbm": -78,
        "noise_floor_dbm": -95,
        "client_count_limit": 100,
        "retry_rate_threshold_pct": 15,
        "monitor_interval_s": 10,
        "blast_radius": 4,
        "busy_period_s": 10,
        "free_period_s": 9,
        "stage_delay_s": 4,
        "t_feedback_s": 20,
    },

    "moderate_busy": {
        # Balanced: Good speed, moderate interference mgmt
        "tx_power_dbm": 21,
        "channel_width_mhz": 40,     # Safer width for moderate density
        "min_rssi_dbm": -75,
        "min_obss_pd_dbm": -78,
        "min_cca_dbm": -80,
        "noise_floor_dbm": -95,
        "client_count_limit": 75,
        "retry_rate_threshold_pct": 10,
        "monitor_interval_s": 10,
        "blast_radius": 3,
        "busy_period_s": 8,
        "free_period_s": 7,
        "stage_delay_s": 3,
        "t_feedback_s": 15,
    },

    "low_busy": {
        # Low Demand: Maximize Efficiency / Range
        "tx_power_dbm": 18,
        "channel_width_mhz": 20,     # Narrow width for range/stability
        "min_rssi_dbm": -78,
        "min_obss_pd_dbm": -82,
        "min_cca_dbm": -82,
        "noise_floor_dbm": -95,
        "client_count_limit": 40,
        "retry_rate_threshold_pct": 5,
        "monitor_interval_s": 12,
        "blast_radius": 2,
        "busy_period_s": 6,
        "free_period_s": 5,
        "stage_delay_s": 2,
        "t_feedback_s": 10,
    }
}

# -----------------------------------------------------------
# MITIGATION STAGES
# -----------------------------------------------------------

EVENT_STAGES = {
    "very_busy": [
        {"name": "relax_admission",   "actions": ["relax_admission"],     "params": {"allow_extra_clients": True}},
        {"name": "force_80mhz",       "actions": ["set_bandwidth"],       "params": {"width": 80}},
        {"name": "increase_tx_power", "actions": ["tx_power_adjust"],     "params": {"delta_db": +3}},
    ],

    "moderate_busy": [
        {"name": "soft_steer",        "actions": ["steer_clients"],       "params": {"bias_5ghz": 0.5}},
        {"name": "stabilize_40mhz",   "actions": ["set_bandwidth"],       "params": {"width": 40}},
        {"name": "tweak_obss_pd",     "actions": ["tweak_obss_pd"],       "params": {"delta_db": +4}},
    ],

    "low_busy": [
        {"name": "save_power",        "actions": ["tx_power_adjust"],     "params": {"delta_db": -2}},
        {"name": "narrow_20mhz",      "actions": ["set_bandwidth"],       "params": {"width": 20}},
    ]
}

# -----------------------------------------------------------
# ACTION MAP (Helpers)
# -----------------------------------------------------------
# (Simplified for simulation control logic)

def should_trigger_event(human_trigger, cu):
    if human_trigger:
        return True
    return cu >= GLOBAL_DEFAULTS["cu_trigger_threshold"]

def build_event_plan(event_type, aps, overrides):
    defaults = copy.deepcopy(GLOBAL_DEFAULTS)
    defaults.update(copy.deepcopy(EVENT_DEFAULTS.get(event_type, EVENT_DEFAULTS["moderate_busy"])))

    if overrides:
        defaults.update(overrides)

    return {
        "event_type": event_type,
        "scope_aps": aps,
        "defaults": defaults,
        "stages": copy.deepcopy(EVENT_STAGES.get(event_type, []))
    }

# Main Runner Logic (Similar to 2.4G)
def run_event_loop_trigger(event_type, scope_aps, human_trigger=True, channel_utilization=0, overrides=None, metrics_callback=None):
    if not should_trigger_event(human_trigger, channel_utilization):
        return {"status": "not_triggered"}

    plan = build_event_plan(event_type, scope_aps, overrides)
    
    # In a simulation step context, we just return the plan/defaults 
    # The Main Controller applies these defaults to the next N simulation steps.
    return {
        "status": "event_active",
        "plan": plan
    }