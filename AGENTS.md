# AGENTS.md

Microduck Studio is a local developer product that joins two sibling repositories without copying
their responsibilities:

- `../microduck` owns the robot runtime, IPC protocol, safety, policies at inference time, media,
  updates, and hardware integration.
- `../microduck_rl` owns MuJoCo models, RL environments, reward design, training, export, and
  publication.
- This repository owns observability, safe orchestration, phone/desktop developer controls,
  cross-repository diagnostics, run comparison, and repeatable development workflows that neither
  sibling should have to embed.

## Commands

```bash
uv sync --extra dev
uv run microduck-studio
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

## Documentation

- Keep the project README in two complete versions: `README.md` in English and
  `README.zh-CN.md` in Simplified Chinese.
- GitHub and repository tooling display `README.md` by default, so it must remain the English
  version. Put Chinese prose in `README.zh-CN.md`, not inline in `README.md`.
- Keep a language switch link near the top of both files and update both versions in the same
  change whenever README content changes.
- Never show a machine-specific absolute workspace path under a user's home directory in
  documentation. Use `~` for a user-home path or, preferably, a repository-relative path when it
  remains executable.

## Product boundaries

- Do not reproduce motor control, safety gates, policy selection, or kinematics. Send the existing
  `duck-ipc-proto` JSON-RPC methods to `robotd` and display its answers.
- Do not reproduce environments, rewards, export, or publication. Invoke `microduck_rl`'s public
  `uv run` commands with explicit arguments.
- Cross-repository reads are allowed. Cross-repository writes require an explicit feature and user
  confirmation; Studio should be useful with both siblings mounted read-only.
- Never accept arbitrary shell commands from HTTP. Every executable and argument shape must be an
  allowlisted command assembled as an argv list and run with `shell=False`.
- Never expose secrets, environment dumps, policy files, or unrestricted filesystem paths through
  an API.

## Robot control invariants

- Units and frame come from `duck-ipc-proto`: `vx` forward, `vy` left, `vyaw` left-turn; metres,
  seconds, and radians.
- Continuous motion uses JSON-RPC notifications without an `id`, refreshed at 10–50 Hz.
- Keep one persistent Unix-socket connection for a control session. `robotd` intentionally zeroes
  motion when a client disconnects; opening one socket per HTTP request silently cancels movement.
- Pointer/touch release, page hide, navigation, backend shutdown, and errors must send
  `robot.stop`. Keep `robotd`'s deadman as the final safety layer.
- Discrete actions (`enable`, `stop`, skills) are requests with an `id` and their refusal must reach
  the UI. Never show success merely because bytes were written.
- A simulator restart creates a new body with fresh torque state. Start MuJoCo before `robotd`, or
  explicitly restart/reconcile `robotd`; do not assume reconnect restores actuator state.

## Training invariants

- A new training flow starts with the documented smoke test: 64 environments and 5 iterations.
- Treat `microduck_rl/AGENTS.md` as authoritative for observation layout, joint order, BAM,
  normalization, curricula, and reward conventions. Read it before adding any training feature.
- Studio records the exact argv, cwd, timestamps, exit code, and log path for every job.
- Cancellation is graceful (`terminate`, bounded wait, then explicit operator action); never kill
  unrelated Python or GPU processes by pattern.
- Long or remote jobs need budgets and confirmation in a future feature; v0.1 exposes smoke tests
  only.

## Architecture

- `src/microduck_studio/app.py` — FastAPI routes and lifecycle.
- `src/microduck_studio/protocol.py` — persistent robotd JSON-RPC and simulator-body client.
- `src/microduck_studio/discovery.py` — read-only Git and ONNX discovery.
- `src/microduck_studio/jobs.py` — allowlisted subprocess jobs and local logs.
- `src/microduck_studio/static/` — dependency-free responsive web UI.
- `tests/` — protocol, safety, command construction, and HTTP regression tests.

Keep the frontend build-free until its complexity genuinely needs a toolchain. A developer should
be able to clone, `uv sync`, and run one process.
