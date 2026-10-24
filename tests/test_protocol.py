import asyncio
import base64
import json
import os
import uuid
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

from microduck_studio.protocol import (
    ROBOTD_API_VERSION,
    BodyCameraClient,
    BodyFrameClient,
    HeadCameraClient,
    ProtocolError,
    RobotdClient,
    RobotdMonitor,
    RpcError,
    SensorMonitor,
)


@asynccontextmanager
async def robotd_peer(handler):
    socket_path = Path(f"/tmp/microduck-studio-{os.getpid()}-{uuid.uuid4().hex[:6]}.sock")

    async def serve(reader, writer):
        try:
            await handler(reader, writer)
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_unix_server(serve, socket_path)
    try:
        yield socket_path
    finally:
        server.close()
        await server.wait_closed()
        await asyncio.to_thread(socket_path.unlink, missing_ok=True)


@pytest.mark.asyncio
async def test_hello_reports_skew_and_rpc_refusal_preserves_the_connection():
    connections = 0
    messages = []
    refusal = {"code": -32602, "message": "unknown skill", "data": {"skill": "new_skill"}}

    async def serve(reader, writer):
        nonlocal connections
        connections += 1
        while line := await reader.readline():
            request = json.loads(line)
            messages.append(request)
            reply = {"jsonrpc": "2.0", "id": request["id"]}
            if request["method"] == "hello":
                reply["result"] = {"api_version": 43, "daemon_version": "0.17.7", "revision": None}
            elif request["method"] == "robot.do":
                reply["error"] = refusal
            else:
                reply["result"] = {"accepted": True}
            writer.write(b'{"jsonrpc":"2.0","method":"robot.notice","params":{}}\n')
            writer.write(json.dumps(reply).encode() + b"\n")
            await writer.drain()

    async with robotd_peer(serve) as socket_path:
        client = RobotdClient(socket_path)
        try:
            assert (await client.hello())["api_version"] == 43
            with pytest.raises(RpcError) as caught:
                await client.request("robot.do", {"skill": "new_skill"})
            assert caught.value.error == refusal
            assert await client.request("robot.stop") == {"accepted": True}
            assert connections == 1
            assert messages[0]["params"] == {"api_version": ROBOTD_API_VERSION}
            assert [message["method"] for message in messages] == [
                "hello",
                "robot.do",
                "robot.stop",
            ]
        finally:
            await client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        {"id": 1, "result": {}},
        {"jsonrpc": "1.0", "id": 1, "result": {}},
        {"jsonrpc": "2.0", "id": True, "result": {}},
        {"jsonrpc": "2.0", "id": "1", "result": {}},
        {"jsonrpc": "2.0", "id": 1},
        {"jsonrpc": "2.0", "id": 1, "result": {}, "error": None},
        {"jsonrpc": "2.0", "id": 1, "error": "refused"},
        {"jsonrpc": "2.0", "id": 1, "error": {"code": True, "message": "refused"}},
        pytest.param("x" * 65536, id="oversized"),
    ],
)
async def test_malformed_rpc_response_closes_the_control_connection(response):
    closed = asyncio.Event()

    async def serve(reader, writer):
        await reader.readline()
        writer.write(json.dumps(response).encode() + b"\n")
        await writer.drain()
        await reader.read()
        closed.set()

    async with robotd_peer(serve) as socket_path:
        client = RobotdClient(socket_path)
        try:
            with pytest.raises(ProtocolError):
                await client.request("robot.stop")
            await asyncio.wait_for(closed.wait(), 1)
        finally:
            await client.close()


@pytest.mark.asyncio
async def test_cancelled_request_closes_socket_before_the_next_command():
    received = asyncio.Event()
    closed = asyncio.Event()
    methods = []

    async def serve(reader, writer):
        request = json.loads(await reader.readline())
        methods.append(request["method"])
        if request["method"] == "robot.do":
            received.set()
            await reader.read()
            closed.set()
        else:
            writer.write(
                json.dumps(
                    {"jsonrpc": "2.0", "id": request["id"], "result": {"accepted": True}}
                ).encode()
                + b"\n"
            )
            await writer.drain()
            await reader.read()

    async with robotd_peer(serve) as socket_path:
        client = RobotdClient(socket_path)
        try:
            pending = asyncio.create_task(client.request("robot.do", {"skill": "roulade"}))
            await asyncio.wait_for(received.wait(), 1)
            pending.cancel()
            with pytest.raises(asyncio.CancelledError):
                await pending
            await asyncio.wait_for(closed.wait(), 1)
            assert await client.request("robot.stop") == {"accepted": True}
            assert methods == ["robot.do", "robot.stop"]
        finally:
            await client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("sensor", [False, True])
async def test_subscription_write_failure_closes_the_stream(monkeypatch, sensor):
    writer = Mock()
    writer.drain = AsyncMock(side_effect=ConnectionResetError("subscription failed"))
    writer.wait_closed = AsyncMock()
    monkeypatch.setattr(asyncio, "open_unix_connection", AsyncMock(return_value=(Mock(), writer)))
    monitor = (
        SensorMonitor(Path("unused"), "tof.stream") if sensor else RobotdMonitor(Path("unused"))
    )
    stream = monitor.messages()
    with pytest.raises(ConnectionResetError, match="subscription failed"):
        await anext(stream)
    writer.close.assert_called_once()
    writer.wait_closed.assert_awaited_once()


@pytest.mark.asyncio
async def test_head_camera_reads_length_prefixed_uyvy_frames():
    frame = bytes(HeadCameraClient.FRAME_BYTES)

    async def serve(reader, writer):
        del reader
        writer.write(len(frame).to_bytes(4, "little") + frame)
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(serve, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    stream = HeadCameraClient("127.0.0.1", port).frames()
    try:
        assert await anext(stream) == frame
    finally:
        await stream.aclose()
        server.close()
        await server.wait_closed()


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
    subscribed = {"accepted": True, "walk": "velstand.onnx", "skills": ["jump", "roulade"]}
    state = {
        "policy": "walk",
        "velocities": [0.25],
        "currents_ma": [83.5],
        "t_ns": 123456789,
        "skeleton": [{"p": [0, 0, 0], "q": [1, 0, 0, 0]}],
    }

    async def serve(reader, writer):
        request = json.loads(await reader.readline())
        messages.append(request)
        writer.write(
            json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": subscribed}).encode()
            + b"\n"
        )
        writer.write(
            json.dumps({"jsonrpc": "2.0", "method": "robot.state", "params": state}).encode()
            + b"\n"
        )
        await writer.drain()
        await reader.read()

    server = await asyncio.start_unix_server(serve, socket_path)
    stream = RobotdMonitor(socket_path).messages(hz=10)
    try:
        assert await anext(stream) == {"type": "subscribed", "data": subscribed}
        assert await anext(stream) == {"type": "state", "data": state}
        assert messages[0]["method"] == "robot.subscribe"
        assert messages[0]["params"] == {"hz": 10}
    finally:
        await stream.aclose()
        server.close()
        await server.wait_closed()
        await asyncio.to_thread(socket_path.unlink, missing_ok=True)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "notification", "subscribed_type", "frame_type"),
    [
        ("tof.stream", "tof.frame", "tof-subscribed", "tof"),
        ("head_imu.stream", "head_imu.frame", "head-imu-subscribed", "head-imu"),
    ],
)
async def test_sensor_monitor_subscribes_and_streams_frames(
    method, notification, subscribed_type, frame_type
):
    socket_path = Path(f"/tmp/microduck-studio-{os.getpid()}-{uuid.uuid4().hex[:6]}.sock")
    requests = []

    async def serve(reader, writer):
        request = json.loads(await reader.readline())
        requests.append(request)
        writer.write(
            json.dumps({"jsonrpc": "2.0", "id": 1, "result": {"accepted": True, "hz": 15}}).encode()
            + b"\n"
        )
        writer.write(
            json.dumps({"jsonrpc": "2.0", "method": notification, "params": {"seq": 7}}).encode()
            + b"\n"
        )
        await writer.drain()
        await reader.read()

    server = await asyncio.start_unix_server(serve, socket_path)
    stream = SensorMonitor(socket_path, method).messages()
    try:
        assert await anext(stream) == {
            "type": subscribed_type,
            "data": {"accepted": True, "hz": 15},
        }
        assert await anext(stream) == {"type": frame_type, "data": {"seq": 7}}
        assert requests == [{"jsonrpc": "2.0", "id": 1, "method": method}]
    finally:
        await stream.aclose()
        server.close()
        await server.wait_closed()
        await asyncio.to_thread(socket_path.unlink, missing_ok=True)


@pytest.mark.asyncio
async def test_sensor_monitor_allows_an_idle_stream_after_subscription():
    socket_path = Path(f"/tmp/microduck-studio-{os.getpid()}-{uuid.uuid4().hex[:6]}.sock")

    async def serve(reader, writer):
        await reader.readline()
        writer.write(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "result": {
                        "accepted": True,
                        "sensor": None,
                        "unavailable": "disabled",
                    },
                }
            ).encode()
            + b"\n"
        )
        await writer.drain()
        await reader.read()

    server = await asyncio.start_unix_server(serve, socket_path)
    stream = SensorMonitor(socket_path, "head_imu.stream", timeout=0.05).messages()
    pending = None
    try:
        subscribed = await anext(stream)
        assert subscribed["type"] == "head-imu-subscribed"
        pending = asyncio.create_task(anext(stream))
        await asyncio.sleep(0.1)
        assert not pending.done()
    finally:
        if pending is not None:
            pending.cancel()
            with suppress(asyncio.CancelledError):
                await pending
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
