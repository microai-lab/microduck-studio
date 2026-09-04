<p align="center">
  <img src="docs/images/microduck-studio-hero-placeholder.png" alt="Microduck Studio development workspace preview" width="100%">
</p>

<h1 align="center">Microduck Studio</h1>

<p align="center">A local control room for developing, simulating, and validating Microduck.</p>

<p align="center">
  <a href="README.md">English</a> · <a href="README.zh-CN.md">简体中文</a>
</p>

<p align="center">
  <img alt="Python 3.12+" src="https://img.shields.io/badge/Python-3.12%2B-3776AB?logo=python&logoColor=white">
  <img alt="FastAPI" src="https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white">
  <img alt="Docker Compose" src="https://img.shields.io/badge/Docker_Compose-2496ED?logo=docker&logoColor=white">
  <a href="LICENSE"><img alt="MIT License" src="https://img.shields.io/badge/License-MIT-f2c94c"></a>
</p>

<p align="center">
  <a href="#quick-start">Quick start</a> ·
  <a href="#robotctl-monitor">Monitor</a> ·
  <a href="#how-the-projects-fit-together">Architecture</a> ·
  <a href="#when-the-page-does-not-move-the-robot">Troubleshooting</a>
</p>

<p align="center">
  <sub>Concept preview — this placeholder will later be replaced by one real composite of the Web UI, <code>robotctl monitor</code>, and MuJoCo.</sub>
</p>

Microduck Studio connects the existing
[`microduck`](https://github.com/pollen-robotics/microduck) runtime and
[`microduck_rl`](https://github.com/pollen-robotics/microduck_rl) simulation/training project in
one browser-based development workflow. It presents status and safe control; it does not duplicate
robot safety, policy inference, simulator physics, or training logic.

## Quick start

The complete macOS stack needs Docker Desktop, `git`, `curl`, Python 3, and
[`uv`](https://docs.astral.sh/uv/).

### 1. Download the three repositories

Studio is not standalone: `microduck` supplies `robotd` and its policies, while `microduck_rl`
supplies the MuJoCo body and Viewer. All three repositories must be sibling directories under one
workspace:

```text
microduck-dev/          # workspace only; not a Git repository
├── microduck/          # robotd, robotctl, policies, and runtime protocol
├── microduck_rl/       # MuJoCo body, Viewer, environments, and training
└── microduck-studio/   # Web UI and development-stack orchestration
```

For a fresh workspace, clone the repositories used by this development setup and register the
official runtime repository as `upstream`:

```bash
mkdir -p ~/microduck-dev
cd ~/microduck-dev

git clone https://github.com/ttfont/microduck.git
git clone https://github.com/ttfont/microduck_rl.git
git clone https://github.com/microai-lab/microduck-studio.git

git -C microduck remote add upstream https://github.com/pollen-robotics/microduck.git
git -C microduck fetch upstream sim-remote-io
```

Download links: [microduck](https://github.com/ttfont/microduck),
[microduck_rl](https://github.com/ttfont/microduck_rl), and
[microduck-studio](https://github.com/microai-lab/microduck-studio). The first two are development
forks of the [official runtime](https://github.com/pollen-robotics/microduck) and
[official RL repository](https://github.com/pollen-robotics/microduck_rl).

If the repositories already exist, do not clone them again. Confirm the directory layout above and
make sure `git -C microduck rev-parse upstream/sim-remote-io` succeeds.

### 2. Prepare the RL environment

The native macOS Viewer runs from the `microduck_rl` virtual environment:

```bash
cd ~/microduck-dev/microduck_rl
uv sync
```

### 3. Start and verify everything

```bash
cd ~/microduck-dev/microduck-studio
./scripts/dev-stack.sh
```

Open **http://127.0.0.1:8090**. The command starts the native MuJoCo Viewer, a simulation-enabled
`robotd`, and Studio, then proves the complete control path by moving the simulated robot. Do not
treat a reachable page alone as ready; wait for:

```text
control probe passed: MuJoCo moved ... m
```

> The launcher never switches a sibling repository's working branch. It extracts the required
> `upstream/sim-remote-io` runtime revision into isolated local state.

## What you get

| Web control | Live visibility | Safe orchestration |
|---|---|---|
| Phone-friendly movement, enable/stop, sit/stand, roulade, and kicks | Runtime, simulator, repository, job, and connection status, plus model discovery | Docker Compose lifecycle, an end-to-end control probe, and allowlisted RL smoke tests |

Motion uses one persistent `robotd` connection. Releasing a control, hiding the page, disconnecting,
or shutting Studio down sends `robot.stop`; `robotd` remains the final safety and motor authority.

## Daily workflow

Run these commands from `microduck-studio`:

| Goal | Command |
|---|---|
| Start or cleanly restart everything and verify control | `./scripts/dev-stack.sh` |
| Check Studio, `robotd`, and MuJoCo together | `./scripts/dev-stack.sh status` |
| Open the live terminal monitor | `./scripts/dev-stack.sh monitor` |
| Stop only this development stack | `./scripts/dev-stack.sh stop` |

Closing the MuJoCo window stops the simulator and does not trigger an automatic restart. Run the
start command again to restore the complete stack.

## `robotctl monitor`

The recommended command opens the live visual monitor directly in the current terminal:

```bash
./scripts/dev-stack.sh monitor
```

The direct Compose equivalent is:

```bash
docker compose run --rm --no-deps --build robotctl monitor
```

Both launch a disposable `robotctl` tool container attached to the existing runtime socket. They do
not enter a Docker shell or the running `robotd` container. The wrapper is preferred because it
first verifies that `robotd` is running.

| Key | Action |
|---|---|
| `q`, `Esc`, or `Ctrl-C` | Exit |
| `[` / `]` or `Left` / `Right` | Rotate the 3D robot view |
| `d` | Show or hide the 3D robot view |

The 3D view needs a terminal at least 110 columns wide. Status and joint tables still work in a
narrower terminal.

## How the projects fit together

The workspace contains three independent Git repositories:

```text
microduck_rl
  MuJoCo body + training + ONNX export
       │ TCP/NDJSON :7801               policy.onnx + manifest
       ▼                                      │
microduck simulator body ◀── robotd ──────────┘
                              ▲
                              │ JSON-RPC/NDJSON over a Unix socket
                              │
                         Microduck Studio ◀── Browser
```

- **microduck** owns `robotd`, hardware I/O, safety, policy loading, and motor authority.
- **microduck_rl** owns MuJoCo models, environments, rewards, training, and ONNX export.
- **microduck-studio** owns the browser experience, status aggregation, and allowlisted local
  orchestration.

Neither runtime nor training depends on Studio. Studio consumes their public protocols and tools.

## Containers and processes

All project-owned container definitions live here and are separated by component:

```text
docker/
├── microduck/       # robotd + robotctl runtime image
├── microduck-rl/    # optional Linux/headless MuJoCo image
└── studio/          # Studio web image
compose.yaml         # robotd, Studio, robotctl, and headless MuJoCo services
```

The launcher uses `docker compose up`, `down`, and `run`. On macOS, MuJoCo Viewer remains a
native host process because Docker Desktop cannot display that GUI directly. The
`mujoco-headless` profile is for Linux/CI and does not replace the default macOS Viewer.

Useful diagnostics:

```bash
docker compose ps
docker compose logs -f studio robotd
docker compose run --rm --no-deps robotctl health
```

The final command runs a temporary tool container; it does not open a Docker shell.

<details>
<summary><strong>Run only MuJoCo Viewer</strong></summary>

Stop the full stack first if it owns port 7801, then start the simulator body from the sibling RL
repository:

```bash
./scripts/dev-stack.sh stop
cd ../microduck_rl
uv run mjpython -m mjlab_microduck.sim.body_server --keyframe HOME --port 7801
```

Close the Viewer or press `Ctrl-C` to stop it. This mode exposes the simulator TCP endpoint but
does not start `robotd` or Studio.

</details>

<details>
<summary><strong>Run only Studio</strong></summary>

```bash
uv sync --extra dev
cp .env.example .env
uv run microduck-studio
```

This starts only the Web service. The default robot socket is `/run/robotd.sock`; the Compose
stack instead shares that socket through its named runtime volume. Port 8090 avoids `microduck`
services that commonly use port 8080.

</details>

## When the page does not move the robot

1. Run `./scripts/dev-stack.sh status`; Studio, `robotd`, and MuJoCo must all be online/healthy.
2. Confirm the `robotd` and simulator cards are connected, then click **Enable RL**.
3. Check `docker compose logs -f studio robotd` and
   `.studio-runtime/dev-stack/mujoco.log` for disconnects or policy refusals.
4. Run `./scripts/dev-stack.sh` again. It stops processes owned by the prior launch and repeats the
   end-to-end control probe before reporting ready.

## Training smoke tests

Training jobs are disabled by default. When running Studio directly on the host, enable them with:

```bash
MICRODUCK_STUDIO_ENABLE_JOBS=true uv run microduck-studio
```

Studio exposes only the documented 64-environment, 5-iteration smoke test. It constructs an
allowlisted `uv run train ...` argument list with `shell=False`; arbitrary shell commands and
long training runs are intentionally unavailable.

## Development

```bash
uv sync --extra dev
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

## Safety

Studio v0.1 has no authentication. Bind it to `127.0.0.1` unless you are on a trusted LAN. Studio
sends intents only; `robotd` remains the sole safety and motor authority.

## License

[MIT](LICENSE)
