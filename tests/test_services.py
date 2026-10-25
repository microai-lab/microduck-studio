import asyncio
import importlib.util
import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from microduck_studio.services import ServiceController


@pytest.mark.parametrize(
    "scene,accepted",
    [
        ("scene.xml", True),
        ("scene_velstand.xml", True),
        ("../scene_velstand.xml", False),
        ("scene_missing.xml", False),
        ("scene_directory.xml", False),
    ],
)
def test_host_manager_scene_allowlist_includes_extension_files(
    tmp_path, monkeypatch, scene, accepted
):
    path = Path(__file__).resolve().parents[1] / "scripts/service-manager.py"
    spec = importlib.util.spec_from_file_location("scene_manager_test", path)
    assert spec and spec.loader
    manager = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(manager)
    package = tmp_path / "rl" / "src" / "mjlab_microduck"
    scene_root = package / "robot/microduck"
    extension_root = package / "sim/visualization/scenes"
    scene_root.mkdir(parents=True)
    extension_root.mkdir(parents=True)
    (scene_root / "scene.xml").write_text("<mujoco/>")
    (extension_root / "scene_velstand.xml").write_text("<mujoco/>")
    (extension_root / "scene_directory.xml").mkdir()
    config = tmp_path / "simulator.json"
    config.write_text('{"scene":"scene.xml"}')
    request = tmp_path / "123.request.json"
    request.write_text(
        json.dumps({"id": "123", "service": "mujoco", "action": "restart", "scene": scene})
    )
    commands = []

    def run(command, **kwargs):
        commands.append(command)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(manager.subprocess, "run", run)
    monkeypatch.setattr(manager, "wait_tcp", lambda *args: None)
    monkeypatch.setattr(manager, "wait_robotd", lambda *args: None)
    manager.handle(
        request,
        mode="docker",
        domain="test",
        body_label="test",
        docker="docker",
        launchctl="launchctl",
        body_port=7801,
        head_camera_port=7901,
        simulator_config=config,
        scene_directory=scene_root,
    )
    response = json.loads((tmp_path / "123.response.json").read_text())
    assert response["ok"] is accepted
    assert json.loads(config.read_text())["scene"] == (scene if accepted else "scene.xml")
    if accepted:
        assert commands[0] == ["docker", "restart", "microduck-studio-mujoco"]
    else:
        assert not commands


def test_manager_availability_requires_a_fresh_heartbeat(tmp_path):
    controller = ServiceController(tmp_path)
    assert not controller.available()

    (tmp_path / "manager.json").write_text(json.dumps({"at": time.time()}))
    assert controller.available()

    (tmp_path / "manager.json").write_text(json.dumps({"at": time.time() - 10}))
    assert not controller.available()


@pytest.mark.asyncio
async def test_request_uses_a_fixed_file_protocol(tmp_path):
    (tmp_path / "manager.json").write_text(json.dumps({"at": time.time()}))
    controller = ServiceController(tmp_path, timeout=1)
    pending = asyncio.create_task(controller.request("mujoco", "restart", scene="scene_vslam.xml"))

    request_path = None
    for _ in range(20):
        matches = list(tmp_path.glob("*.request.json"))
        if matches:
            request_path = matches[0]
            break
        await asyncio.sleep(0.01)
    assert request_path is not None
    request = json.loads(request_path.read_text())
    assert request["service"] == "mujoco"
    assert request["action"] == "restart"
    assert request["scene"] == "scene_vslam.xml"

    response_path = tmp_path / f"{request['id']}.response.json"
    response_path.write_text(json.dumps({"id": request["id"], "ok": True}))
    assert (await pending)["ok"] is True
    assert not response_path.exists()


@pytest.mark.asyncio
async def test_request_rejects_commands_outside_the_allowlist(tmp_path):
    controller = ServiceController(tmp_path)
    with pytest.raises(ValueError, match="unsupported service operation"):
        await controller.request("studio", "delete")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="only be selected"):
        await controller.request("robotd", "restart", scene="scene.xml")


@pytest.mark.asyncio
async def test_tofd_restart_uses_the_fixed_file_protocol(tmp_path):
    (tmp_path / "manager.json").write_text(json.dumps({"at": time.time()}))
    controller = ServiceController(tmp_path, timeout=1)
    pending = asyncio.create_task(controller.request("tofd", "restart"))

    request_path = None
    for _ in range(20):
        matches = list(tmp_path.glob("*.request.json"))
        if matches:
            request_path = matches[0]
            break
        await asyncio.sleep(0.01)
    assert request_path is not None
    request = json.loads(request_path.read_text())
    assert request["service"] == "tofd"
    assert request["action"] == "restart"
    assert "scene" not in request

    response_path = tmp_path / f"{request['id']}.response.json"
    response_path.write_text(json.dumps({"id": request["id"], "ok": True}))
    assert (await pending)["ok"] is True
