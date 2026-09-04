from __future__ import annotations

import asyncio
import re
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

TASK_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,120}$")


@dataclass(slots=True)
class Job:
    id: str
    kind: str
    task_id: str
    argv: list[str]
    cwd: str
    log_path: str
    started_at: float
    pid: int
    status: str = "running"
    exit_code: int | None = None
    finished_at: float | None = None

    def json(self) -> dict:
        return asdict(self)


class JobManager:
    def __init__(self, repo: Path, runtime_dir: Path, enabled: bool):
        self.repo = repo
        self.runtime_dir = runtime_dir
        self.enabled = enabled
        self.jobs: dict[str, Job] = {}
        self._processes: dict[str, asyncio.subprocess.Process] = {}

    @staticmethod
    def smoke_argv(task_id: str) -> list[str]:
        if not TASK_ID.fullmatch(task_id):
            raise ValueError("invalid task id")
        return [
            "uv",
            "run",
            "train",
            task_id,
            "--env.scene.num-envs",
            "64",
            "--agent.max_iterations",
            "5",
        ]

    async def start_smoke(self, task_id: str) -> Job:
        if not self.enabled:
            raise PermissionError("training jobs are disabled")
        argv = self.smoke_argv(task_id)
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        job_id = uuid.uuid4().hex[:12]
        log_path = self.runtime_dir / f"{job_id}.log"
        log_file = log_path.open("wb")
        try:
            process = await asyncio.create_subprocess_exec(
                *argv,
                cwd=self.repo,
                stdout=log_file,
                stderr=asyncio.subprocess.STDOUT,
            )
        except Exception:
            log_file.close()
            raise
        job = Job(
            id=job_id,
            kind="smoke",
            task_id=task_id,
            argv=argv,
            cwd=str(self.repo),
            log_path=str(log_path),
            started_at=time.time(),
            pid=process.pid,
        )
        self.jobs[job_id] = job
        self._processes[job_id] = process
        asyncio.create_task(self._watch(job, process, log_file))
        return job

    async def _watch(self, job: Job, process: asyncio.subprocess.Process, log_file) -> None:
        job.exit_code = await process.wait()
        job.finished_at = time.time()
        job.status = "succeeded" if job.exit_code == 0 else "failed"
        log_file.close()
        self._processes.pop(job.id, None)

    def list(self) -> list[dict]:
        return [
            job.json()
            for job in sorted(self.jobs.values(), key=lambda j: j.started_at, reverse=True)
        ]

    def log_tail(self, job_id: str, limit: int = 40_000) -> str:
        job = self.jobs.get(job_id)
        if job is None:
            raise KeyError(job_id)
        with Path(job.log_path).open("rb") as stream:
            stream.seek(0, 2)
            size = stream.tell()
            stream.seek(max(0, size - limit))
            return stream.read().decode(errors="replace")

    async def stop_all(self) -> None:
        processes = list(self._processes.values())
        for process in processes:
            process.terminate()
        if processes:
            await asyncio.gather(*(process.wait() for process in processes))
