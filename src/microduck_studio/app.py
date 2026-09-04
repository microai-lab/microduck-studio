from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

import uvicorn
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import Settings
from .discovery import model_catalog, repo_status
from .jobs import JobManager
from .protocol import BodyClient, ProtocolError, RobotdClient


class Move(BaseModel):
    vx: float = Field(0, ge=-0.4, le=0.4)
    vy: float = Field(0, ge=-0.3, le=0.3)
    vyaw: float = Field(0, ge=-1.5, le=1.5)


class Enable(BaseModel):
    on: bool = True


class SkillRequest(BaseModel):
    skill: Literal["ground_pick", "kick_left", "kick_right", "sit_toggle", "roulade"]


class SmokeRequest(BaseModel):
    task_id: str


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    robot = RobotdClient(settings.robotd_socket)
    body_client = BodyClient(settings.body_host, settings.body_port)
    jobs = JobManager(settings.microduck_rl_repo, settings.runtime_dir, settings.enable_jobs)
    static = Path(__file__).parent / "static"

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        try:
            await robot.request("robot.stop")
        except Exception:
            pass
        await robot.close()
        await jobs.stop_all()

    app = FastAPI(title="Microduck Studio", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.robot = robot
    app.state.body = body_client
    app.state.jobs = jobs

    async def call(method: str, params: dict | None = None, *, notify: bool = False):
        try:
            if notify:
                await robot.notify(method, params)
                return {"accepted": True}
            return await robot.request(method, params)
        except (OSError, ConnectionError, TimeoutError, ProtocolError) as error:
            raise HTTPException(503, str(error)) from error

    @app.get("/api/status")
    async def status():
        microduck, rl = await asyncio.gather(
            repo_status(settings.microduck_repo), repo_status(settings.microduck_rl_repo)
        )
        try:
            body_state = await body_client.read()
            simulator = {
                "connected": True,
                "sim_time": body_state.get("sim_time"),
                "trunk": body_state.get("trunk"),
                "gravity": body_state.get("imu", {}).get("gravity"),
            }
        except (OSError, ConnectionError, TimeoutError, ProtocolError) as error:
            simulator = {"connected": False, "error": str(error)}
        try:
            robot_health = await robot.request("robot.health", {})
            robotd = {"connected": True, "health": robot_health}
        except (OSError, ConnectionError, TimeoutError, ProtocolError) as error:
            robotd = {"connected": False, "error": str(error)}
        return {
            "repositories": {"microduck": microduck, "microduck_rl": rl},
            "robotd": robotd,
            "robotd_socket": {
                "path": str(settings.robotd_socket),
                "exists": settings.robotd_socket.exists(),
            },
            "simulator": simulator,
            "training_jobs_enabled": settings.enable_jobs,
        }

    @app.post("/api/control/move")
    async def move(command: Move):
        return await call("robot.move", command.model_dump(), notify=True)

    @app.post("/api/control/stop")
    async def stop():
        return await call("robot.stop")

    @app.post("/api/control/enable")
    async def enable(command: Enable):
        return await call("robot.enable", command.model_dump())

    @app.post("/api/control/skill")
    async def skill(command: SkillRequest):
        return await call("robot.do", command.model_dump())

    @app.get("/api/models")
    async def models():
        return await asyncio.to_thread(
            model_catalog, settings.microduck_repo, settings.microduck_rl_repo
        )

    @app.get("/api/training/jobs")
    async def list_jobs():
        return jobs.list()

    @app.post("/api/training/smoke", status_code=202)
    async def smoke(command: SmokeRequest):
        try:
            return (await jobs.start_smoke(command.task_id)).json()
        except PermissionError as error:
            raise HTTPException(403, str(error)) from error
        except ValueError as error:
            raise HTTPException(422, str(error)) from error

    @app.get("/api/training/jobs/{job_id}/log")
    async def job_log(job_id: str, limit: int = Query(40_000, ge=100, le=200_000)):
        try:
            return {"log": jobs.log_tail(job_id, limit)}
        except KeyError as error:
            raise HTTPException(404, "job not found") from error

    @app.get("/", include_in_schema=False)
    async def index():
        return FileResponse(static / "index.html")

    app.mount("/static", StaticFiles(directory=static), name="static")
    return app


app = create_app()


def main() -> None:
    settings = Settings.from_env()
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port)
