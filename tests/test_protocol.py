import asyncio
import json
import os
import uuid
from pathlib import Path

import pytest

from microduck_studio.protocol import RobotdClient


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
