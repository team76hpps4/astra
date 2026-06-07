from dataclasses import dataclass, asdict
from typing import List, Dict, Any, Optional
import time
import uuid
import json
import copy
from datetime import datetime

# -----------------------------------------------------------
# GLOBAL THRESHOLDS
# -----------------------------------------------------------

GLOBAL_DEFAULTS = {
    "cu_trigger_threshold": 0.70,
    "max_width_changes_per_4h": 1,
}

# -----------------------------------------------------------
# EVENT-SPECIFIC DEFAULTS (FULLY SEPARATE)
# -----------------------------------------------------------

EVENT_DEFAULTS = {
    "very_busy": {
        "tx_power_dbm": 23,
        "channel_width_mhz": 80,
        "min_rssi_dbm": -70,
        "min_obss_pd_dbm": -78,
        "min_cca_dbm": -82,
        "noise_floor_dbm": -95,
        "client_count_limit": 80,
        "retry_rate_threshold_pct": 15,
        "monitor_interval_s": 10,
        "blast_radius": 4,
        "busy_period_s": 10,
        "free_period_s": 9,
        "stage_delay_s": 4,
        "t_feedback_s": 20,
    },

    "moderate_busy": {
        "tx_power_dbm": 20,
        "channel_width_mhz": 40,
        "min_rssi_dbm": -72,
        "min_obss_pd_dbm": -82,
        "min_cca_dbm": -82,
        "noise_floor_dbm": -96,
        "client_count_limit": 64,
        "retry_rate_threshold_pct": 12,
        "monitor_interval_s": 10,
        "blast_radius": 3,
        "busy_period_s": 8,
        "free_period_s": 7,
        "stage_delay_s": 3,
        "t_feedback_s": 15,
    },

    "low_busy": {
        "tx_power_dbm": 18,
        "channel_width_mhz": 20,
        "min_rssi_dbm": -75,
        "min_obss_pd_dbm": -85,
        "min_cca_dbm": -85,
        "noise_floor_dbm": -97,
        "client_count_limit": 32,
        "retry_rate_threshold_pct": 8,
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
        {"name": "aggressive_steer",  "actions": ["steer_clients"],       "params": {"bias_5ghz": 0.8}},
        {"name": "increase_tx_power", "actions": ["tx_power_adjust"],     "params": {"delta_db": +2}},
        {"name": "load_balance",      "actions": ["load_balance"],        "params": {}},
    ],

    "moderate_busy": [
        {"name": "soft_steer",        "actions": ["steer_clients"],       "params": {"bias_5ghz": 0.5}},
        {"name": "narrow_24",         "actions": ["narrow_2_4"],          "params": {}},
        {"name": "tweak_obss_pd",     "actions": ["tweak_obss_pd"],       "params": {"delta_db": +3}},
    ],

    "low_busy": [
        {"name": "bias_probe",        "actions": ["bias_probe_responses"], "params": {"bias_5ghz": 0.4}},
        {"name": "gentle_steer",      "actions": ["steer_clients"],        "params": {"bias_5ghz": 0.3}},
    ]
}

# -----------------------------------------------------------
# ACTION MAP
# -----------------------------------------------------------

def action_steer_clients(ap, params):         return {"ap": ap, "action": "steer_clients", "params": params}
def action_narrow_2_4(ap, params):            return {"ap": ap, "action": "narrow_2_4", "params": params}
def action_tx_power_adjust(ap, params):       return {"ap": ap, "action": "tx_power_adjust", "params": params}
def action_tweak_obss_pd(ap, params):         return {"ap": ap, "action": "tweak_obss_pd", "params": params}
def action_relax_admission(ap, params):       return {"ap": ap, "action": "relax_admission", "params": params}
def action_load_balance(ap, params):          return {"ap": ap, "action": "load_balance", "params": params}
def action_bias_probe_responses(ap, params):  return {"ap": ap, "action": "bias_probe_responses", "params": params}

ACTION_FACTORY = {
    "steer_clients": action_steer_clients,
    "narrow_2_4": action_narrow_2_4,
    "tx_power_adjust": action_tx_power_adjust,
    "tweak_obss_pd": action_tweak_obss_pd,
    "relax_admission": action_relax_admission,
    "load_balance": action_load_balance,
    "bias_probe_responses": action_bias_probe_responses,
}

# -----------------------------------------------------------
# CONTROL SIGNAL STRUCT
# -----------------------------------------------------------

def new_control_signal(event_active=0, busy_active=0, free_active=0, event_done=0, unfreeze=0):
    return {
        "event_active": event_active,
        "busy_period_active": busy_active,
        "free_period_active": free_active,
        "event_done": event_done,
        "unfreeze_slow_loop": unfreeze
    }

# -----------------------------------------------------------
# MAIN HELPERS
# -----------------------------------------------------------

def should_trigger_event(human_trigger, cu):
    if human_trigger:
        return True
    return cu >= GLOBAL_DEFAULTS["cu_trigger_threshold"]

def build_event_plan(event_type, aps, overrides):
    defaults = copy.deepcopy(GLOBAL_DEFAULTS)
    defaults.update(copy.deepcopy(EVENT_DEFAULTS[event_type]))

    if overrides:
        defaults.update(overrides)

    return {
        "event_type": event_type,
        "scope_aps": aps,
        "defaults": defaults,
        "stages": copy.deepcopy(EVENT_STAGES[event_type])
    }

def generate_batches(plan):
    aps = plan["scope_aps"]
    br = plan["defaults"]["blast_radius"]
    batches = []

    for stage in plan["stages"]:
        for i in range(0, len(aps), br):
            chunk = aps[i:i+br]
            actions=[]
            for ap in chunk:
                for a in stage["actions"]:
                    fn = ACTION_FACTORY[a]
                    actions.append(fn(ap, stage.get("params",{})))
            batches.append({
                "stage": stage["name"],
                "aps": chunk,
                "actions": actions,
                "stage_delay_s": plan["defaults"]["stage_delay_s"],
                "t_feedback_s": plan["defaults"]["t_feedback_s"]
            })
    return batches

# -----------------------------------------------------------
# MAIN EVENT LOOP FUNCTION (FULLY SEQUENTIAL, BLOCKING)
# -----------------------------------------------------------

def run_event_loop_trigger(event_type,
                           scope_aps,
                           human_trigger=True,
                           channel_utilization=0,
                           overrides=None,
                           metrics_callback=None):
    """
    metrics_callback(aps) should return metrics dict:
        { ap -> {"throughput":..., "p95_retry":..., ...} }
    """

    # ---- TRIGGER CHECK ----
    if not should_trigger_event(human_trigger, channel_utilization):
        return {
            "status": "not_triggered",
            "control_signal": new_control_signal(),
            "message": "Trigger conditions not satisfied"
        }

    # ---- BUILD PLAN ----
    plan = build_event_plan(event_type, scope_aps, overrides)
    batches = generate_batches(plan)

    control_signal = new_control_signal(event_active=1)

    # Return batches for Simulink to run
    report = {
        "status": "event_started",
        "event_type": event_type,
        "plan": plan,
        "batches": batches,
        "control_signal": control_signal,
        "message": "Event loop started"
    }

    # ---- STAGE EXECUTION (Simulink performs actions, not Python) ----
    for batch in batches:
        # Simulink executes actions here
        time.sleep(batch["stage_delay_s"])

        # Check metrics if provided
        if metrics_callback:
            metrics = metrics_callback(batch["aps"])
            # For now: Simulink decides rollback — Python doesn't enforce
            # You can add rollback logic here if needed.

    # ---- BUSY PERIOD ----
    busy_duration = plan["defaults"]["busy_period_s"]
    start = time.time()

    while time.time() - start < busy_duration:
        control_signal = new_control_signal(event_active=1, busy_active=1)
        if metrics_callback:
            metrics_callback(scope_aps)  # Simulink evaluates KPI
        time.sleep(plan["defaults"]["monitor_interval_s"])

    # ---- FREE PERIOD ----
    free_duration = plan["defaults"]["free_period_s"]
    start = time.time()

    while time.time() - start < free_duration:
        control_signal = new_control_signal(event_active=1, free_active=1)
        time.sleep(plan["defaults"]["monitor_interval_s"])

    # ---- EVENT DONE ----
    control_signal = new_control_signal(event_done=1, unfreeze=1)

    return {
        "status": "event_completed",
        "event_type": event_type,
        "plan": plan,
        "batches": batches,
        "control_signal": control_signal,
        "message": "Event loop finished — slow loop can resume"
    }


# -----------------------------------------------------------
# DEMO
# -----------------------------------------------------------

if __name__ == "__main__":
    def fake_metrics(aps):
        return {ap: {"throughput": 100, "p95_retry": 5} for ap in aps}

    r = run_event_loop_trigger(
        event_type="low_busy",
        scope_aps=["AP1","AP2"],
        human_trigger=True,
        channel_utilization=0.2,
        overrides = {
            "tx_power_dbm": 22,
            "channel_width_mhz": 20,
            "busy_period_s": 1,
            "free_period_s": 1,
        },
        metrics_callback=fake_metrics
    )

    print(json.dumps(r, indent=2))