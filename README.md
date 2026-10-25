<p align="center">
  <img src="docs/images/microduck-studio-demo.jpg" alt="Microduck Studio controlling a robot in MuJoCo with live robotd telemetry" width="100%">
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
  AI coding ready:
  <a href="https://developers.openai.com/codex/">Codex</a> ·
  <a href="https://code.claude.com/docs/en/overview">Claude Code</a> ·
  <a href="https://cursor.com/docs/agent/overview">Cursor Agent</a> ·
  <a href="https://docs.github.com/en/copilot/concepts/agents/copilot-cli/about-copilot-cli">GitHub Copilot CLI</a>
</p>

<p align="center">
  <a href="#start-with-an-ai-coding-agent">AI startup</a> ·
  <a href="#quick-start">Quick start</a> ·
  <a href="#robotctl-monitor">Monitor</a> ·
  <a href="#how-the-projects-fit-together">Architecture</a> ·
  <a href="#when-the-page-does-not-move-the-robot">Troubleshooting</a>
</p>

Microduck Studio brings Microduck simulation, live monitoring, and robot controls into one
browser workspace. It connects the existing
[`microduck`](https://github.com/pollen-robotics/microduck) runtime and
[`microduck_rl`](https://github.com/pollen-robotics/microduck_rl) simulator.

## Start with an AI coding agent

Open the `microduck-dev` workspace in a local AI coding agent with repository, terminal, and
Docker access, then use this prompt:

```text
Start all Microduck Studio services. First read AGENTS.md and microduck-studio/README.md. Check the
three sibling repositories, Docker, uv, and ports 7801 and 8090. Then run
./scripts/dev-stack.sh from microduck-studio. Wait for "contract probe passed" before reporting the
Studio URL and the status of Studio, robotd, tofd, and MuJoCo. Do not start a training job, and do not
switch or modify the working branches of the sibling repositories.
```

Use a local session on the development machine so the agent can reach its Docker services.

## Quick start

### Requirements

- Docker with Docker Compose
- `git` and `curl`
- Python 3 and [`uv`](https://docs.astral.sh/uv/)
- macOS for the default native mode; Linux users should select Docker mode below

The one-command stack uses Docker for `robotd`, `tofd`, and Studio. On macOS, Docker Desktop or
another compatible Docker runtime must already be running.

### 1. Download the three repositories

Keep the repositories beside one another:

```text
microduck-dev/
├── microduck/          # robot runtime
├── microduck_rl/       # MuJoCo simulation and training
└── microduck-studio/   # browser workspace and service startup
```

```bash
mkdir -p ~/microduck-dev
cd ~/microduck-dev

git clone https://github.com/microai-lab/microduck.git
git clone --branch develop https://github.com/microai-lab/microduck_rl.git
git clone https://github.com/microai-lab/microduck-studio.git
```

These development forks include the features used by Studio. If the repositories already exist,
check their directory layout and keep `microduck` on a compatible `main` and `microduck_rl` on a
compatible `develop`. The launcher does not switch their working branches.

### 2. Prepare the native MuJoCo environment

For native macOS background rendering or the desktop Viewer:

```bash
cd ~/microduck-dev/microduck_rl
uv sync --extra visualization
```

Docker mode prepares its rendering environment inside the container instead.

### 3. Start and verify the services

```bash
cd ~/microduck-dev/microduck-studio
./scripts/dev-stack.sh
```

On Linux or for a fully containerized environment, use
`./scripts/dev-stack.sh --sim-mode docker --gpu none` instead.

Open **http://127.0.0.1:8090**. In the default native mode, MuJoCo runs in the macOS background
and the desktop Viewer stays closed. The first launch downloads the official v8 policies and
builds the containers. Wait for the startup check to report:

```text
contract probe passed: runtime source, policies, subscription, movement ... m, stop, disconnect
```

The startup check includes a brief simulated movement and stop test. Add `--skip-control-probe`
when you want to start without that movement test.

## Capabilities

| Feature | What you can do |
|---|---|
| Robot control | Move forward/backward/sideways, turn, enable/stop RL, and run sit/stand, roulade, or kick actions. |
| Live MuJoCo video | Switch between the world view and the robot's simulated head-camera view. |
| Camera controls | Drag to rotate, use the wheel or trackpad to zoom, and double-click to reset. |
| Image quality | Choose Smooth, Clear, or Lossless images up to 1920×1080; view the actual FPS. |
| Scene selection | Select and apply a scene, restarting the simulator and robot service. |
| Live robot monitor | Inspect policy, commands, joints, IMU, 8×8 ToF, odometry, safety state, and loop rate. |
| Service controls | Check connections and start or restart `robotd` and MuJoCo. |
| Language | Switch the page between Chinese and English. |
| Runtime modes | Use native macOS background rendering, fully containerized CPU rendering, or Linux GPU options. |

Hold a movement button to move and release it to stop. Directions follow the duck's orientation.
Hiding or disconnecting the page also requests a stop. Movement quality, including sideways
travel, depends on the selected policy.

The monitor shows missing sensor values as `—` and displays runtime refusal or disconnection
messages. A picked-up robot is marked paused.

## Daily workflow

Run these commands from `microduck-studio`:

| Goal | Command |
|---|---|
| Start or cleanly restart and verify the stack | `./scripts/dev-stack.sh` |
| Check all services | `./scripts/dev-stack.sh status` |
| Stop the stack | `./scripts/dev-stack.sh stop` |
| Open the terminal monitor | `./scripts/dev-stack.sh monitor` |
| Start with a particular scene | `./scripts/dev-stack.sh --scene scene_vslam.xml` |
| Open the desktop MuJoCo Viewer | `./scripts/dev-stack.sh --viewer` |
| Start without the movement test | `./scripts/dev-stack.sh --skip-control-probe` |
| Stop native MuJoCo after the last page closes | `./scripts/dev-stack.sh --stop-on-browser-close` |

The `robotd` and MuJoCo cards show **Start** or **Restart** according to their current status.
Restarting MuJoCo also reconnects the robot service. If Studio itself is unavailable, restart it
from the terminal with `./scripts/dev-stack.sh`.

Only `--viewer` opens a desktop window. Closing that window stops MuJoCo. The default background
mode continues running until `./scripts/dev-stack.sh stop`; `--headless` explicitly selects the
same background behavior.

In native background mode, `--stop-on-browser-close` stops only MuJoCo after the last scene page
has been disconnected for 10 seconds. Refreshing or reconnecting during that grace period cancels
the shutdown.

### Rendering modes and GPU options

| Situation | Command | Result |
|---|---|---|
| macOS native rendering | `./scripts/dev-stack.sh` | Background MuJoCo without a desktop Viewer. |
| Fully containerized CPU mode | `./scripts/dev-stack.sh --sim-mode docker --gpu none` | MuJoCo, robotd, and Studio run in Docker; software-rendered video may be slower. |
| Linux DRI GPU interface | `./scripts/dev-stack.sh --sim-mode docker --gpu dri` | Uses an available host `/dev/dri` GPU; requires compatible drivers. |
| Linux NVIDIA GPU interface | `./scripts/dev-stack.sh --sim-mode docker --gpu nvidia` | Uses the host NVIDIA GPU; requires NVIDIA Container Toolkit. |

GPU selection is explicit in the startup arguments. These Linux GPU interfaces are configurable;
performance must be checked on the target host. Docker Desktop on macOS cannot use these Linux GPU
paths. `--gpu` applies only to Docker mode; `--viewer` and `--stop-on-browser-close` are native options.

XML physics remains the default. To try the optional BAM/backlash scene, use
`./scripts/dev-stack.sh --actuator-model bam --scene scene_velstand.xml`; this selection is available
with either native or Docker rendering.

### Scene selection

Choose a scene and click **Apply** to restart MuJoCo with it. Click **Scene** beside the selector
to copy the selected `.xml` filename.

Available scenes depend on the local RL repository.

| File | Use |
|---|---|
| `scene.xml` | Flat-ground simulation. |
| `scene_allcollisions.xml` | Robot self-collision and contact inspection. |
| `scene_apartment.xml` | Furnished indoor scene. |
| `scene_backlash.xml` | Simulated servo gear play. |
| `scene_ball.xml` | Kicks and ball interactions. |
| `scene_rollers.xml` | Passive foot-roller simulation. |
| `scene_vslam.xml` | Room with visual landmarks. |
| `scene_walk.xml` | Walking robot on flat ground. |
| `scene_walk_backlash.xml` | Walking model with gear play. |
| `scene_velstand.xml` | Full-collision/backlash scene for the optional BAM mode. |

### Image quality and language

Use the language switch at the top of the page for Chinese or English. The scene card provides
these image profiles:

| Profile | Maximum frame size | Suggested use |
|---|---:|---|
| Smooth | 960×540 | Lower bandwidth and latency. |
| Clear (default) | 1920×1080 | Normal desktop viewing. |
| Lossless | 1920×1080 | Static detail inspection; frame rate may be lower. |

The scene shows the actual received video FPS, image resolution, and simulation time. Image
quality, scene complexity, and host load affect frame rate. The default startup target is
1280×720 at 24 FPS; this is a requested target, rather than a fixed output rate.

## `robotctl monitor`

Open the live visual monitor in the current terminal:

```bash
./scripts/dev-stack.sh monitor
```

Or run it directly with Compose:

```bash
docker compose run --rm --no-deps --build robotctl monitor
```

The stack must already be running.

| Key | Action |
|---|---|
| `q`, `Esc`, or `Ctrl-C` | Exit |
| `[` / `]` or `Left` / `Right` | Rotate the 3D robot view |
| `d` | Show or hide the 3D robot view |

The 3D view needs a terminal at least 110 columns wide; status and joint tables work in a
narrower terminal.

## How the projects fit together

- **microduck** provides the robot runtime, policies, and safety controls.
- **microduck_rl** provides MuJoCo simulation and training.
- **microduck-studio** provides the browser controls, monitoring, and service startup.

## When the page does not move the robot

1. Run `./scripts/dev-stack.sh status` and confirm Studio, `robotd`, and MuJoCo are ready.
2. Click **Enable RL**, then try holding a movement control.
3. Use the `robotd` or MuJoCo card's **Start/Restart** action if either service is disconnected.
4. If the page is unavailable, run `./scripts/dev-stack.sh` again and wait for the startup check.

| Problem | Recovery |
|---|---|
| Waiting for MuJoCo frames | Check service status and use MuJoCo **Start/Restart**. |
| Choppy Docker video on macOS | Use native mode or select the **Smooth** image profile. |
| Unexpected desktop Viewer | Stop the stack and restart without `--viewer`. |
| Rendering dependency missing in native mode | Run `uv sync --extra visualization` in `microduck_rl`. |
| Web Start/Restart buttons unavailable | Start the stack with `./scripts/dev-stack.sh`; the buttons are available for launcher-managed services. |

For service diagnostics:

```bash
docker compose ps
docker compose logs -f studio robotd tofd
docker compose run --rm --no-deps robotctl health
```

## Run components separately

<details>
<summary><strong>Run only MuJoCo Viewer</strong></summary>

Stop the stack first if it owns port 7801, then run:

```bash
./scripts/dev-stack.sh stop
cd ../microduck_rl
uv run --extra visualization mjpython -m mjlab_microduck.sim.body_server --keyframe HOME --port 7801 --render
```

Close the Viewer or press `Ctrl-C` to stop it.

</details>

<details>
<summary><strong>Run only Studio</strong></summary>

```bash
uv sync --extra dev
cp .env.example .env
uv run microduck-studio
```

This starts only the Web service on port 8090.

</details>

## Training smoke tests

Training jobs are disabled by default. For the optional 64-environment, 5-iteration smoke test,
run Studio directly on the host with:

```bash
MICRODUCK_STUDIO_ENABLE_JOBS=true uv run microduck-studio
```

Then use the training smoke-test card on the page.

## Development

```bash
uv sync --extra dev
uv run pytest
uv run ruff check .
uv run ruff format --check .
node --test tests/test_frontend.mjs
```

## Safety

Studio has no authentication. Keep it on `127.0.0.1` or a trusted LAN. Robot safety and motor
control remain the responsibility of `robotd`.

## License

[MIT](LICENSE)
