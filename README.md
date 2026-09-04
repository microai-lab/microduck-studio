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

```bash
cd ~/Documents/coding/gh/microduck-dev/microduck-studio
uv sync --extra dev
cp .env.example .env
uv run microduck-studio
```

Open `http://127.0.0.1:8090` on the Mac, or `http://<mac-lan-ip>:8090` from a phone on the same
trusted Wi-Fi. Port 8090 avoids colliding with `microduck`'s `mediad` and the existing demo page
on port 8080.

The default `/run/robotd.sock` is appropriate when Studio runs beside `robotd`. For the current
Docker demo, bind-mount or forward the socket and set `MICRODUCK_ROBOTD_SOCKET` to that path.

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
