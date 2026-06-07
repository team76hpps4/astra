import time
import yaml
import matlab.engine
from .helper import Params, scaled_sleep
from .logger_config import main_logger

MATLAB_FUNCTION = "rrm_sim"
with open("configs/policy_guradrails.yaml", "r") as f:
    config = yaml.safe_load(f)

def start_engine():
    """Start MATLAB engine, cd to project dir, and return engine instance."""
    try:
        eng = matlab.engine.start_matlab()
        eng.cd(r"src", nargout=0)
        main_logger.info("MATLAB engine started")
        return eng
    except Exception as e:
        main_logger.exception("Failed to start MATLAB engine: %s", e)
        raise


def run_matlab_online(engine, params: Params, observe_time_min: float):
    """Run RRM MATLAB function online and return (P50, retry_p95, flagged)."""
    main_logger.info("Running MATLAB feval for %s", params.as_dict())

    res = engine.feval(
        MATLAB_FUNCTION,
        float(params.obss_pd_dbm),
        float(params.tx_power_dbm),
        float(params.channel_width_mhz),
        float(observe_time_min),
        nargout=1,
    )

    scaled_sleep(config['MIN_ONLINE_OBSERVE_TIME_MINS'] * 60)

    try:
        p50 = float(res["P50_Throughput"])
        p95_retry = float(res["P95_Retry_Rate"]) * 100.0
        flagged = float(res.get("num_flagged", 0.0))
    except Exception as exc:
        main_logger.exception("Failed to parse MATLAB result: %s", exc)
        raise

    return p50, p95_retry, flagged
