import asyncio
import base64
import json
import os
import uuid
from pathlib import Path

import pytest

from microduck_studio.protocol import (
    BodyCameraClient,
    BodyFrameClient,
    ProtocolError,
    RobotdClient,
    RobotdMonitor,
)


@pytest.mark.asyncio
async def test_robotd_connection_is_reused(tmp_path):
    del tmp_path
    socket_path = Path(f"/tmp/microduck-studio-{os.getpid()}-{uuid.uuid4().hex[:6]}.sock")
    connections = 0
    messages = []

    async def serve(reader, writer):
        nonlocal connections
        connections += 1
        while line := await reader.readline():
            message = json.loads(line)
            messages.append(message)
            if "id" in message:
                writer.write(
                    json.dumps(
                        {"jsonrpc": "2.0", "id": message["id"], "result": {"accepted": True}}
                    ).encode()
                    + b"\n"
                )
                await writer.drain()

    server = await asyncio.start_unix_server(serve, socket_path)
    client = RobotdClient(socket_path)
    try:
        await client.notify("robot.move", {"vx": 0.3, "vy": 0, "vyaw": 0})
        result = await client.request("robot.stop")
        assert result == {"accepted": True}
        assert connections == 1
        assert [message["method"] for message in messages] == ["robot.move", "robot.stop"]
    finally:
        await client.close()
        server.close()
        await server.wait_closed()
        await asyncio.to_thread(socket_path.unlink, missing_ok=True)


@pytest.mark.asyncio
async def test_discrete_request_is_not_retried_after_uncertain_delivery():
    socket_path = Path(f"/tmp/microduck-studio-{os.getpid()}-{uuid.uuid4().hex[:6]}.sock")
    messages = []

    async def serve(reader, writer):
        messages.append(json.loads(await reader.readline()))
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_unix_server(serve, socket_path)
    client = RobotdClient(socket_path)
    try:
        with pytest.raises(ConnectionError, match="closed the socket"):
            await client.request("robot.do", {"skill": "roulade"})
        assert [message["method"] for message in messages] == ["robot.do"]
    finally:
        await client.close()
        server.close()
        await server.wait_closed()
        await asyncio.to_thread(socket_path.unlink, missing_ok=True)


@pytest.mark.asyncio
async def test_monitor_subscribes_at_requested_rate_and_streams_state():
    socket_path = Path(f"/tmp/microduck-studio-{os.getpid()}-{uuid.uuid4().hex[:6]}.sock")
    messages = []

    async def serve(reader, writer):
        request = json.loads(await reader.readline())
        messages.append(request)
        writer.write(
            json.dumps(
                {"jsonrpc": "2.0", "id": request["id"], "result": {"accepted": True}}
            ).encode()
            + b"\n"
        )
        writer.write(
            json.dumps(
                {"jsonrpc": "2.0", "method": "robot.state", "params": {"policy": "walk"}}
            ).encode()
            + b"\n"
        )
        await writer.drain()
        await reader.read()

    server = await asyncio.start_unix_server(serve, socket_path)
    stream = RobotdMonitor(socket_path).messages(hz=10)
    try:
        assert await anext(stream) == {"type": "subscribed", "data": {"accepted": True}}
        assert await anext(stream) == {"type": "state", "data": {"policy": "walk"}}
        assert messages[0]["method"] == "robot.subscribe"
        assert messages[0]["params"] == {"hz": 10}
    finally:
        await stream.aclose()
        server.close()
        await server.wait_closed()
        await asyncio.to_thread(socket_path.unlink, missing_ok=True)


@pytest.mark.asyncio
async def test_body_frame_client_reuses_connection_and_skips_timeouts():
    connections = 0
    requests = []
    jpeg = b"\xff\xd8frame\xff\xd9"

    async def serve(reader, writer):
        nonlocal connections
        connections += 1
        first = json.loads(await reader.readline())
        requests.append(first)
        writer.write(b'{"seq":0,"timeout":true}\n')
        await writer.drain()
        second = json.loads(await reader.readline())
        requests.append(second)
        writer.write(
            json.dumps(
                {
                    "seq": 4,
                    "sim_time": 1.25,
                    "width": 640,
                    "height": 360,
                    "mime": "image/jpeg",
                    "backend": "egl",
                    "image_b64": base64.b64encode(jpeg).decode(),
                }
            ).encode()
            + b"\n"
        )
        await writer.drain()
        await reader.read()

    server = await asyncio.start_server(serve, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    stream = BodyFrameClient("127.0.0.1", port).frames()
    try:
        frame = await anext(stream)
        assert frame.seq == 4
        assert frame.image == jpeg
        assert frame.backend == "egl"
        assert connections == 1
        assert requests == [
            {"op": "render", "after": 0, "timeout_ms": 1000},
            {"op": "render", "after": 0, "timeout_ms": 1000},
        ]
    finally:
        await stream.aclose()
        server.close()
        await server.wait_closed()


def test_body_frame_client_rejects_invalid_jpeg():
    with pytest.raises(ProtocolError, match="JPEG"):
        BodyFrameClient._decode(
            {
                "seq": 1,
                "sim_time": 0,
                "width": 1,
                "height": 1,
                "mime": "image/jpeg",
                "backend": "osmesa",
                "image_b64": base64.b64encode(b"not-jpeg").decode(),
            }
        )


@pytest.mark.asyncio
async def test_body_camera_client_reuses_connection():
    connections = 0
    requests = []

    async def serve(reader, writer):
        nonlocal connections
        connections += 1
        while line := await reader.readline():
            request = json.loads(line)
            requests.append(request)
            writer.write(b'{"azimuth":90.0,"elevation":-20.0,"distance":1.2}\n')
            await writer.drain()

    server = await asyncio.start_server(serve, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    client = BodyCameraClient("127.0.0.1", port)
    try:
        await client.command("orbit", 12, -4)
        response = await client.command("zoom", 0, 30)
        await client.configure(
            width=1920,
            height=1080,
            fps=24,
            quality=100,
            image_format="png",
        )
        assert response["distance"] == 1.2
        assert connections == 1
        assert requests == [
            {"op": "camera", "action": "orbit", "dx": 12, "dy": -4},
            {"op": "camera", "action": "zoom", "dx": 0, "dy": 30},
            {
                "op": "render_config",
                "width": 1920,
                "height": 1080,
                "fps": 24,
                "quality": 100,
                "format": "png",
            },
        ]
    finally:
        await client.close()
        server.close()
        await server.wait_closed()


def test_body_frame_client_accepts_png():
    png = b"\x89PNG\r\n\x1a\ncontent"
    frame = BodyFrameClient._decode(
        {
            "seq": 2,
            "sim_time": 1,
            "width": 1920,
            "height": 1080,
            "mime": "image/png",
            "backend": "default",
            "image_b64": base64.b64encode(png).decode(),
        }
    )
    assert frame.mime == "image/png"
    assert frame.image == png
