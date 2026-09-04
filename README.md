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

## Run

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
The launcher stops an earlier MuJoCo process before starting a new one. Closing the Viewer window
manually also stops MuJoCo, and it remains closed until the launcher is run again.

Run `./scripts/dev-stack.sh monitor` to open `robotctl`'s live visual monitor directly in the
current terminal. Press `q` to exit it; a terminal at least 110 columns wide also shows the 3D
robot view.

### Container layout

All project-owned container definitions live in this repository and are isolated by component:

```text
docker/
├── microduck/       # robotd + robotctl runtime image
├── microduck-rl/    # optional Linux/headless MuJoCo image
└── studio/          # Studio web image
compose.yaml         # robotd, Studio, robotctl, and headless MuJoCo services
```

The launcher invokes `docker compose up`, `down`, and `run`; it no longer starts individual
containers with `docker run`. Use `docker compose ps` and `docker compose logs -f robotd` for
container status and logs. The macOS Viewer remains a native process because Docker Desktop cannot
display that native GUI directly. The `mujoco-headless` Compose profile exists for Linux/CI use and
does not replace the Viewer in the default macOS stack.

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
