from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any


async def _run(*argv: str, cwd: Path, timeout_seconds: float = 2.0) -> str:
    process = await asyncio.create_subprocess_exec(
        *argv,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    stdout, _ = await asyncio.wait_for(process.communicate(), timeout_seconds)
    if process.returncode:
        raise RuntimeError(f"{argv[0]} exited {process.returncode}")
    return stdout.decode(errors="replace").strip()


async def repo_status(path: Path) -> dict[str, Any]:
    if not await asyncio.to_thread(path.is_dir):
        return {"path": str(path), "available": False}
    try:
        branch, porcelain = await asyncio.gather(
            _run("git", "branch", "--show-current", cwd=path),
            _run("git", "status", "--porcelain", cwd=path),
        )
        return {
            "path": str(path),
            "available": True,
            "branch": branch or "detached",
            "dirty": bool(porcelain),
            "changed_files": len(porcelain.splitlines()) if porcelain else 0,
        }
    except (OSError, RuntimeError, TimeoutError) as error:
        return {"path": str(path), "available": False, "error": str(error)}


def model_catalog(*roots: Path) -> list[dict[str, Any]]:
    models: list[dict[str, Any]] = []
    for root in roots:
        if not root.is_dir():
            continue
        for path in root.rglob("*.onnx"):
            try:
                stat = path.stat()
            except OSError:
                continue
            models.append(
                {
                    "name": path.name,
                    "path": str(path),
                    "size_bytes": stat.st_size,
                    "modified_at": stat.st_mtime,
                }
            )
    return sorted(models, key=lambda item: item["modified_at"], reverse=True)[:200]
