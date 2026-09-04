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

### Requirements

- Docker with Docker Compose
- `git` and `curl`
- Python 3 and [`uv`](https://docs.astral.sh/uv/)

> The individual projects can run directly on the host and do not inherently require Docker.
> The `dev-stack.sh` launcher does require Docker because it isolates the `robotd` and Studio Web
> build and runtime environments. On macOS, Docker Desktop is one option; any compatible Docker
> runtime is suitable.

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

For a fresh workspace, clone the repositories used by this development setup:

```bash
mkdir -p ~/microduck-dev
cd ~/microduck-dev

git clone https://github.com/ttfont/microduck.git
git clone https://github.com/ttfont/microduck_rl.git
git clone https://github.com/microai-lab/microduck-studio.git
```

Download links: [microduck](https://github.com/ttfont/microduck),
[microduck_rl](https://github.com/ttfont/microduck_rl), and
[microduck-studio](https://github.com/microai-lab/microduck-studio). The first two are development
forks of the [official runtime](https://github.com/pollen-robotics/microduck) and
[official RL repository](https://github.com/pollen-robotics/microduck_rl).

Existing repositories do not need to be cloned again; their directory layout only needs to match
the structure above.

### 2. Prepare the simulation backend

Full MuJoCo integration requires the official `microduck` `sim-remote-io` branch. The regular
runtime branch in the cloned development fork does not provide the `robotd --sim` backend; this
branch supplies the remote `RobotIo` implementation that connects `robotd` to the MuJoCo body
service at TCP `127.0.0.1:7801` by default.

Fetch it once from the workspace directory:

```bash
git -C microduck remote add upstream https://github.com/pollen-robotics/microduck.git
git -C microduck fetch upstream sim-remote-io
```

Run `remote add` only once; if `upstream` already exists, run only the second command. These
commands add the repository address and download the branch; they do not switch the current
`microduck` branch. The launcher reads `upstream/sim-remote-io` and extracts it into isolated Studio
state. If it was not fetched in advance, the launcher can also download it automatically into
`.studio-runtime/dev-stack/sim-runtime.git` without changing the sibling repository's branch or
working tree. See [How the projects fit together](#how-the-projects-fit-together) for the role of
`robotd --sim` in the full control path.

### 3. Prepare the RL environment

The native macOS Viewer runs from the `microduck_rl` virtual environment:

```bash
cd ~/microduck-dev/microduck_rl
uv sync
```

### 4. Start and verify everything

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
> `sim-remote-io` runtime revision into isolated Studio state.

## Capabilities

| Area | Included |
|---|---|
| Web control | Phone-friendly movement, enable/stop, sit/stand, roulade, and kicks |
| Live visibility | Runtime, simulator, repository, job, and connection status, plus model discovery |
| Safe orchestration | Docker Compose lifecycle, an end-to-end control probe, and allowlisted RL smoke tests |

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

The workspace contains three independent Git repositories with one-way ownership boundaries:

```text
Browser
   │ HTTP / JSON API
   ▼
Microduck Studio
   │ JSON-RPC / NDJSON over a Unix socket
   ▼
robotd --sim ◀──────── policy.onnx + manifest ─────── microduck_rl export
   │
   │ TCP / NDJSON :7801
   ▼
duck-body / MuJoCo ────────────────────────────────── microduck_rl
```

- **microduck** owns `robotd`, hardware I/O, safety, policy loading, and motor authority.
- **microduck_rl** owns MuJoCo models, environments, rewards, training, and ONNX export.
- **microduck-studio** owns the browser experience, status aggregation, and allowlisted local
  orchestration.

Neither runtime nor training depends on Studio. Studio consumes their public protocols and tools.

### What `robotd --sim` does

`robotd --sim` is a startup mode, not a separate runtime environment. It runs the complete
`robotd` while replacing physical motor and sensor I/O with a remote simulation adapter:

- Joint and sensor state comes from the `microduck_rl` `duck-body` service.
- Control targets are sent back to MuJoCo over TCP.
- The control loop, policy inference, safety checks, and JSON-RPC interface remain unchanged.
- Studio and `robotctl` therefore use the same control interface for simulation and hardware.

The simulation backend does not start the Viewer, run training, or bypass `robotd` safety logic.
Docker provides process and dependency isolation for the one-command workflow; it is separate from
the `--sim` mode itself.

## Containers and processes

### Compose layout

All project-owned container definitions live here and are separated by component:

```text
docker/
├── microduck/       # robotd + robotctl runtime image
├── microduck-rl/    # optional Linux/headless MuJoCo image
└── studio/          # Studio web image
compose.yaml         # robotd, Studio, robotctl, and headless MuJoCo services
```

The one-command launcher uses `docker compose up`, `down`, and `run` to isolate `robotd` and Studio
Web, so Docker must be running when that script is used. Docker is not mandatory when the
components are run separately. Containers cannot display this native macOS GUI directly, so the
default MuJoCo Viewer remains a host process. The `mujoco-headless` profile is for Linux/CI and does
not replace the default macOS Viewer.

### Diagnostics

```bash
docker compose ps
docker compose logs -f studio robotd
docker compose run --rm --no-deps robotctl health
```

The final command runs a temporary tool container; it does not open a Docker shell.

### Run components separately

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

Studio v0.1 has no authentication. Bind it to `127.0.0.1`; non-loopback binding should be limited
to trusted LANs. Studio sends intents only; `robotd` remains the sole safety and motor authority.

## License

[MIT](LICENSE)
