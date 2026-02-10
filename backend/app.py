from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from backend.twin.config import TwinConfig, load_config, write_config
from backend.twin.core import SCENARIOS, DigitalTwinEngine

CONFIG_PATH = Path("config/default_config.yaml")


class ScenarioRequest(BaseModel):
    name: str


class StepRequest(BaseModel):
    steps: int = 1


class TwinRuntime:
    def __init__(self, config: TwinConfig) -> None:
        self.config = config
        self.engine = DigitalTwinEngine(config)
        self.state: dict[str, Any] = self.engine.simulate_step()
        self.clients: set[WebSocket] = set()
        self._loop_task: asyncio.Task[Any] | None = None

    async def start(self) -> None:
        if self._loop_task is None:
            self._loop_task = asyncio.create_task(self._ticker())

    async def _ticker(self) -> None:
        while True:
            await asyncio.sleep(1.0)
            self.state = self.engine.simulate_step()
            await self.broadcast(self.state)

    async def broadcast(self, payload: dict[str, Any]) -> None:
        stale: list[WebSocket] = []
        for client in self.clients:
            try:
                await client.send_json(payload)
            except Exception:
                stale.append(client)
        for client in stale:
            self.clients.discard(client)


runtime = TwinRuntime(load_config(CONFIG_PATH))
app = FastAPI(title="Hyperscale AI Data Center Digital Twin")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def _startup() -> None:
    await runtime.start()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/state")
def get_state() -> dict[str, Any]:
    return runtime.state


@app.get("/api/scenarios")
def list_scenarios() -> dict[str, list[str]]:
    return {"scenarios": list(SCENARIOS.keys())}


@app.post("/api/scenario")
def set_scenario(payload: ScenarioRequest) -> dict[str, Any]:
    runtime.engine.set_scenario(payload.name)
    runtime.state = runtime.engine.simulate_step()
    return {"status": "ok", "scenario": payload.name, "state": runtime.state}


@app.post("/api/simulate")
def simulate(payload: StepRequest) -> dict[str, Any]:
    for _ in range(max(1, payload.steps)):
        runtime.state = runtime.engine.simulate_step()
    return {"status": "ok", "state": runtime.state}


@app.get("/api/config")
def get_config() -> dict[str, Any]:
    return runtime.config.model_dump()


@app.put("/api/config")
def update_config(payload: dict[str, Any]) -> dict[str, Any]:
    runtime.config = TwinConfig.model_validate(payload)
    write_config(CONFIG_PATH, runtime.config)
    runtime.engine.update_config(runtime.config)
    runtime.state = runtime.engine.simulate_step()
    return {"status": "ok", "config": runtime.config.model_dump(), "state": runtime.state}


@app.websocket("/ws/state")
async def ws_state(websocket: WebSocket) -> None:
    await websocket.accept()
    runtime.clients.add(websocket)
    await websocket.send_json(runtime.state)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        runtime.clients.discard(websocket)
