from __future__ import annotations

import asyncio
import base64
import binascii
import itertools
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ProtocolError(RuntimeError):
    pass


@dataclass(frozen=True)
class SimulatorFrame:
    seq: int
    sim_time: float
    width: int
    height: int
    mime: str
    backend: str
    image: bytes


class RobotdClient:
    """Persistent newline-delimited JSON-RPC client.

    Persistence is a safety requirement, not an optimization: robotd clears motion when a control
    client disconnects.
    """

    def __init__(self, socket_path: Path, timeout: float = 2.0):
        self.socket_path = socket_path
        self.timeout = timeout
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._lock = asyncio.Lock()
        self._ids = itertools.count(1)

    async def close(self) -> None:
        if self._writer is not None:
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except OSError:
                pass
        self._reader = None
        self._writer = None

    async def _connect(self) -> None:
        if self._writer is None or self._writer.is_closing():
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_unix_connection(self.socket_path), self.timeout
            )

    async def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        await self._send(method, params, notification=True)

    async def request(self, method: str, params: dict[str, Any] | None = None) -> Any:
        return await self._send(method, params, notification=False)

    async def _send(self, method: str, params: dict[str, Any] | None, *, notification: bool) -> Any:
        async with self._lock:
            message: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
            if params is not None:
                message["params"] = params
            request_id = None if notification else next(self._ids)
            if request_id is not None:
                message["id"] = request_id
            wire = json.dumps(message, separators=(",", ":")).encode() + b"\n"

            for attempt in range(2):
                try:
                    await self._connect()
                except (OSError, ConnectionError, TimeoutError):
                    await self.close()
                    if attempt:
                        raise
                    continue

                assert self._writer is not None
                try:
                    self._writer.write(wire)
                    await asyncio.wait_for(self._writer.drain(), self.timeout)
                except (OSError, ConnectionError, TimeoutError):
                    await self.close()
                    if notification and not attempt:
                        continue
                    raise

                if notification:
                    return None

                assert self._reader is not None
                try:
                    line = await asyncio.wait_for(self._reader.readline(), self.timeout)
                    if not line:
                        raise ConnectionError("robotd closed the socket")
                except (OSError, ConnectionError, TimeoutError):
                    await self.close()
                    raise

                try:
                    response = json.loads(line)
                except (json.JSONDecodeError, UnicodeDecodeError) as error:
                    await self.close()
                    raise ProtocolError("invalid JSON-RPC response") from error
                if not isinstance(response, dict):
                    await self.close()
                    raise ProtocolError("invalid JSON-RPC response")
                if response.get("id") != request_id:
                    await self.close()
                    raise ProtocolError("unexpected JSON-RPC response id")
                if error := response.get("error"):
                    raise ProtocolError(error.get("message", str(error)))
                return response.get("result")
            raise AssertionError("unreachable")


class RobotdMonitor:
    """A dedicated ``robot.subscribe`` connection for live state frames."""

    def __init__(self, socket_path: Path, timeout: float = 2.0):
        self.socket_path = socket_path
        self.timeout = timeout

    async def messages(self, hz: int = 10) -> AsyncIterator[dict[str, Any]]:
        if not 1 <= hz <= 50:
            raise ValueError("monitor rate must be between 1 and 50 Hz")

        reader, writer = await asyncio.wait_for(
            asyncio.open_unix_connection(self.socket_path), self.timeout
        )
        request_id = 1
        request = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "robot.subscribe",
            "params": {"hz": hz},
        }
        writer.write(json.dumps(request, separators=(",", ":")).encode() + b"\n")
        await asyncio.wait_for(writer.drain(), self.timeout)

        try:
            while True:
                line = await asyncio.wait_for(reader.readline(), max(self.timeout, 2.0))
                if not line:
                    raise ConnectionError("robotd closed the monitor stream")
                try:
                    message = json.loads(line)
                except (json.JSONDecodeError, UnicodeDecodeError) as error:
                    raise ProtocolError("invalid robot monitor message") from error
                if not isinstance(message, dict):
                    raise ProtocolError("invalid robot monitor message")

                if message.get("id") == request_id:
                    if error := message.get("error"):
                        raise ProtocolError(error.get("message", str(error)))
                    result = message.get("result")
                    if not isinstance(result, dict) or not result.get("accepted"):
                        raise ProtocolError("robotd refused the monitor subscription")
                    yield {"type": "subscribed", "data": result}
                elif message.get("method") == "robot.state":
                    state = message.get("params")
                    if not isinstance(state, dict):
                        raise ProtocolError("invalid robot.state notification")
                    yield {"type": "state", "data": state}
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass


class BodyClient:
    def __init__(self, host: str, port: int, timeout: float = 1.0):
        self.host = host
        self.port = port
        self.timeout = timeout

    async def read(self) -> dict[str, Any]:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(self.host, self.port), self.timeout
        )
        try:
            writer.write(b'{"op":"read"}\n')
            await writer.drain()
            line = await asyncio.wait_for(reader.readline(), self.timeout)
            if not line:
                raise ConnectionError("simulator body closed the connection")
            try:
                response = json.loads(line)
            except (json.JSONDecodeError, UnicodeDecodeError) as error:
                raise ProtocolError("invalid simulator response") from error
            if not isinstance(response, dict):
                raise ProtocolError("invalid simulator response")
            if error := response.get("error"):
                raise ProtocolError(error)
            return response
        finally:
            writer.close()
            await writer.wait_closed()


class BodyFrameClient:
    """Long-poll cached frames over one persistent duck-body connection."""

    MAX_FRAME_LINE = 32 * 1024 * 1024

    def __init__(self, host: str, port: int, timeout: float = 2.0):
        self.host = host
        self.port = port
        self.timeout = timeout

    async def frames(self) -> AsyncIterator[SimulatorFrame]:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(self.host, self.port, limit=self.MAX_FRAME_LINE),
            self.timeout,
        )
        after = 0
        try:
            while True:
                request = {"op": "render", "after": after, "timeout_ms": 1000}
                writer.write(json.dumps(request, separators=(",", ":")).encode() + b"\n")
                await asyncio.wait_for(writer.drain(), self.timeout)
                line = await asyncio.wait_for(reader.readline(), max(self.timeout, 1.5))
                if not line:
                    raise ConnectionError("simulator body closed the frame stream")
                try:
                    response = json.loads(line)
                except (json.JSONDecodeError, UnicodeDecodeError) as error:
                    raise ProtocolError("invalid simulator frame response") from error
                if not isinstance(response, dict):
                    raise ProtocolError("invalid simulator frame response")
                if error := response.get("error"):
                    raise ProtocolError(str(error))
                if response.get("timeout"):
                    continue
                frame = self._decode(response)
                if frame.seq <= after:
                    raise ProtocolError("simulator frame sequence did not advance")
                after = frame.seq
                yield frame
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass

    @staticmethod
    def _decode(response: dict[str, Any]) -> SimulatorFrame:
        try:
            seq = int(response["seq"])
            sim_time = float(response["sim_time"])
            width = int(response["width"])
            height = int(response["height"])
            mime = response["mime"]
            backend = response["backend"]
            image = base64.b64decode(response["image_b64"], validate=True)
        except (KeyError, TypeError, ValueError, binascii.Error) as error:
            raise ProtocolError("invalid simulator frame metadata") from error
        if seq < 1 or width < 1 or height < 1:
            raise ProtocolError("invalid simulator frame metadata")
        if mime not in {"image/jpeg", "image/png"} or not isinstance(backend, str):
            raise ProtocolError("unsupported simulator frame format")
        if mime == "image/jpeg" and (
            not image.startswith(b"\xff\xd8") or not image.endswith(b"\xff\xd9")
        ):
            raise ProtocolError("invalid simulator JPEG frame")
        if mime == "image/png" and not image.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ProtocolError("invalid simulator PNG frame")
        return SimulatorFrame(seq, sim_time, width, height, mime, backend, image)


class BodyCameraClient:
    """Persistent control connection for the authoritative MuJoCo camera."""

    def __init__(self, host: str, port: int, timeout: float = 2.0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._lock = asyncio.Lock()

    async def close(self) -> None:
        if self._writer is not None:
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except OSError:
                pass
        self._reader = None
        self._writer = None

    async def command(self, action: str, dx: float = 0.0, dy: float = 0.0) -> dict[str, Any]:
        return await self._request({"op": "camera", "action": action, "dx": dx, "dy": dy})

    async def configure(
        self,
        *,
        width: int,
        height: int,
        fps: int,
        quality: int,
        image_format: str,
    ) -> dict[str, Any]:
        return await self._request(
            {
                "op": "render_config",
                "width": width,
                "height": height,
                "fps": fps,
                "quality": quality,
                "format": image_format,
            }
        )

    async def _request(self, request: dict[str, Any]) -> dict[str, Any]:
        wire = json.dumps(request, separators=(",", ":")).encode() + b"\n"
        async with self._lock:
            if self._writer is None or self._writer.is_closing():
                self._reader, self._writer = await asyncio.wait_for(
                    asyncio.open_connection(self.host, self.port), self.timeout
                )
            assert self._reader is not None
            assert self._writer is not None
            try:
                self._writer.write(wire)
                await asyncio.wait_for(self._writer.drain(), self.timeout)
                line = await asyncio.wait_for(self._reader.readline(), self.timeout)
                if not line:
                    raise ConnectionError("simulator body closed the camera connection")
            except (OSError, ConnectionError, TimeoutError):
                await self.close()
                raise

            try:
                response = json.loads(line)
            except (json.JSONDecodeError, UnicodeDecodeError) as error:
                await self.close()
                raise ProtocolError("invalid simulator camera response") from error
            if not isinstance(response, dict):
                await self.close()
                raise ProtocolError("invalid simulator camera response")
            if error := response.get("error"):
                raise ProtocolError(str(error))
            return response
