from datetime import datetime
from typing import Dict, Optional
from dataclasses import dataclass

@dataclass
class Params:
    """Container for RRM parameters + objective value."""
    tx_power_dbm: float
    obss_pd_dbm: float
    channel_width_mhz: float
    objective: float = 0.0

    def as_dict(self) -> Dict[str, float]:
        """Return parameters as a float-only dict."""
        return {
            "tx_power_dbm": float(self.tx_power_dbm),
            "obss_pd_dbm": float(self.obss_pd_dbm),
            "channel_width_mhz": float(self.channel_width_mhz),
            "objective": float(self.objective)
        }

    def copy(self) -> "Params":
        """Return a shallow copy of Params."""
        return Params(self.tx_power_dbm, self.obss_pd_dbm,
                      self.channel_width_mhz, self.objective)


def get_current_window_index(ts: Optional[float] = None) -> int:
    """Return 3-hour window index (0–7) for a timestamp or now."""
    dt = datetime.now() if ts is None else datetime.fromtimestamp(ts)
    return dt.hour // 3