from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import requests
import json
from app.sockets import ConnectionManager
import asyncio
from app.models import LogFormat 


app = FastAPI(
    title="Arista API",
    description="Arista API for stats on RF environment",
    summary="Arista's Summary",
    version="1.0.0"
)
manager = ConnectionManager()
origins = [
    "http://localhost:5173"
]

app.add_middleware(
CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True, 
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/sensing", response_model=list[LogFormat])
def sensing():
    resp = requests.get("http://logger:8090/log")
    data = resp.json()

    return json.loads(data["data"])


@app.websocket("/api/sensing/ws")
async def sensing_sockets(ws: WebSocket):
    await manager.connect(ws)
    try:
        while True:
            await asyncio.sleep(3600)
    except WebSocketDisconnect:
        await manager.disconnect(ws)


@app.post("/api/internal/broadcast")
async def broadcast(data: list[LogFormat]):
    await manager.broadcast(data)
    return JSONResponse({"ok": True})