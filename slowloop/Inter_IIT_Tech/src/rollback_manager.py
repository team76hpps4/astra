from .logger_config import main_logger

def rollback_if_unstable(retry_p95, eirp_violation, safe_cfg, current_window):
    """Return fallback config if metrics exceed limits; otherwise None."""
    if (retry_p95 > 8.0 or eirp_violation > 30.0) and safe_cfg[current_window] is not None:
        main_logger.warning(
            "Unstable config detected: retry=%.2f eirp=%.2f. Reverting to safe config.",
            retry_p95, eirp_violation
        )
        return safe_cfg[current_window].copy()
    return None