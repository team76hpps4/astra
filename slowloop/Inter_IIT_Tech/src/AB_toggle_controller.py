import json
from .logger_config import main_logger

def load_ab_config(path="configs/ab_test_config.json"):
    """
    Load A/B test config from JSON. Returns empty defaults on failure.
    """
    try:
        with open(path) as f:
            return json.load(f)
    except Exception as e:
        main_logger.error("Failed to load A/B config: %s", e)
        return {"A": {}, "B": {}}