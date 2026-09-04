from __future__ import annotations

import asyncio
import itertools
import json
from pathlib import Path
from typing import Any


class ProtocolError(RuntimeError):
    pass


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
