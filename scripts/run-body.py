#!/usr/bin/env python3
"""Launch duck-body from one validated, reloadable Studio scene selection."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def selected_scene(config: Path, rl_root: Path) -> Path:
    payload = json.loads(config.read_text(encoding="utf-8"))
    name = payload.get("scene")
    if not isinstance(name, str) or Path(name).name != name or not name.startswith("scene"):
        raise SystemExit("Studio simulator config has an invalid scene name")
    scene = rl_root / "src" / "mjlab_microduck" / "robot" / "microduck" / name
    if scene.suffix != ".xml" or not scene.is_file():
        raise SystemExit(f"Studio simulator scene does not exist: {name}")
    return scene


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--rl-root", type=Path, required=True)
    parser.add_argument("--mjpython", type=Path)
    args, body_args = parser.parse_known_args()

    scene = selected_scene(args.config, args.rl_root)
    command = [sys.executable]
    if args.mjpython is not None:
        command.append(str(args.mjpython))
    command.extend(["-m", "mjlab_microduck.sim.body_server", "--scene", str(scene), *body_args])
    os.execv(sys.executable, command)


if __name__ == "__main__":
    main()
