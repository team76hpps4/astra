import logging
import os

def get_logger(name: str, log_filename: str = None) -> logging.Logger:
    """
    Returns a logger that logs to a file and console.
    
    :param name: Logger name
    :param log_filename: File to log to; if None, defaults to <name>.log in logs/
    """
    log_dir = "logs"
    os.makedirs(log_dir, exist_ok=True)
    if log_filename is None:
        log_filename = f"{name}.log"
    log_path = os.path.join(log_dir, log_filename)
    
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    
    if not logger.handlers:
        
        fh = logging.FileHandler(log_path)
        fh.setLevel(logging.INFO)
        fh.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
        ))
        logger.addHandler(fh)

    return logger

main_logger = get_logger('wifi_main')
online_logger = get_logger('online_logger') 
offline_logger = get_logger("offlline_simulations")