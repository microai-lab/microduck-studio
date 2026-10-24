#!/usr/bin/env python3
"""Cache the policy set pinned by the exact runtime source being built."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path


def policy_spec(source: Path) -> tuple[str, str]:
    with (source / "Cargo.toml").open("rb") as stream:
        spec = tomllib.load(stream)["workspace"]["metadata"]["policies"]
    repo, version = spec["repo"], spec["version"]
    component = r"[A-Za-z0-9][A-Za-z0-9_.-]*"
    if not isinstance(repo, str) or not re.fullmatch(f"{component}/{component}", repo):
        raise ValueError("runtime policy repo must be owner/name")
    if not isinstance(version, str) or not re.fullmatch(component, version):
        raise ValueError("runtime policy version must be a plain tag")
    return repo, version


def manifest_files(directory: Path) -> list[str]:
    payload = json.loads((directory / "manifest.json").read_text())
    policies = payload.get("policies") if isinstance(payload, dict) else None
    if not isinstance(policies, list) or not policies:
        raise ValueError("policy manifest must contain a nonempty policies list")
    names = []
    for policy in policies:
        name = policy.get("file") if isinstance(policy, dict) else None
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*\.onnx", name):
            raise ValueError("policy manifest contains an invalid ONNX filename")
        path = directory / name
        if not path.is_file() or path.stat().st_size == 0:
            raise ValueError(f"policy set is incomplete: {name}")
        names.append(name)
    return names


def prepare(source: Path, cache: Path) -> Path:
    repo, version = policy_spec(source)
    # A new daemon's pin must not reuse an imported alpha set just because one old file exists.
    # Keep each runtime pin in its own namespace, preserving all older/custom caches in place.
    root = cache / repo.replace("/", "--") / version
    try:
        manifest_files(root / "current")
    except (OSError, ValueError):
        script = source / "scripts" / "seed-policies.sh"
        env = {**os.environ, "POLICY_REPO": repo, "POLICY_VERSION": version}
        print(f"Preparing runtime policies: {repo}@{version}", file=sys.stderr)
        subprocess.run(
            ["sh", str(script), str(root)],
            env=env,
            stdout=sys.stderr,
            check=True,
            timeout=180,
        )
        # Upstream seeding deliberately returns success while offline. A development stack
        # must still explain missing files before starting a daemon with an unusable gait.
        try:
            manifest_files(root / "current")
        except (OSError, ValueError) as error:
            raise RuntimeError(f"{repo}@{version} is not ready: {error}") from error
    return root.resolve()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-source", required=True, type=Path)
    parser.add_argument("--cache", required=True, type=Path)
    args = parser.parse_args()
    try:
        print(prepare(args.runtime_source, args.cache))
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as error:
        parser.exit(1, f"Policy preparation failed: {error}\n")


if __name__ == "__main__":
    main()
