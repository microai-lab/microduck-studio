#!/usr/bin/env python3
"""Install the lightweight simulator from the sibling RL lock, without training extras."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tomllib
from pathlib import Path
from urllib.parse import urlsplit

BAM_REPOSITORY = "https://github.com/Rhoban/bam.git"
RUNTIME_PACKAGES = ("mujoco", "numpy", "pillow")


def runtime_requirements(lock: Path) -> list[str]:
    """Keep Docker's physics and image packages aligned with native simulation."""
    packages = tomllib.loads(lock.read_text(encoding="utf-8"))["package"]
    requirements = []
    for name in RUNTIME_PACKAGES:
        matches = [package for package in packages if package["name"] == name]
        if len(matches) != 1:
            raise ValueError(f"RL uv.lock must contain exactly one {name} package")
        package = matches[0]
        version = package.get("version", "")
        if package.get("source") != {"registry": "https://pypi.org/simple"} or not re.fullmatch(
            r"[0-9]+(?:\.[0-9]+)*", version
        ):
            raise ValueError(f"RL uv.lock must pin {name} to an exact PyPI release")
        requirements.append(f"{name}=={version}")
    return requirements


def pinned_requirements(lock: Path) -> list[str]:
    packages = tomllib.loads(lock.read_text(encoding="utf-8"))["package"]
    bam = next(package for package in packages if package["name"] == "better-actuator-models")
    source = urlsplit(bam.get("source", {}).get("git", ""))
    repository = f"{source.scheme}://{source.netloc}{source.path}"
    if repository != BAM_REPOSITORY or not re.fullmatch(r"[0-9a-f]{40}", source.fragment):
        raise ValueError("RL uv.lock must pin the official BAM repository to a full Git revision")
    dependencies = {entry["name"] for entry in bam.get("dependencies", [])}
    if dependencies != {"numpy", "colorama"}:
        raise ValueError(f"review changed BAM core dependencies before building: {dependencies}")
    colorama = next(package for package in packages if package["name"] == "colorama")
    version = colorama["version"]
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)*", version):
        raise ValueError("RL uv.lock has an invalid colorama version")
    return [
        f"colorama=={version}",
        f"better-actuator-models @ git+{BAM_REPOSITORY}@{source.fragment}",
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument(
        "--runtime", action="store_true", help="also install locked MuJoCo, NumPy, and Pillow"
    )
    args = parser.parse_args()
    # Validate all selected requirements before changing the environment. MuJoCo
    # still needs its small OpenGL/Python dependencies, while BAM must never pull
    # its optional training stack into the simulator image.
    bam = pinned_requirements(args.lock)
    if args.runtime:
        runtime = runtime_requirements(args.lock)
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "--no-cache-dir", *runtime], check=True
        )
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--no-cache-dir",
            "--no-deps",
            *bam,
        ],
        check=True,
    )


if __name__ == "__main__":
    main()
