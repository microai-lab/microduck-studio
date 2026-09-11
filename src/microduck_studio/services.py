from __future__ import annotations

import asyncio
import json
import time
import uuid
from pathlib import Path
from typing import Literal

ServiceName = Literal["robotd", "mujoco", "tofd"]
ServiceAction = Literal["start", "restart"]


class ServiceManagerUnavailable(RuntimeError):
    pass


class ServiceController:
    """File-based bridge to the host launcher with a deliberately tiny command surface."""

    def __init__(self, directory: Path, timeout: float = 30.0):
        self.directory = directory
        self.timeout = timeout

    def available(self) -> bool:
        heartbeat = self.directory / "manager.json"
        try:
            payload = json.loads(heartbeat.read_text())
            return time.time() - float(payload["at"]) < 3.0
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            return False

    async def request(
        self, service: ServiceName, action: ServiceAction, *, scene: str | None = None
    ) -> dict:
        if service not in {"robotd", "mujoco", "tofd"} or action not in {
            "start",
            "restart",
        }:
            raise ValueError("unsupported service operation")
        if scene is not None and service != "mujoco":
            raise ValueError("a scene can only be selected for MuJoCo")
        if not self.available():
            raise ServiceManagerUnavailable("host service manager is not available")

        request_id = uuid.uuid4().hex
        request_path = self.directory / f"{request_id}.request.json"
        response_path = self.directory / f"{request_id}.response.json"
        request = {"id": request_id, "service": service, "action": action}
        if scene is not None:
            request["scene"] = scene
        request_path.write_text(json.dumps(request), encoding="utf-8")
        deadline = asyncio.get_running_loop().time() + self.timeout
        try:
            while asyncio.get_running_loop().time() < deadline:
                try:
                    response = json.loads(response_path.read_text(encoding="utf-8"))
                except FileNotFoundError:
                    await asyncio.sleep(0.05)
                    continue
                if not isinstance(response, dict) or response.get("id") != request_id:
                    raise ServiceManagerUnavailable("invalid host service manager response")
                return response
            raise ServiceManagerUnavailable("host service manager did not respond")
        finally:
            request_path.unlink(missing_ok=True)
            response_path.unlink(missing_ok=True)
