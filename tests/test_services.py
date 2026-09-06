import asyncio
import json
import time

import pytest

from microduck_studio.services import ServiceController


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
    pending = asyncio.create_task(controller.request("mujoco", "restart"))

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

    response_path = tmp_path / f"{request['id']}.response.json"
    response_path.write_text(json.dumps({"id": request["id"], "ok": True}))
    assert (await pending)["ok"] is True
    assert not response_path.exists()


@pytest.mark.asyncio
async def test_request_rejects_commands_outside_the_allowlist(tmp_path):
    controller = ServiceController(tmp_path)
    with pytest.raises(ValueError, match="unsupported service operation"):
        await controller.request("studio", "delete")  # type: ignore[arg-type]
