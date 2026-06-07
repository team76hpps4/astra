from fastapi import FastAPI, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import threading
import json
import requests


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


log_lock = threading.Lock()
LOG_FILE = "./log.log"
app = FastAPI()


@app.get("/log")
async def read_log():
    try:
        with log_lock:
            with open(LOG_FILE, "r") as file:
                content = file.read()
            return JSONResponse({"data": content})
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


class Dummy(BaseModel):
    data: list[LogFormat]


@app.post("/log")
async def write_log(data: Dummy):
    try:
        with log_lock:
            with open(LOG_FILE, "w") as file:
                dump = [d.model_dump() for d in data.data]
                file.write(json.dumps(dump))
                requests.post("http://api:8000/api/internal/broadcast", json=dump)
    except Exception as e:
        print(str(e))
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))