#!/usr/bin/env python3
"""Execute the fixed service operations requested by the local Studio UI."""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import time
from pathlib import Path

ROBOTD_CONTAINER = "microduck-studio-robotd"
MUJOCO_CONTAINER = "microduck-studio-mujoco"


def atomic_json(path: Path, payload: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload), encoding="utf-8")
    temporary.replace(path)


def command_for(
    service: str,
    action: str,
    mode: str,
    domain: str,
    body_label: str,
    docker: str,
    launchctl: str,
) -> list[str]:
    if service == "robotd":
        return [docker, "restart", ROBOTD_CONTAINER]
    if service == "mujoco" and mode == "docker":
        return [docker, "restart", MUJOCO_CONTAINER]
    if service == "mujoco" and mode == "native":
        target = f"{domain}/{body_label}"
        return [launchctl, "kickstart", "-k", target]
    raise ValueError("unsupported service operation")


def handle(
    path: Path,
    *,
    mode: str,
    domain: str,
    body_label: str,
    docker: str,
    launchctl: str,
    body_port: int,
) -> None:
    working = path.with_name(path.name.replace(".request.json", ".working.json"))
    try:
        path.replace(working)
    except FileNotFoundError:
        return

    request_id = working.name.removesuffix(".working.json")
    response_path = working.with_name(f"{request_id}.response.json")
    try:
        request = json.loads(working.read_text(encoding="utf-8"))
        if request.get("id") != request_id:
            raise ValueError("request id does not match its file name")
        service = request.get("service")
        action = request.get("action")
        if service not in {"robotd", "mujoco"} or action not in {"start", "restart"}:
            raise ValueError("unsupported service operation")
        command = command_for(service, action, mode, domain, body_label, docker, launchctl)
        result = subprocess.run(command, capture_output=True, text=True, timeout=20, check=False)
        if result.returncode:
            detail = (result.stderr or result.stdout).strip() or f"exit {result.returncode}"
            payload = {"id": request_id, "ok": False, "message": detail}
        else:
            if service == "mujoco":
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline:
                    try:
                        with socket.create_connection(("127.0.0.1", body_port), timeout=0.2):
                            break
                    except OSError:
                        time.sleep(0.2)
                else:
                    raise TimeoutError(f"MuJoCo did not listen on port {body_port}")
                subprocess.run(
                    [docker, "restart", ROBOTD_CONTAINER],
                    capture_output=True,
                    text=True,
                    timeout=20,
                    check=True,
                )
            payload = {"id": request_id, "ok": True, "message": f"{service} {action} requested"}
    except (OSError, ValueError, subprocess.SubprocessError, json.JSONDecodeError) as error:
        payload = {"id": request_id, "ok": False, "message": str(error)}
    finally:
        working.unlink(missing_ok=True)
    atomic_json(response_path, payload)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--mode", choices=("native", "docker"), required=True)
    parser.add_argument("--domain", required=True)
    parser.add_argument("--body-label", required=True)
    parser.add_argument("--docker", required=True)
    parser.add_argument("--launchctl", default="launchctl")
    parser.add_argument("--body-port", type=int, required=True)
    args = parser.parse_args()

    args.directory.mkdir(parents=True, exist_ok=True)
    heartbeat = args.directory / "manager.json"
    while True:
        atomic_json(heartbeat, {"at": time.time(), "pid": os.getpid(), "mode": args.mode})
        for request in args.directory.glob("*.request.json"):
            handle(
                request,
                mode=args.mode,
                domain=args.domain,
                body_label=args.body_label,
                docker=args.docker,
                launchctl=args.launchctl,
                body_port=args.body_port,
            )
        time.sleep(0.1)


if __name__ == "__main__":
    main()
