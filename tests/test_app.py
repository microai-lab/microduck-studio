import asyncio
import threading
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from microduck_studio.app import RenderCommand, create_app, render_profile
from microduck_studio.config import Settings
from microduck_studio.protocol import ROBOTD_API_VERSION, ProtocolError, RpcError


def settings(tmp_path: Path) -> Settings:
    return Settings(
        microduck_repo=tmp_path / "microduck",
        microduck_rl_repo=tmp_path / "microduck_rl",
        robotd_socket=tmp_path / "robotd.sock",
        tofd_socket=tmp_path / "tofd.sock",
        body_host="127.0.0.1",
        body_port=1,
        head_camera_port=1,
        host="127.0.0.1",
        port=8090,
        enable_jobs=False,
        runtime_dir=tmp_path / "runtime",
        runtime_ref="main",
        runtime_revision="213a5ce90ec5f2605b6e6977b75672d9d2eea8c5",
    )


def test_index_is_served(tmp_path):
    with TestClient(create_app(settings(tmp_path))) as client:
        response = client.get("/")
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert "Microduck Studio" in response.text
        assert "MuJoCo 场景" in response.text
        assert "MuJoCo scene" in response.text
        assert "启用 RL / 站起" in response.text
        assert "Enable RL / Stand up" in response.text
        assert "实时监视器" in response.text
        assert "Live robot monitor" in response.text
        assert "/static/styles.css?v=workbench-46" in response.text
        assert "/static/app.js?v=workbench-46" in response.text
        assert 'data-placeholder-zh="任务 ID"' in response.text
        assert 'data-placeholder-en="TASK_ID"' in response.text
        assert "loop rate" in response.text
        assert "±11.5°" in response.text
        assert "rad/s" in response.text
        assert ">mA</span>" in response.text
        assert 'data-service="robotd"' in response.text
        assert 'data-service="mujoco"' in response.text
        assert 'data-service="tofd"' in response.text
        assert '<strong id="tofd">—</strong>' in response.text
        assert 'id="tofd-detail"' in response.text
        assert response.text.count("runtime-service-card") == 3
        assert "拖动旋转" in response.text
        assert 'data-sim-view="head"' in response.text
        assert 'data-sim-view="world" aria-pressed="true"' in response.text
        assert 'data-sim-view="head" aria-pressed="false"' in response.text
        assert 'id="sim-scene"' in response.text
        assert 'id="scene-copy-status"' in response.text
        assert 'id="scene-copy"' in response.text
        assert 'id="tof-grid"' in response.text
        assert 'id="monitor-imu-gyro"' in response.text
        assert 'id="monitor-frame-camera"' in response.text
        assert 'id="head-imu-stream-status"' in response.text
        assert (
            '<option value="clear" data-zh="清晰" data-en="Clear" selected>清晰</option>'
            in response.text
        )


def test_camera_selection_is_independent_from_motion_button_state(tmp_path):
    with TestClient(create_app(settings(tmp_path))) as client:
        script = client.get("/static/app.js")
        assert script.status_code == 200
        assert "button.setAttribute('aria-pressed'" in script.text
        assert "document.querySelectorAll('.active')" not in script.text
        assert "[data-vx].active,[data-vy].active,[data-vyaw].active" in script.text


def test_sensor_websocket_closes_after_source_error_so_the_browser_reconnects(tmp_path):
    with TestClient(create_app(settings(tmp_path))) as client:
        with client.websocket_connect("/ws/sensors") as websocket:
            assert websocket.receive_json()["type"] == "sensor-error"
            with pytest.raises(WebSocketDisconnect):
                websocket.receive_json()


def test_training_is_opt_in(tmp_path):
    with TestClient(create_app(settings(tmp_path))) as client:
        response = client.post("/api/training/smoke", json={"task_id": "Microduck-Velocity-v0"})
        assert response.status_code == 403


def test_status_reports_the_runtime_source_that_was_actually_built(tmp_path):
    with TestClient(create_app(settings(tmp_path))) as client:
        response = client.get("/api/status")
        assert response.status_code == 200
        assert response.json()["robotd"]["source"] == {
            "ref": "main",
            "revision": "213a5ce90ec5f2605b6e6977b75672d9d2eea8c5",
        }


@pytest.mark.parametrize("api_version", [ROBOTD_API_VERSION, ROBOTD_API_VERSION - 1])
def test_status_reports_running_daemon_and_version_skew(tmp_path, api_version):
    app = create_app(settings(tmp_path))
    hello = {"api_version": api_version, "daemon_version": "0.17.8", "revision": "running-revision"}
    health = {
        "healthy": False,
        "degraded": True,
        "reason": "no servo power",
        "bus": {"missing": [32, 33]},
        "imu": {"missing": True},
        "cpu_throttle": {"max_khz": 1800000, "current_khz": 408000},
    }
    app.state.robot.hello = AsyncMock(return_value=hello)
    app.state.robot.request = AsyncMock(return_value=health)
    with TestClient(app) as client:
        robotd = client.get("/api/status").json()["robotd"]
        assert robotd["connected"] is True
        assert robotd["health"] == health
        assert robotd["hello"] == hello
        assert robotd["protocol"] == {
            "client_api_version": ROBOTD_API_VERSION,
            "matches": api_version == ROBOTD_API_VERSION,
        }
        app.state.robot.request.assert_awaited_once_with("robot.health", {})


def test_status_does_not_report_malformed_health_as_connected(tmp_path):
    app = create_app(settings(tmp_path))
    app.state.robot.hello = AsyncMock(return_value={"api_version": ROBOTD_API_VERSION})
    app.state.robot.request = AsyncMock(return_value={"healthy": "yes"})
    with TestClient(app) as client:
        robotd = client.get("/api/status").json()["robotd"]
        assert robotd["connected"] is False
        assert "health result" in robotd["error"]


@pytest.mark.parametrize(
    "refusal",
    [
        {"accepted": False, "reason": "the policy is not driving"},
        RpcError(
            {"code": -32601, "message": "robot.do is unavailable", "data": {"api_version": 43}}
        ),
    ],
)
def test_control_reports_daemon_refusals_as_conflicts(tmp_path, refusal):
    app = create_app(settings(tmp_path))
    if isinstance(refusal, RpcError):
        app.state.robot.request = AsyncMock(side_effect=refusal)
        detail = refusal.error
    else:
        app.state.robot.request = AsyncMock(return_value=refusal)
        detail = refusal
    with TestClient(app) as client:
        response = client.post("/api/control/skill", json={"skill": "jump"})
        assert response.status_code == 409
        assert response.json()["detail"] == detail
        app.state.robot.request.assert_awaited_once_with("robot.do", {"skill": "jump"})


@pytest.mark.parametrize(
    "failure", [ProtocolError("malformed response"), ConnectionError("offline")]
)
def test_control_reports_protocol_and_connection_failures_as_unavailable(tmp_path, failure):
    app = create_app(settings(tmp_path))
    app.state.robot.request = AsyncMock(side_effect=failure)
    with TestClient(app) as client:
        response = client.post("/api/control/stop")
        assert response.status_code == 503
        assert response.json()["detail"] == str(failure)


def test_control_uses_notifications_for_move_and_requests_for_stop(tmp_path):
    app = create_app(settings(tmp_path))
    app.state.robot.notify = AsyncMock()
    app.state.robot.request = AsyncMock(return_value={"accepted": True})
    with TestClient(app) as client:
        assert client.post("/api/control/move", json={"vx": 0.2}).status_code == 200
        app.state.robot.notify.assert_awaited_once_with(
            "robot.move", {"vx": 0.2, "vy": 0.0, "vyaw": 0.0}
        )
        app.state.robot.request.assert_not_awaited()
        assert client.post("/api/control/stop").json() == {"accepted": True}
        app.state.robot.request.assert_awaited_once_with("robot.stop", None)
    # Shutdown also waits for an explicit stop response before closing the control socket.
    assert app.state.robot.request.await_args_list[-1].args == ("robot.stop",)


@pytest.mark.parametrize(
    "command",
    [
        {"vy": 0.6},
        {"vy": -0.3},
        {"vy": 0.0},
        {"vx": 0.4, "vy": 0.3, "vyaw": 1.5},
        {"vx": -0.4, "vy": -0.3, "vyaw": -1.5},
    ],
)
def test_move_accepts_left_start_command_and_preserves_other_axis_limits(tmp_path, command):
    app = create_app(settings(tmp_path))
    app.state.robot.notify = AsyncMock()
    app.state.robot.request = AsyncMock(return_value={"accepted": True})
    with TestClient(app) as client:
        assert client.post("/api/control/move", json=command).status_code == 200
        app.state.robot.notify.assert_awaited_once_with(
            "robot.move", {"vx": 0.0, "vy": 0.0, "vyaw": 0.0} | command
        )


@pytest.mark.parametrize(
    "command",
    [
        {"vy": 0.60001},
        {"vy": -0.30001},
        {"vx": 0.40001},
        {"vx": -0.40001},
        {"vyaw": 1.50001},
        {"vyaw": -1.50001},
        {"vy": "NaN"},
        {"vy": "Infinity"},
        {"vy": "-Infinity"},
    ],
)
def test_move_rejects_excessive_or_nonfinite_commands_before_robotd(tmp_path, command):
    app = create_app(settings(tmp_path))
    app.state.robot.notify = AsyncMock()
    app.state.robot.request = AsyncMock(return_value={"accepted": True})
    with TestClient(app) as client:
        assert client.post("/api/control/move", json=command).status_code == 422
        app.state.robot.notify.assert_not_awaited()


@pytest.mark.parametrize("skill", ["", "../jump", "jump now", "jump\n", "a" * 129])
def test_skill_names_are_validated_before_reaching_robotd(tmp_path, skill):
    app = create_app(settings(tmp_path))
    app.state.robot.request = AsyncMock(return_value={"accepted": True})
    with TestClient(app) as client:
        assert client.post("/api/control/skill", json={"skill": skill}).status_code == 422
        app.state.robot.request.assert_not_awaited()


def test_monitor_websocket_closes_after_source_error(tmp_path):
    with TestClient(create_app(settings(tmp_path))) as client:
        with client.websocket_connect("/ws/monitor") as websocket:
            assert websocket.receive_json()["type"] == "error"
            with pytest.raises(WebSocketDisconnect):
                websocket.receive_json()


@pytest.mark.parametrize("route", ["/ws/monitor", "/ws/sensors"])
def test_idle_upstream_streams_close_when_browser_disconnects(tmp_path, monkeypatch, route):
    closed = {
        name: threading.Event() for name in ("robot.subscribe", "tof.stream", "head_imu.stream")
    }

    async def monitor_messages(self, hz=10):
        del self, hz
        try:
            yield {"type": "subscribed", "data": {"accepted": True}}
            await asyncio.Event().wait()
        finally:
            closed["robot.subscribe"].set()

    async def sensor_messages(self):
        try:
            yield {"type": "sensor-subscribed", "data": {"accepted": True}}
            await asyncio.Event().wait()
        finally:
            closed[self.method].set()

    monkeypatch.setattr("microduck_studio.app.RobotdMonitor.messages", monitor_messages)
    monkeypatch.setattr("microduck_studio.app.SensorMonitor.messages", sensor_messages)
    expected = ("tof.stream", "head_imu.stream") if route == "/ws/sensors" else ("robot.subscribe",)
    with TestClient(create_app(settings(tmp_path))) as client:
        with client.websocket_connect(route) as websocket:
            websocket.receive_json()
            if route == "/ws/sensors":
                websocket.receive_json()
            websocket.close()
            assert all(closed[name].wait(1) for name in expected)


def test_service_actions_require_the_host_manager(tmp_path):
    with TestClient(create_app(settings(tmp_path))) as client:
        response = client.post("/api/services/robotd/restart")
        assert response.status_code == 503
        assert "service manager is not available" in response.json()["detail"]

        response = client.post("/api/services/tofd/restart")
        assert response.status_code == 503
        assert "service manager is not available" in response.json()["detail"]

        response = client.post("/api/services/shell/restart")
        assert response.status_code == 422


def test_scene_catalog_and_selection_are_exposed(tmp_path):
    configured = settings(tmp_path)
    scene_root = configured.microduck_rl_repo / "src" / "mjlab_microduck" / "robot" / "microduck"
    scene_root.mkdir(parents=True)
    (scene_root / "scene.xml").write_text("<mujoco/>")
    (scene_root / "scene_vslam.xml").write_text("<mujoco/>")
    extension_root = scene_root.parent.parent / "sim" / "visualization" / "scenes"
    extension_root.mkdir(parents=True)
    (extension_root / "scene_velstand.xml").write_text("<mujoco/>")
    (extension_root / "scene_vslam.xml").write_text("<mujoco/>")
    (extension_root / "scene_directory.xml").mkdir()
    configured.runtime_dir.mkdir()
    (configured.runtime_dir / "simulator.json").write_text('{"scene":"scene_vslam.xml"}')

    with TestClient(create_app(configured)) as client:
        response = client.get("/api/scenes")
        assert response.status_code == 200
        assert response.json() == {
            "selected": "scene_vslam.xml",
            "available": ["scene.xml", "scene_velstand.xml", "scene_vslam.xml"],
        }

        response = client.post("/api/services/robotd/restart", json={"scene": "scene.xml"})
        assert response.status_code == 422


def test_render_profiles_preserve_aspect_ratio_and_cap_resolution():
    clear = render_profile(RenderCommand(type="render", profile="clear", width=3000, height=1500))
    assert clear == {
        "width": 1920,
        "height": 960,
        "fps": 24,
        "quality": 95,
        "image_format": "jpeg",
    }
    lossless = render_profile(
        RenderCommand(type="render", profile="lossless", width=1280, height=720)
    )
    assert lossless["image_format"] == "png"
