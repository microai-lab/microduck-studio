from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

import uvicorn
from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .config import Settings
from .discovery import model_catalog, repo_status
from .jobs import JobManager
from .protocol import (
    BodyCameraClient,
    BodyClient,
    BodyFrameClient,
    ProtocolError,
    RobotdClient,
    RobotdMonitor,
)
from .services import ServiceController, ServiceManagerUnavailable


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


class CameraCommand(BaseModel):
    type: Literal["camera"]
    action: Literal["orbit", "zoom", "reset"]
    dx: float = Field(0, ge=-500, le=500)
    dy: float = Field(0, ge=-500, le=500)


class RenderCommand(BaseModel):
    type: Literal["render"]
    profile: Literal["smooth", "clear", "lossless"] = "clear"
    width: int = Field(1280, ge=1, le=3840)
    height: int = Field(720, ge=1, le=2160)


RENDER_PROFILES = {
    "smooth": {"max_width": 960, "max_height": 540, "fps": 24, "quality": 82, "format": "jpeg"},
    "clear": {"max_width": 1920, "max_height": 1080, "fps": 24, "quality": 95, "format": "jpeg"},
    "lossless": {"max_width": 1920, "max_height": 1080, "fps": 24, "quality": 100, "format": "png"},
}


def render_profile(command: RenderCommand) -> dict:
    profile = RENDER_PROFILES[command.profile]
    scale = min(
        1.0,
        profile["max_width"] / command.width,
        profile["max_height"] / command.height,
    )
    return {
        "width": max(1, round(command.width * scale)),
        "height": max(1, round(command.height * scale)),
        "fps": profile["fps"],
        "quality": profile["quality"],
        "image_format": profile["format"],
    }


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    robot = RobotdClient(settings.robotd_socket)
    body_client = BodyClient(settings.body_host, settings.body_port)
    frame_client = BodyFrameClient(settings.body_host, settings.body_port)
    jobs = JobManager(settings.microduck_rl_repo, settings.runtime_dir, settings.enable_jobs)
    services = ServiceController(settings.runtime_dir / "services")
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
    app.state.frame_client = frame_client
    app.state.jobs = jobs
    app.state.services = services

    @app.middleware("http")
    async def disable_development_asset_cache(request, call_next):
        response = await call_next(request)
        if request.url.path == "/" or request.url.path.startswith("/static/"):
            response.headers["cache-control"] = "no-store"
        return response

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
            "service_manager": {"available": services.available()},
            "training_jobs_enabled": settings.enable_jobs,
        }

    @app.post("/api/services/{service}/{action}", status_code=202)
    async def manage_service(
        service: Literal["robotd", "mujoco"], action: Literal["start", "restart"]
    ):
        try:
            result = await services.request(service, action)
        except ServiceManagerUnavailable as error:
            raise HTTPException(503, str(error)) from error
        if not result.get("ok"):
            raise HTTPException(503, result.get("message", "service operation failed"))
        return result

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

    @app.websocket("/ws/monitor")
    async def monitor(websocket: WebSocket):
        await websocket.accept()
        stream = RobotdMonitor(settings.robotd_socket)
        try:
            async for message in stream.messages(hz=10):
                await websocket.send_json(message)
        except WebSocketDisconnect:
            pass
        except (OSError, ConnectionError, TimeoutError, ProtocolError) as error:
            try:
                await websocket.send_json({"type": "error", "message": str(error)})
            except (RuntimeError, WebSocketDisconnect):
                pass

    @app.websocket("/ws/simulator")
    async def simulator(websocket: WebSocket):
        await websocket.accept()
        frames = frame_client.frames()
        camera = BodyCameraClient(settings.body_host, settings.body_port)

        async def send_frames() -> None:
            async for frame in frames:
                await websocket.send_json(
                    {
                        "type": "frame",
                        "seq": frame.seq,
                        "sim_time": frame.sim_time,
                        "width": frame.width,
                        "height": frame.height,
                        "mime": frame.mime,
                        "backend": frame.backend,
                    }
                )
                await websocket.send_bytes(frame.image)

        async def receive_camera_commands() -> None:
            while True:
                message = await websocket.receive_json()
                if message.get("type") == "camera":
                    command = CameraCommand.model_validate(message)
                    await camera.command(command.action, command.dx, command.dy)
                elif message.get("type") == "render":
                    command = RenderCommand.model_validate(message)
                    await camera.configure(**render_profile(command))
                else:
                    raise ValueError("unknown simulator WebSocket message")

        tasks = {
            asyncio.create_task(send_frames()),
            asyncio.create_task(receive_camera_commands()),
        }
        try:
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            for task in done:
                task.result()
        except WebSocketDisconnect:
            pass
        except (
            OSError,
            ConnectionError,
            TimeoutError,
            ProtocolError,
            ValueError,
        ) as error:
            try:
                await websocket.send_json({"type": "error", "message": str(error)})
            except (RuntimeError, WebSocketDisconnect):
                pass
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await frames.aclose()
            await camera.close()

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
