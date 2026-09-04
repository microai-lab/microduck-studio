#!/usr/bin/env python3
"""Small local transports for reaching robotd's Unix socket through Docker Desktop."""

from __future__ import annotations

import argparse
import asyncio
import select
import socket
import socketserver
from pathlib import Path


class TcpToUnixHandler(socketserver.BaseRequestHandler):
    unix_socket: Path

    def handle(self) -> None:
        upstream = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        upstream.connect(str(self.unix_socket))
        peers = [self.request, upstream]
        try:
            while True:
                readable, _, _ = select.select(peers, [], [])
                for source in readable:
                    data = source.recv(65_536)
                    if not data:
                        return
                    target = upstream if source is self.request else self.request
                    target.sendall(data)
        finally:
            upstream.close()


class ThreadingTcpServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def tcp_to_unix(host: str, port: int, unix_socket: Path) -> None:
    handler = type("ConfiguredTcpToUnixHandler", (TcpToUnixHandler,), {"unix_socket": unix_socket})
    with ThreadingTcpServer((host, port), handler) as server:
        server.serve_forever()


async def copy_stream(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while data := await reader.read(65_536):
            writer.write(data)
            await writer.drain()
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except (ConnectionError, OSError):
            pass


async def unix_client(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    tcp_host: str,
    tcp_port: int,
) -> None:
    try:
        upstream_reader, upstream_writer = await asyncio.open_connection(tcp_host, tcp_port)
    except (ConnectionError, OSError):
        writer.close()
        await writer.wait_closed()
        return
    await asyncio.gather(
        copy_stream(reader, upstream_writer),
        copy_stream(upstream_reader, writer),
    )


async def unix_to_tcp(unix_socket: Path, tcp_host: str, tcp_port: int) -> None:
    await asyncio.to_thread(unix_socket.unlink, missing_ok=True)
    server = await asyncio.start_unix_server(
        lambda reader, writer: unix_client(reader, writer, tcp_host, tcp_port),
        unix_socket,
    )
    async with server:
        await server.serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="mode", required=True)

    tcp = subparsers.add_parser("tcp-to-unix")
    tcp.add_argument("--host", default="0.0.0.0")
    tcp.add_argument("--port", type=int, required=True)
    tcp.add_argument("--unix-socket", type=Path, required=True)

    unix = subparsers.add_parser("unix-to-tcp")
    unix.add_argument("--unix-socket", type=Path, required=True)
    unix.add_argument("--host", default="127.0.0.1")
    unix.add_argument("--port", type=int, required=True)

    args = parser.parse_args()
    if args.mode == "tcp-to-unix":
        tcp_to_unix(args.host, args.port, args.unix_socket)
    else:
        asyncio.run(unix_to_tcp(args.unix_socket, args.host, args.port))


if __name__ == "__main__":
    main()
