#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
STUDIO_REPO=$(dirname "$SCRIPT_DIR")
WORKSPACE=$(dirname "$STUDIO_REPO")
MICRODUCK_REPO=${MICRODUCK_REPO:-"$WORKSPACE/microduck"}
MICRODUCK_RL_REPO=${MICRODUCK_RL_REPO:-"$WORKSPACE/microduck_rl"}
RUNTIME_DIR=${MICRODUCK_STUDIO_RUNTIME:-"$STUDIO_REPO/.studio-runtime/dev-stack"}
COMPOSE_FILE="$STUDIO_REPO/compose.yaml"

BODY_PORT=${MICRODUCK_BODY_PORT:-7801}
STUDIO_PORT=${MICRODUCK_STUDIO_PORT:-8090}
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

BODY_LABEL=com.microduck.mujoco.viewer
SOCKET_LABEL=com.microduck.studio.socketbridge
WEB_LABEL=com.microduck.studio.web
DOMAIN="gui/$(id -u)"

say() { printf '\033[36m==\033[0m %s\n' "$*"; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }
need() { command -v "$1" >/dev/null 2>&1 || die "missing command: $1"; }

label_exists() {
    launchctl print "$DOMAIN/$1" >/dev/null 2>&1
}

remove_label() {
    label_exists "$1" && launchctl remove "$1" || true
}

remove_container() {
    docker container inspect "$1" >/dev/null 2>&1 && docker rm -f "$1" >/dev/null || true
}

compose() {
    docker compose --project-directory "$STUDIO_REPO" -f "$COMPOSE_FILE" "$@"
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

stop_stack() {
    say "stopping Studio development stack"
    # Remove host jobs and containers created by launcher versions before Compose.
    remove_label "$WEB_LABEL"
    remove_label "$SOCKET_LABEL"
    stop_body
    compose down --remove-orphans >/dev/null 2>&1 || true
    remove_container "$RPC_CONTAINER"
    remove_container "$ROBOTD_CONTAINER"
    remove_container "$WEB_CONTAINER"
    rm -f "$HOST_SOCKET" "$HOST_BRIDGE_SCRIPT" "$HOST_STUDIO_SCRIPT"
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

start_body() {
    say "starting MuJoCo body and Viewer"
    python3 -c '
import plistlib, sys

path, label, python, mjpython, port, log = sys.argv[1:]
config = {
    "Label": label,
    "ProgramArguments": [
        python,
        mjpython,
        "-m",
        "mjlab_microduck.sim.body_server",
        "--keyframe",
        "HOME",
        "--port",
        port,
    ],
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
        "$BODY_PORT" "$RUNTIME_DIR/mujoco.log"
    launchctl bootstrap "$DOMAIN" "$BODY_PLIST"
    wait_tcp 127.0.0.1 "$BODY_PORT" "MuJoCo body"
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

action=${1:-start}
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
        die "usage: $0 [start|stop|status|monitor]"
        ;;
esac

need curl
need docker
need git
need launchctl
need python3
[ "$(uname -s)" = Darwin ] || die "this launcher currently supports macOS only"
[ -d "$MICRODUCK_REPO/.git" ] || die "microduck sibling repository is missing"
[ -f "$MICRODUCK_RL_REPO/.venv/bin/mjpython" ] || die "run 'uv sync' in microduck_rl first"
docker info >/dev/null 2>&1 || die "Docker Desktop is not running"
mkdir -p "$RUNTIME_DIR/jobs"
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
start_body
start_compose
verify_status
verify_control
verify_status
trap - EXIT

say "ready: http://127.0.0.1:$STUDIO_PORT"
show_status
