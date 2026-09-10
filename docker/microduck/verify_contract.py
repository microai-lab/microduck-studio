#!/usr/bin/env python3
"""Verify the live Studio, robotd, policy, and MuJoCo boundary contracts."""

from __future__ import annotations

import argparse
import json
import math
import socket
import time
import urllib.request
from pathlib import Path
from typing import Any


def http_json(url: str, payload: dict[str, Any] | None = None) -> Any:
    body = None if payload is None else json.dumps(payload).encode()
    request = urllib.request.Request(
        url,
        data=body,
        headers={"content-type": "application/json"} if body is not None else {},
        method="POST" if body is not None else "GET",
    )
    with urllib.request.urlopen(request, timeout=3) as response:  # noqa: S310 - fixed local URL
        return json.load(response)


def monitor_state(socket_path: Path, timeout: float = 2.0) -> dict[str, Any]:
    connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    connection.settimeout(timeout)
    connection.connect(str(socket_path))
    stream = connection.makefile("rwb")
    try:
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "robot.subscribe",
            "params": {"hz": 50},
        }
        stream.write(json.dumps(request, separators=(",", ":")).encode() + b"\n")
        stream.flush()
        deadline = time.monotonic() + timeout
        accepted = False
        while time.monotonic() < deadline:
            message = json.loads(stream.readline())
            if message.get("id") == 1:
                result = message.get("result", {})
                if not result.get("accepted"):
                    raise RuntimeError(f"robot.subscribe refused: {message}")
                accepted = True
            elif message.get("method") == "robot.state":
                if not accepted:
                    raise RuntimeError("robot.state arrived before subscription acceptance")
                state = message.get("params")
                if not isinstance(state, dict):
                    raise RuntimeError("robot.state params are not an object")
                return state
        raise TimeoutError("robot.subscribe produced no state")
    finally:
        stream.close()
        connection.close()


def sensor_stream(
    socket_path: Path, method: str, notification: str, *, require_frame: bool
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    connection.settimeout(3)
    connection.connect(str(socket_path))
    stream = connection.makefile("rwb")
    try:
        request = {"jsonrpc": "2.0", "id": 1, "method": method}
        stream.write(json.dumps(request, separators=(",", ":")).encode() + b"\n")
        stream.flush()
        result = json.loads(stream.readline()).get("result", {})
        if not result.get("accepted"):
            raise RuntimeError(f"{method} refused: {result}")
        if not require_frame:
            return result, None
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            message = json.loads(stream.readline())
            if message.get("method") == notification:
                frame = message.get("params")
                if isinstance(frame, dict):
                    return result, frame
        raise TimeoutError(f"{method} produced no frame")
    finally:
        stream.close()
        connection.close()


def send_move(connection: socket.socket, vx: float) -> None:
    message = {
        "jsonrpc": "2.0",
        "method": "robot.move",
        "params": {"vx": vx, "vy": 0.0, "vyaw": 0.0},
    }
    connection.sendall(json.dumps(message, separators=(",", ":")).encode() + b"\n")


def wait_for_stopped(
    socket_path: Path, *, requested_zero: bool, timeout: float = 1.0
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        last = monitor_state(socket_path)
        move = last.get("move", {})
        requested = move.get("requested")
        applied = move.get("applied")
        if not isinstance(requested, list) or not isinstance(applied, list):
            time.sleep(0.02)
            continue
        applied_stopped = len(applied) == 3 and all(abs(float(value)) < 0.01 for value in applied)
        requested_stopped = len(requested) == 3 and all(
            abs(float(value)) < 1e-6 for value in requested
        )
        deadman = "deadman" in move.get("limited_by", [])
        if applied_stopped and (
            (requested_zero and requested_stopped) or (not requested_zero and deadman)
        ):
            return last
        time.sleep(0.02)
    raise RuntimeError(f"robot command was not safely stopped: {last}")


def position(status: dict[str, Any]) -> tuple[float, float]:
    trunk = status["simulator"]["trunk"]
    return float(trunk[0]), float(trunk[1])


def receive_exactly(connection: socket.socket, length: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < length:
        chunk = connection.recv(length - len(chunks))
        if not chunk:
            raise ConnectionError("head camera closed before one complete frame")
        chunks.extend(chunk)
    return bytes(chunks)


def verify_head_camera(host: str, port: int) -> None:
    with socket.create_connection((host, port), timeout=3) as connection:
        length = int.from_bytes(receive_exactly(connection, 4), "little")
        expected = 640 * 360 * 2
        if length != expected:
            raise RuntimeError(f"head camera frame is {length} bytes, expected {expected}")
        receive_exactly(connection, length)


def verify(args: argparse.Namespace) -> float:
    base_url = args.studio_url.rstrip("/")
    deadline = time.monotonic() + 5
    while True:
        status = http_json(f"{base_url}/api/status")
        if (
            status["robotd"].get("connected")
            and status["robotd"].get("health", {}).get("healthy")
            and status["simulator"].get("connected")
        ):
            break
        if time.monotonic() >= deadline:
            break
        time.sleep(0.1)
    robotd = status["robotd"]
    if not robotd.get("connected") or not robotd.get("health", {}).get("healthy"):
        raise RuntimeError(f"robotd is not healthy: {robotd}")
    if not status["simulator"].get("connected"):
        raise RuntimeError(f"MuJoCo is not connected: {status['simulator']}")
    source = robotd.get("source", {})
    if source.get("ref") != args.expected_ref:
        raise RuntimeError(f"runtime ref is {source.get('ref')}, expected {args.expected_ref}")
    if source.get("revision") != args.expected_revision:
        raise RuntimeError(
            f"runtime revision is {source.get('revision')}, expected {args.expected_revision}"
        )
    scenes = http_json(f"{base_url}/api/scenes")
    if scenes.get("selected") != args.expected_scene:
        raise RuntimeError(
            f"selected scene is {scenes.get('selected')}, expected {args.expected_scene}"
        )
    if args.expected_scene not in scenes.get("available", []):
        raise RuntimeError(f"selected scene is absent from the RL catalog: {scenes}")
    verify_head_camera(args.head_camera_host, args.head_camera_port)

    required = (
        "alpha_walking.onnx",
        "alpha_stand.onnx",
        "alpha_sitstand.onnx",
        "alpha_ground_pick.onnx",
        "ball_kick_left.onnx",
        "ball_kick_right.onnx",
        "roulade.onnx",
    )
    missing = [name for name in required if not (args.policy_dir / name).is_file()]
    if missing:
        raise RuntimeError(f"policy mount is incomplete: {', '.join(missing)}")

    state = monitor_state(args.robot_socket)
    if "move" not in state or "policy" not in state:
        raise RuntimeError("robot.state is missing move or policy")
    if not state.get("t_ns") or not state.get("imu") or not state.get("frames"):
        raise RuntimeError("robot.state is missing synchronized sensor observations")
    tof_status, tof_frame = sensor_stream(
        args.tof_socket, "tof.stream", "tof.frame", require_frame=True
    )
    if tof_status.get("rows") != 8 or tof_status.get("cols") != 8:
        raise RuntimeError(f"unexpected ToF geometry: {tof_status}")
    if (
        tof_frame is None
        or len(tof_frame.get("distance_mm", [])) != 64
        or len(tof_frame.get("status", [])) != 64
        or not tof_frame.get("t_ns")
    ):
        raise RuntimeError(f"invalid synchronized ToF frame: {tof_frame}")
    sensor_stream(args.tof_socket, "head_imu.stream", "head_imu.frame", require_frame=False)

    http_json(f"{base_url}/api/control/enable", {"on": True})
    before = position(http_json(f"{base_url}/api/status"))
    for _ in range(30):
        http_json(f"{base_url}/api/control/move", {"vx": 0.2, "vy": 0.0, "vyaw": 0.0})
        time.sleep(0.1)
    http_json(f"{base_url}/api/control/stop", {})
    wait_for_stopped(args.robot_socket, requested_zero=True)
    after = position(http_json(f"{base_url}/api/status"))
    distance = math.hypot(after[0] - before[0], after[1] - before[1])
    if distance < 0.02:
        raise RuntimeError(f"control path moved only {distance:.3f} m")

    control = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    control.settimeout(2)
    control.connect(str(args.robot_socket))
    try:
        for _ in range(6):
            send_move(control, 0.2)
            time.sleep(0.05)
        moving = monitor_state(args.robot_socket)
        requested = moving.get("move", {}).get("requested", [0.0])
        if abs(float(requested[0]) - 0.2) > 1e-6:
            raise RuntimeError(f"direct control command was not applied: {moving.get('move')}")
        send_move(control, 0.2)
    finally:
        control.close()
    wait_for_stopped(args.robot_socket, requested_zero=False)
    return distance


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--studio-url", default="http://studio:8090")
    parser.add_argument("--robot-socket", type=Path, default=Path("/runtime/robotd.sock"))
    parser.add_argument("--tof-socket", type=Path, default=Path("/runtime/tofd.sock"))
    parser.add_argument("--policy-dir", type=Path, default=Path("/opt/robot/policies/current"))
    parser.add_argument("--expected-ref", required=True)
    parser.add_argument("--expected-revision", required=True)
    parser.add_argument("--expected-scene", required=True)
    parser.add_argument("--head-camera-host", required=True)
    parser.add_argument("--head-camera-port", type=int, required=True)
    args = parser.parse_args()
    distance = verify(args)
    print(
        "contract probe passed: runtime source, policies, scene, head camera, "
        "robot/ToF/head-IMU subscriptions, "
        f"movement {distance:.3f} m, stop, disconnect"
    )


if __name__ == "__main__":
    main()
