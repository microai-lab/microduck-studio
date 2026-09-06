#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
STUDIO_REPO=$(dirname "$SCRIPT_DIR")
WORKSPACE=$(dirname "$STUDIO_REPO")
MICRODUCK_REPO=${MICRODUCK_REPO:-"$WORKSPACE/microduck"}
MICRODUCK_RL_REPO=${MICRODUCK_RL_REPO:-"$WORKSPACE/microduck_rl"}
RUNTIME_DIR=${MICRODUCK_STUDIO_RUNTIME:-"$STUDIO_REPO/.studio-runtime/dev-stack"}
COMPOSE_FILE="$STUDIO_REPO/compose.yaml"
GPU_DRI_FILE="$STUDIO_REPO/compose.gpu-dri.yaml"
GPU_NVIDIA_FILE="$STUDIO_REPO/compose.gpu-nvidia.yaml"

BODY_PORT=${MICRODUCK_BODY_PORT:-7801}
STUDIO_PORT=${MICRODUCK_STUDIO_PORT:-8090}
# Rendering/isolation choices must remain visible in shell history. The no-argument default is the
# authoritative native MuJoCo path; Docker and GPU passthrough are selected only with CLI flags.
SIM_MODE=native
GPU=none
RENDER_WIDTH=${MICRODUCK_RENDER_WIDTH:-1280}
RENDER_HEIGHT=${MICRODUCK_RENDER_HEIGHT:-720}
RENDER_FPS=${MICRODUCK_RENDER_FPS:-24}
RENDER_QUALITY=${MICRODUCK_RENDER_QUALITY:-95}
# Native MuJoCo is a background service by default. The browser receives the same authoritative
# frames; opening the desktop Viewer is an explicit development choice.
HEADLESS=true
STOP_ON_BROWSER_CLOSE=false
CONTROL_PROBE=true
SIM_REF=${MICRODUCK_SIM_REF:-sim-remote-io}
SIM_REPO_URL=${MICRODUCK_SIM_REPO_URL:-https://github.com/pollen-robotics/microduck.git}
RUST_IMAGE=${MICRODUCK_RUST_IMAGE:-rust:1.89-bookworm}
ORT_VERSION=${MICRODUCK_ORT_VERSION:-1.28.0}
ROBOTD_CONTAINER=microduck-studio-robotd
RPC_CONTAINER=microduck-studio-rpc-bridge
WEB_CONTAINER=microduck-studio-web
RUNTIME_VOLUME=microduck-studio-runtime
HOST_SOCKET=/tmp/microduck-studio-robotd.sock
HOST_BRIDGE_SCRIPT=/tmp/microduck-studio-rpc-bridge.py
HOST_STUDIO_SCRIPT=/tmp/microduck-studio-run-web.sh
BODY_PID_FILE="$RUNTIME_DIR/mujoco.pid"
BODY_PLIST="$RUNTIME_DIR/mujoco.plist"
SERVICE_MANAGER_PID_FILE="$RUNTIME_DIR/service-manager.pid"
SERVICE_MANAGER_PLIST="$RUNTIME_DIR/service-manager.plist"
SERVICE_MANAGER_DIR="$RUNTIME_DIR/services"

BODY_LABEL=com.microduck.mujoco.viewer
SOCKET_LABEL=com.microduck.studio.socketbridge
WEB_LABEL=com.microduck.studio.web
SERVICE_MANAGER_LABEL=com.microduck.studio.service-manager
DOMAIN="gui/$(id -u)"

say() { printf '\033[36m==\033[0m %s\n' "$*"; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }
need() { command -v "$1" >/dev/null 2>&1 || die "missing command: $1"; }

label_exists() {
    command -v launchctl >/dev/null 2>&1 || return 1
    launchctl print "$DOMAIN/$1" >/dev/null 2>&1
}

remove_label() {
    label_exists "$1" && launchctl remove "$1" || true
}

remove_container() {
    docker container inspect "$1" >/dev/null 2>&1 && docker rm -f "$1" >/dev/null || true
}

compose() {
    case "$GPU" in
        none) docker compose --project-directory "$STUDIO_REPO" -f "$COMPOSE_FILE" "$@" ;;
        dri) docker compose --project-directory "$STUDIO_REPO" -f "$COMPOSE_FILE" -f "$GPU_DRI_FILE" "$@" ;;
        nvidia) docker compose --project-directory "$STUDIO_REPO" -f "$COMPOSE_FILE" -f "$GPU_NVIDIA_FILE" "$@" ;;
    esac
}

ensure_runtime_volume() {
    docker volume inspect "$RUNTIME_VOLUME" >/dev/null 2>&1 ||
        docker volume create "$RUNTIME_VOLUME" >/dev/null
}

body_pid() {
    [ -f "$BODY_PID_FILE" ] || return 1
    pid=$(sed -n '1p' "$BODY_PID_FILE")
    case "$pid" in
        ''|*[!0-9]*) return 1 ;;
    esac
    command=$(ps -p "$pid" -o command= 2>/dev/null) || return 1
    case "$command" in
        *mjlab_microduck.sim.body_server*) printf '%s\n' "$pid" ;;
        *) return 1 ;;
    esac
}

stop_body() {
    # Remove jobs created by older launcher versions before switching to PID ownership.
    remove_label "$BODY_LABEL"
    pid=$(body_pid) || pid=
    if [ -n "$pid" ]; then
        kill "$pid" 2>/dev/null || true
        attempts=0
        while kill -0 "$pid" 2>/dev/null && [ "$attempts" -lt 40 ]; do
            attempts=$((attempts + 1))
            sleep 0.1
        done
        if kill -0 "$pid" 2>/dev/null; then
            kill -9 "$pid" 2>/dev/null || true
        fi
    fi
    rm -f "$BODY_PID_FILE"
    rm -f "$BODY_PLIST"
}

stop_service_manager() {
    remove_label "$SERVICE_MANAGER_LABEL"
    if [ -f "$SERVICE_MANAGER_PID_FILE" ]; then
        pid=$(sed -n '1p' "$SERVICE_MANAGER_PID_FILE")
        case "$pid" in
            ''|*[!0-9]*) ;;
            *) kill "$pid" 2>/dev/null || true ;;
        esac
    fi
    rm -f "$SERVICE_MANAGER_PID_FILE" "$SERVICE_MANAGER_PLIST"
    rm -f "$SERVICE_MANAGER_DIR/manager.json"
}

stop_stack() {
    say "stopping Studio development stack"
    # Remove host jobs and containers created by launcher versions before Compose.
    remove_label "$WEB_LABEL"
    remove_label "$SOCKET_LABEL"
    stop_service_manager
    stop_body
    # Include the optional simulator profile so switching docker -> native cannot leave its
    # published body port behind and accidentally connect native robotd to the old container.
    compose --profile headless down --remove-orphans >/dev/null 2>&1 || true
    remove_container "$RPC_CONTAINER"
    remove_container "$ROBOTD_CONTAINER"
    remove_container "$WEB_CONTAINER"
    rm -f "$HOST_SOCKET" "$HOST_BRIDGE_SCRIPT" "$HOST_STUDIO_SCRIPT"
}

start_service_manager() {
    say "starting restricted host service manager"
    python_bin=$(command -v python3)
    docker_bin=$(command -v docker)
    launchctl_bin=$(command -v launchctl || printf launchctl)
    mkdir -p "$SERVICE_MANAGER_DIR"
    if [ "$(uname -s)" = Darwin ]; then
        python3 -c '
import plistlib, sys

path, label, python, script, directory, mode, domain, body_label, body_port, docker, launchctl, log = sys.argv[1:]
config = {
    "Label": label,
    "ProgramArguments": [
        python, script,
        "--directory", directory,
        "--mode", mode,
        "--domain", domain,
        "--body-label", body_label,
        "--body-port", body_port,
        "--docker", docker,
        "--launchctl", launchctl,
    ],
    "RunAtLoad": True,
    "KeepAlive": True,
    "StandardOutPath": log,
    "StandardErrorPath": log,
}
with open(path, "wb") as output:
    plistlib.dump(config, output)
' "$SERVICE_MANAGER_PLIST" "$SERVICE_MANAGER_LABEL" "$python_bin" \
            "$STUDIO_REPO/scripts/service-manager.py" "$SERVICE_MANAGER_DIR" "$SIM_MODE" \
            "$DOMAIN" "$BODY_LABEL" "$BODY_PORT" "$docker_bin" "$launchctl_bin" \
            "$RUNTIME_DIR/service-manager.log"
        launchctl bootstrap "$DOMAIN" "$SERVICE_MANAGER_PLIST"
    else
        "$python_bin" "$STUDIO_REPO/scripts/service-manager.py" \
            --directory "$SERVICE_MANAGER_DIR" --mode "$SIM_MODE" --domain "$DOMAIN" \
            --body-label "$BODY_LABEL" --body-port "$BODY_PORT" --docker "$docker_bin" \
            --launchctl "$launchctl_bin" \
            >>"$RUNTIME_DIR/service-manager.log" 2>&1 &
        printf '%s\n' "$!" >"$SERVICE_MANAGER_PID_FILE"
    fi
    attempts=0
    while [ ! -f "$SERVICE_MANAGER_DIR/manager.json" ] && [ "$attempts" -lt 40 ]; do
        attempts=$((attempts + 1))
        sleep 0.1
    done
    [ -f "$SERVICE_MANAGER_DIR/manager.json" ] || die "host service manager did not start"
}

wait_tcp() {
    host=$1
    port=$2
    name=$3
    attempts=0
    while [ "$attempts" -lt 120 ]; do
        if python3 -c 'import socket,sys;s=socket.socket();s.settimeout(.2);sys.exit(s.connect_ex((sys.argv[1],int(sys.argv[2]))))' "$host" "$port"; then
            return 0
        fi
        attempts=$((attempts + 1))
        sleep 0.25
    done
    die "$name did not listen on $host:$port"
}

ensure_sim_source() {
    SIM_ARCHIVE_REPO=$MICRODUCK_REPO
    commit=
    candidates=$SIM_REF
    case "$SIM_REF" in
        */*) ;;
        *) candidates="$SIM_REF upstream/$SIM_REF origin/$SIM_REF" ;;
    esac
    for candidate in $candidates; do
        if resolved=$(git -C "$MICRODUCK_REPO" rev-parse "$candidate^{commit}" 2>/dev/null); then
            commit=$resolved
            break
        fi
    done

    if [ -z "$commit" ]; then
        SIM_ARCHIVE_REPO="$RUNTIME_DIR/sim-runtime.git"
        if [ ! -d "$SIM_ARCHIVE_REPO" ]; then
            git init --bare --quiet "$SIM_ARCHIVE_REPO"
        fi
        if ! commit=$(git -C "$SIM_ARCHIVE_REPO" rev-parse "refs/heads/$SIM_REF^{commit}" 2>/dev/null); then
            say "downloading isolated robotd --sim source ($SIM_REF)"
            git -C "$SIM_ARCHIVE_REPO" fetch --quiet --depth 1 \
                "$SIM_REPO_URL" "$SIM_REF:refs/heads/$SIM_REF" ||
                die "could not download $SIM_REF from $SIM_REPO_URL"
            commit=$(git -C "$SIM_ARCHIVE_REPO" rev-parse "refs/heads/$SIM_REF^{commit}")
        fi
    fi

    short=$(printf '%s' "$commit" | cut -c1-12)
    SIM_SOURCE="$RUNTIME_DIR/sim-source-$short"
    export SIM_SOURCE
    if [ ! -d "$SIM_SOURCE" ]; then
        say "extracting isolated robotd --sim source ($short)"
        temporary=$(mktemp -d "$RUNTIME_DIR/.sim-source.XXXXXX")
        git -C "$SIM_ARCHIVE_REPO" archive "$commit" | tar -x -C "$temporary"
        mv "$temporary" "$SIM_SOURCE"
    fi
    # BuildKit must not send the local Cargo output back into the image build context.
    printf 'target\n' >"$SIM_SOURCE/.dockerignore"
    MICRODUCK_SIM_SOURCE=$SIM_SOURCE
    MICRODUCK_RUNTIME_DIR=$RUNTIME_DIR
    MICRODUCK_BODY_PORT=$BODY_PORT
    MICRODUCK_STUDIO_PORT=$STUDIO_PORT
    MICRODUCK_RUST_IMAGE=$RUST_IMAGE
    MICRODUCK_ORT_VERSION=$ORT_VERSION
    export MICRODUCK_SIM_SOURCE MICRODUCK_RUNTIME_DIR
    export MICRODUCK_REPO MICRODUCK_RL_REPO MICRODUCK_BODY_PORT MICRODUCK_STUDIO_PORT
    export MICRODUCK_RUST_IMAGE MICRODUCK_ORT_VERSION
    MICRODUCK_RENDER_WIDTH=$RENDER_WIDTH
    MICRODUCK_RENDER_HEIGHT=$RENDER_HEIGHT
    MICRODUCK_RENDER_FPS=$RENDER_FPS
    MICRODUCK_RENDER_QUALITY=$RENDER_QUALITY
    export MICRODUCK_RENDER_WIDTH MICRODUCK_RENDER_HEIGHT MICRODUCK_RENDER_FPS
    export MICRODUCK_RENDER_QUALITY MICRODUCK_BODY_HOST MICRODUCK_MUJOCO_GL
}

write_robotd_params() {
    PARAMS_FILE="$RUNTIME_DIR/robotd.toml"
    export PARAMS_FILE
    cat >"$PARAMS_FILE" <<'EOF'
[policy]
enabled = true
walk = "/opt/microduck/policies/alpha_walking.onnx"
stand = "/opt/microduck/policies/alpha_stand.onnx"
sitstand = "/opt/microduck/policies/alpha_sitstand.onnx"
ground_pick = "/opt/microduck/policies/alpha_ground_pick.onnx"
kick_left = "/opt/microduck/policies/ball_kick_left.onnx"
kick_right = "/opt/microduck/policies/ball_kick_right.onnx"
roulade = "/opt/microduck/policies/roulade.onnx"

[audio]
device = "default"
EOF
}

start_native_body() {
    if [ "$HEADLESS" = true ]; then
        say "starting native MuJoCo body in the background"
    else
        say "starting MuJoCo body and Viewer"
    fi
    python3 -c '
import plistlib, sys

path, label, python, mjpython, port, width, height, fps, quality, headless, idle, log = sys.argv[1:]
arguments = [
    python,
    mjpython,
    "-m",
    "mjlab_microduck.sim.body_server",
    "--keyframe",
    "HOME",
    "--port",
    port,
    "--render",
    "--render-width",
    width,
    "--render-height",
    height,
    "--render-fps",
    fps,
    "--render-quality",
    quality,
]
if headless == "true":
    arguments.append("--headless")
if idle != "0":
    arguments.extend(["--exit-on-render-idle", idle])
config = {
    "Label": label,
    "ProgramArguments": arguments,
    "RunAtLoad": True,
    "KeepAlive": False,
    "ProcessType": "Interactive",
    "StandardOutPath": log,
    "StandardErrorPath": log,
}
with open(path, "wb") as output:
    plistlib.dump(config, output)
' "$BODY_PLIST" "$BODY_LABEL" \
        "$MICRODUCK_RL_REPO/.venv/bin/python" \
        "$MICRODUCK_RL_REPO/.venv/bin/mjpython" \
        "$BODY_PORT" "$RENDER_WIDTH" "$RENDER_HEIGHT" "$RENDER_FPS" "$RENDER_QUALITY" \
        "$HEADLESS" "$([ "$STOP_ON_BROWSER_CLOSE" = true ] && printf 10 || printf 0)" \
        "$RUNTIME_DIR/mujoco.log"
    launchctl bootstrap "$DOMAIN" "$BODY_PLIST"
    wait_tcp 127.0.0.1 "$BODY_PORT" "MuJoCo body"
}

start_docker_body() {
    say "building and starting headless MuJoCo in Docker ($GPU)"
    compose --profile headless up -d --build mujoco-headless
    wait_tcp 127.0.0.1 "$BODY_PORT" "Docker MuJoCo body"
}

start_compose() {
    say "building and starting robotd and Microduck Studio with Docker Compose"
    compose up -d --build --wait --wait-timeout 60 robotd studio
    wait_tcp 127.0.0.1 "$STUDIO_PORT" "Microduck Studio"
}

verify_status() {
    attempts=0
    status=
    while [ "$attempts" -lt 120 ]; do
        status=$(curl -fsS "http://127.0.0.1:$STUDIO_PORT/api/status") || status=
        if [ -n "$status" ] && printf '%s' "$status" | python3 -c '
import json, sys
status = json.load(sys.stdin)
assert status["robotd"]["connected"], status["robotd"]
assert status["robotd"]["health"]["healthy"], status["robotd"]["health"]
assert status["simulator"]["connected"], status["simulator"]
' 2>/dev/null; then
            return 0
        fi
        attempts=$((attempts + 1))
        sleep 0.25
    done
    if [ -n "$status" ]; then
        printf '%s' "$status" | python3 -c '
import json, sys
status = json.load(sys.stdin)
robotd = status.get("robotd", {})
simulator = status.get("simulator", {})
print("robotd connected:", robotd.get("connected"), file=sys.stderr)
if robotd.get("error"):
    print("robotd error:", robotd["error"], file=sys.stderr)
health = robotd.get("health") or {}
print("robotd healthy:", health.get("healthy"), file=sys.stderr)
print("MuJoCo connected:", simulator.get("connected"), file=sys.stderr)
if simulator.get("error"):
    print("MuJoCo error:", simulator["error"], file=sys.stderr)
' || true
    fi
    die "Studio, robotd, and MuJoCo did not become healthy together"
}

verify_control() {
    base_url="http://127.0.0.1:$STUDIO_PORT"
    say "verifying Web -> robotd -> policy -> MuJoCo control"
    curl -fsS -X POST -H 'content-type: application/json' \
        -d '{"on":true}' "$base_url/api/control/enable" >/dev/null
    before=$(curl -fsS "$base_url/api/status" | python3 -c \
        'import json,sys; p=json.load(sys.stdin)["simulator"]["trunk"]; print(f"{p[0]},{p[1]}")')
    count=0
    while [ "$count" -lt 30 ]; do
        curl -fsS -X POST -H 'content-type: application/json' \
            -d '{"vx":0.2,"vy":0,"vyaw":0}' "$base_url/api/control/move" >/dev/null
        count=$((count + 1))
        sleep 0.1
    done
    curl -fsS -X POST "$base_url/api/control/stop" >/dev/null
    after=$(curl -fsS "$base_url/api/status" | python3 -c \
        'import json,sys; p=json.load(sys.stdin)["simulator"]["trunk"]; print(f"{p[0]},{p[1]}")')
    python3 -c '
import math, sys
before_x, before_y = map(float, sys.argv[1].split(","))
after_x, after_y = map(float, sys.argv[2].split(","))
distance = math.hypot(after_x - before_x, after_y - before_y)
if distance < 0.02:
    raise SystemExit(f"control probe moved only {distance:.3f} m")
print(f"control probe passed: MuJoCo moved {distance:.3f} m")
' "$before" "$after"
}

show_status() {
    curl -fsS "http://127.0.0.1:$STUDIO_PORT/api/status" | python3 -c '
import json, sys
status = json.load(sys.stdin)
print("Studio:   online")
print("robotd:   " + ("healthy" if status["robotd"].get("health", {}).get("healthy") else "offline"))
print("MuJoCo:   " + ("online" if status["simulator"]["connected"] else "offline"))
'
}

monitor_robot() {
    docker container inspect "$ROBOTD_CONTAINER" >/dev/null 2>&1 ||
        die "robotd is not running; start the development stack first"
    compose run --rm --no-deps --build robotctl
}

action=start
if [ "$#" -gt 0 ]; then
    case "$1" in
        start|stop|status|monitor) action=$1; shift ;;
    esac
fi
while [ "$#" -gt 0 ]; do
    case "$1" in
        --sim-mode)
            [ "$#" -ge 2 ] || die "--sim-mode requires native or docker"
            SIM_MODE=$2
            shift 2
            ;;
        --gpu)
            [ "$#" -ge 2 ] || die "--gpu requires none, dri, or nvidia"
            GPU=$2
            shift 2
            ;;
        --headless)
            HEADLESS=true
            shift
            ;;
        --viewer)
            HEADLESS=false
            shift
            ;;
        --stop-on-browser-close)
            STOP_ON_BROWSER_CLOSE=true
            shift
            ;;
        --skip-control-probe)
            CONTROL_PROBE=false
            shift
            ;;
        *) die "usage: $0 [start|stop|status|monitor] [--sim-mode native|docker] [--gpu none|dri|nvidia] [--viewer|--headless] [--stop-on-browser-close] [--skip-control-probe]" ;;
    esac
done

case "$SIM_MODE" in native|docker) ;; *) die "--sim-mode requires native or docker" ;; esac
case "$GPU" in none|dri|nvidia) ;; *) die "--gpu requires none, dri, or nvidia" ;; esac
[ "$SIM_MODE" = docker ] || [ "$GPU" = none ] || die "--gpu is only valid with --sim-mode docker"
[ "$HEADLESS" = true ] || [ "$SIM_MODE" = native ] || die "--viewer is only valid with native mode"
[ "$STOP_ON_BROWSER_CLOSE" = false ] || [ "$HEADLESS" = true ] || die "--stop-on-browser-close requires --headless"

case "$action" in
    stop)
        stop_stack
        exit 0
        ;;
    status)
        show_status
        exit 0
        ;;
    monitor)
        ;;
    start)
        ;;
    *)
        die "usage: $0 [start|stop|status|monitor] [--sim-mode native|docker] [--gpu none|dri|nvidia] [--viewer|--headless] [--stop-on-browser-close] [--skip-control-probe]"
        ;;
esac

need curl
need docker
need git
need python3
[ -d "$MICRODUCK_REPO/.git" ] || die "microduck sibling repository is missing"
if [ "$SIM_MODE" = native ]; then
    [ "$(uname -s)" = Darwin ] || die "native MuJoCo mode currently supports macOS only"
    need launchctl
    [ -f "$MICRODUCK_RL_REPO/.venv/bin/mjpython" ] || die "run 'uv sync' in microduck_rl first"
    MICRODUCK_BODY_HOST=host.docker.internal
else
    MICRODUCK_BODY_HOST=mujoco-headless
fi
case "$GPU" in
    none) MICRODUCK_MUJOCO_GL=${MICRODUCK_MUJOCO_GL:-osmesa} ;;
    dri|nvidia) MICRODUCK_MUJOCO_GL=egl ;;
esac
export MICRODUCK_BODY_HOST MICRODUCK_MUJOCO_GL
say "mode: $SIM_MODE; GPU: $GPU; headless: $HEADLESS; render: ${RENDER_WIDTH}x${RENDER_HEIGHT} @ ${RENDER_FPS} FPS"
docker info >/dev/null 2>&1 || die "Docker is not running or is not reachable"
mkdir -p "$RUNTIME_DIR/jobs" "$SERVICE_MANAGER_DIR"
ensure_sim_source
ensure_runtime_volume
if [ "$action" = monitor ]; then
    monitor_robot
    exit 0
fi
write_robotd_params

stop_stack
trap 'code=$?; if [ "$code" -ne 0 ]; then
    if [ "${MICRODUCK_KEEP_FAILED_STACK:-false}" = true ]; then
        say "leaving failed stack running for diagnostics"
    else
        stop_stack
    fi
fi; exit "$code"' EXIT
if [ "$SIM_MODE" = native ]; then
    start_native_body
else
    start_docker_body
fi
start_compose
start_service_manager
verify_status
if [ "$CONTROL_PROBE" = true ]; then
    verify_control
else
    say "control probe skipped"
fi
verify_status
trap - EXIT

say "ready: http://127.0.0.1:$STUDIO_PORT"
show_status
