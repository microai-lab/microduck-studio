# Microduck Studio

English | [简体中文](README.zh-CN.md)

Microduck Studio is the missing local product between
[`microduck`](../microduck) and [`microduck_rl`](../microduck_rl): one browser UI for development
status, simulated-robot control, and safe RL smoke-test orchestration.

It does **not** reimplement the robot runtime or training environments. It speaks `robotd`'s
existing JSON-RPC protocol, reads the simulator body's existing TCP protocol, inspects both Git
repositories, and invokes the official `microduck_rl` CLI for training jobs.

## Project relationships

These are three independent Git projects, not projects nested inside one another:

```text
microduck_rl ──train and export ONNX policies──▶ microduck
                                                    ▲
                                                    │ JSON-RPC control and status
                                                    │
microduck-studio ──development, debugging, visualization, and orchestration
        │
        └──invokes microduck_rl training commands and reads training results
```

- `microduck` is the robot runtime. It owns `robotd`, hardware communication, safety control, and
  policy loading and execution.
- `microduck_rl` is the training project. It owns MuJoCo simulation, reinforcement-learning
  environments, reward functions, training, and ONNX export.
- `microduck-studio` is a supporting development tool. It is not part of either sibling and does
  not provide core runtime or training logic. It uses their existing interfaces to bring status,
  phone controls, training launches, and logs together in one web UI.

The directory layout therefore represents three independent repositories in one development
workspace:

```text
microduck-dev/          # Codex workspace only; not a Git repository
├── microduck/          # independent repository
├── microduck_rl/       # independent repository
└── microduck-studio/   # independent repository
```

Strictly speaking, Studio has a tooling-integration relationship with the other two projects, not
a code-ownership or containment relationship. Neither `microduck` nor `microduck_rl` depends on
Studio; development, training, and robot operation continue to work without it.

## Included in v0.1

- Phone-friendly drive controls with a persistent `robotd` connection and release-to-stop safety.
- Enable, stop, sit/stand, roulade, and kick actions.
- Live robot, simulator, repository branch, and dirty-worktree status.
- A model catalog that finds ONNX artifacts without loading them into the web process.
- An opt-in RL smoke-test launcher. It only builds the documented `uv run train ...` command and
  never accepts arbitrary shell input.
- Local job status and logs under `.studio-runtime/`.

## Run the development stack

### Prerequisites

- macOS with Docker Desktop running.
- `git`, `curl`, Python 3, and [`uv`](https://docs.astral.sh/uv/) available on the host.
- `microduck`, `microduck_rl`, and `microduck-studio` checked out as sibling directories.
- The RL environment prepared once with `uv sync` from `microduck_rl`.

The launcher currently uses the `upstream/sim-remote-io` revision of `microduck` for the
simulation backend, in an isolated runtime directory. It does not modify or switch the branch in
your working checkout.

### One-command startup

For the complete macOS development stack—MuJoCo Viewer, a simulation-enabled `robotd` with the
bundled policies, and Studio—start Docker Desktop and run:

```bash
cd ~/microduck-dev/microduck-studio
./scripts/dev-stack.sh
```

The launcher does not switch either sibling repository's branch. It prepares the upstream
simulation runtime in isolated local state, starts the native macOS MuJoCo Viewer, and uses Docker
Compose to build and start `robotd` and Studio in dependency order. It finishes with an end-to-end
control probe. Success means an HTTP move request travelled through `robotd` and its policy and
measurably moved the MuJoCo body; a merely reachable web page is not considered ready.

Use `./scripts/dev-stack.sh status` to check it and `./scripts/dev-stack.sh stop` to stop only the
services created by the launcher.

### Daily commands

Run these from `microduck-studio`:

| Goal | Command |
|---|---|
| Start or restart everything and run the control probe | `./scripts/dev-stack.sh` |
| Check Studio, `robotd`, and MuJoCo together | `./scripts/dev-stack.sh status` |
| Open the live `robotctl` visual monitor in this terminal | `./scripts/dev-stack.sh monitor` |
| Stop only this development stack | `./scripts/dev-stack.sh stop` |

Closing the MuJoCo window stops that simulator process. It is not automatically restarted; run
`./scripts/dev-stack.sh` again when you want the complete stack back.

### Open the `robotctl` visual monitor

Start the development stack first, then use the launcher from the same `microduck-studio`
directory:

```bash
./scripts/dev-stack.sh monitor
```

To invoke the same monitor directly through Compose, without the launcher wrapper:

```bash
docker compose run --rm --no-deps --build robotctl monitor
```

Both commands attach the monitor to the current terminal. They start a disposable `robotctl` tool
container connected to the development stack's existing runtime socket; they do **not** open or
enter a Docker shell. The wrapper form is preferred because it also checks that `robotd` is
running.

Monitor keys:

| Key | Action |
|---|---|
| `q`, `Esc`, or `Ctrl-C` | Exit the monitor |
| `[` / `]` or `Left` / `Right` | Rotate the 3D robot view |
| `d` | Show or hide the 3D robot view |

Use a terminal at least 110 columns wide for the 3D view. A narrower terminal continues to show
the live status and joint tables.

### Container layout

All project-owned container definitions live in this repository and are isolated by component:

```text
docker/
├── microduck/       # robotd + robotctl runtime image
├── microduck-rl/    # optional Linux/headless MuJoCo image
└── studio/          # Studio web image
compose.yaml         # robotd, Studio, robotctl, and headless MuJoCo services
```

The launcher invokes `docker compose up`, `down`, and `run`; it does not start individual
containers with `docker run`. The macOS Viewer remains a native process because Docker Desktop
cannot display that native GUI directly. The `mujoco-headless` Compose profile exists for Linux/CI
use and does not replace the Viewer in the default macOS stack.

Useful direct Compose commands:

```bash
docker compose ps
docker compose logs -f studio robotd
docker compose run --rm --no-deps robotctl health
```

The health command runs `robotctl` in a temporary tool container attached to the same runtime
socket. It does not enter the already-running `robotd` container. See
[Open the `robotctl` visual monitor](#open-the-robotctl-visual-monitor) for the interactive monitor.

### Run only the MuJoCo Viewer

Stop the complete stack first if it already owns port 7801, then run the simulator body directly
from the sibling RL repository:

```bash
./scripts/dev-stack.sh stop
cd ../microduck_rl
uv run mjpython -m mjlab_microduck.sim.body_server --keyframe HOME --port 7801
```

Close the Viewer window or press `Ctrl-C` in that terminal to stop it. This mode shows the model
and exposes the simulator TCP endpoint, but it does not start `robotd` or Studio.

### Connectivity checks

The startup command does more than wait for open ports: it sends a move through
`Web -> Studio -> robotd -> policy -> MuJoCo` and requires measurable simulator displacement. If
it prints `control probe passed`, the web control path was working at startup.

If a later click produces no movement:

1. Run `./scripts/dev-stack.sh status`; all three lines must be online/healthy.
2. In Studio, confirm the `robotd` and simulator cards are connected, then click **Enable RL**.
3. Inspect `docker compose logs -f studio robotd` and
   `.studio-runtime/dev-stack/mujoco.log` for a disconnect or policy refusal.
4. Run `./scripts/dev-stack.sh` again. It stops the processes owned by the previous launch, starts
   a clean stack, and repeats the end-to-end control probe before reporting ready.

To run Studio without the complete simulator control chain:

```bash
cd ~/microduck-dev/microduck-studio
uv sync --extra dev
cp .env.example .env
uv run microduck-studio
```

Open `http://127.0.0.1:8090` on the Mac, or `http://<mac-lan-ip>:8090` from a phone on the same
trusted Wi-Fi. Port 8090 avoids colliding with `microduck`'s `mediad` and the existing demo page
on port 8080.

The default `/run/robotd.sock` is appropriate when Studio runs beside `robotd`. In the Compose
stack, Studio and `robotd` share a named runtime volume containing that socket.

## Training jobs

Training launches are disabled by default. Enable them deliberately:

```bash
MICRODUCK_STUDIO_ENABLE_JOBS=true uv run microduck-studio
```

The first productized action is a 64-environment, 5-iteration smoke test, matching
`microduck_rl/AGENTS.md`. Long training runs are intentionally not exposed yet.

## Safety

Studio has no authentication in v0.1. Bind to `127.0.0.1` unless using a trusted LAN. Motion is a
continuous notification refreshed while a control is held; pointer release, page hide, connection
loss, and `robotd`'s deadman all stop it.

## License

Microduck Studio is licensed under the [MIT License](LICENSE).
