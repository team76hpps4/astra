from fastapi import WebSocket 
import asyncio
from app.models import LogFormat


class ConnectionManager:
    def __init__(self):
        self.active: list[WebSocket] = []
        self.lock = asyncio.Lock()


    async def connect(self, ws: WebSocket):
        await ws.accept()
        async with self.lock:
            self.active.append(ws)


    async def disconnect(self, ws: WebSocket):
        async with self.lock:
            if ws in self.active:
                self.active.remove(ws)


    async def broadcast(self, message: list[LogFormat]):
        async with self.lock:
            dead = []
            for ws in self.active:
                try:
                    await ws.send_json(message)
                except Exception:
                    dead.append(ws)
            for ws in dead:
                self.active.remove(ws)