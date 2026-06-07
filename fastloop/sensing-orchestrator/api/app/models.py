from pydantic import BaseModel

class InferenceFormat(BaseModel):
    bluetooth: float
    empty: float
    wifi: float
    zigbee: float
    microwave: float


class LogFormat(BaseModel):
    interference_power: float
    noise_power: float
    wifi_power: float
    inference: InferenceFormat
    cusum_flag: int 
    channel: int