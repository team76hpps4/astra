import yaml
import numpy as np
import optuna
from .helper import Params

with open("configs/policy_guradrails.yaml", "r") as f:
    config = yaml.safe_load(f)

def optuna_constraints(trial):
    """Compute constraint penalties (retry, EIRP) from trial user attrs."""
    retry = trial.user_attrs.get("retry_rate_p95", 0.0)
    eirp = trial.user_attrs.get("eirp_violation", 0.0)
    return (retry - config['MAX_RETRY_RATE']) * config['RETRY_RATE_PENALTY_DB'], \
           (eirp - config['MAX_EIRP_RATE']) * config['EIRP_RATE_PENALTY_DB']


def check_hysteresis(study: optuna.Study, trial: optuna.trial.Trial,
                     params: Params, prev_params: Params) -> bool:
    """Apply hysteresis: prune if parameter jumps are below dynamic thresholds."""
    if prev_params is None:
        return True

    d_tx = abs(params.tx_power_dbm - prev_params.tx_power_dbm)
    d_pd = abs(params.obss_pd_dbm - prev_params.obss_pd_dbm)

    r_tx = max(0.125, 5 * np.exp(-0.05 * trial.number))
    r_pd = max(0.25, 10 * np.exp(-0.05 * trial.number))

    if (d_tx < r_tx) and (d_pd < r_pd):
        study.tell(trial, prev_params.objective)
        return False
    return True