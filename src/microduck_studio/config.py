from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    return default if value is None else value.lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True, slots=True)
class Settings:
    microduck_repo: Path
    microduck_rl_repo: Path
    robotd_socket: Path
    tofd_socket: Path
    body_host: str
    body_port: int
    head_camera_port: int
    host: str
    port: int
    enable_jobs: bool
    runtime_dir: Path
    runtime_ref: str
    runtime_revision: str

    @classmethod
    def from_env(cls) -> Settings:
        parent = Path(__file__).resolve().parents[3]
        microduck_rl_repo = Path(os.getenv("MICRODUCK_RL_REPO", parent / "microduck_rl"))
        return cls(
            microduck_repo=Path(os.getenv("MICRODUCK_REPO", parent / "microduck")),
            microduck_rl_repo=microduck_rl_repo,
            robotd_socket=Path(os.getenv("MICRODUCK_ROBOTD_SOCKET", "/run/robotd.sock")),
            tofd_socket=Path(os.getenv("MICRODUCK_TOFD_SOCKET", "/run/tofd/tof.sock")),
            body_host=os.getenv("MICRODUCK_BODY_HOST", "127.0.0.1"),
            body_port=int(os.getenv("MICRODUCK_BODY_PORT", "7801")),
            head_camera_port=int(os.getenv("MICRODUCK_HEAD_CAMERA_PORT", "7901")),
            host=os.getenv("MICRODUCK_STUDIO_HOST", "127.0.0.1"),
            port=int(os.getenv("MICRODUCK_STUDIO_PORT", "8090")),
            enable_jobs=_bool("MICRODUCK_STUDIO_ENABLE_JOBS"),
            runtime_dir=Path(os.getenv("MICRODUCK_STUDIO_RUNTIME", ".studio-runtime")),
            runtime_ref=os.getenv("MICRODUCK_RUNTIME_REF", "unknown"),
            runtime_revision=os.getenv("MICRODUCK_RUNTIME_REVISION", "unknown"),
        )
