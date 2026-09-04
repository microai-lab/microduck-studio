#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
STUDIO_REPO=$(dirname "$SCRIPT_DIR")
WORKSPACE=$(dirname "$STUDIO_REPO")
MICRODUCK_REPO=${MICRODUCK_REPO:-"$WORKSPACE/microduck"}
MICRODUCK_RL_REPO=${MICRODUCK_RL_REPO:-"$WORKSPACE/microduck_rl"}
RUNTIME_DIR=${MICRODUCK_STUDIO_RUNTIME:-"$STUDIO_REPO/.studio-runtime/dev-stack"}

BODY_PORT=${MICRODUCK_BODY_PORT:-7801}
BRIDGE_PORT=${MICRODUCK_RPC_BRIDGE_PORT:-8765}
STUDIO_PORT=${MICRODUCK_STUDIO_PORT:-8090}
SIM_REF=${MICRODUCK_SIM_REF:-upstream/sim-remote-io}
RUST_IMAGE=${MICRODUCK_RUST_IMAGE:-microduck-dev:local}
PYTHON_IMAGE=${MICRODUCK_PYTHON_IMAGE:-python:3.13-slim}
ORT_VERSION=${MICRODUCK_ORT_VERSION:-1.28.0}
ORT_VOLUME=microduck-studio-ort
SOCKET_VOLUME=microduck-studio-runtime
ROBOTD_CONTAINER=microduck-studio-robotd
RPC_CONTAINER=microduck-studio-rpc-bridge
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
    remove_label "$WEB_LABEL"
    remove_label "$SOCKET_LABEL"
    stop_body
    remove_container "$RPC_CONTAINER"
    remove_container "$ROBOTD_CONTAINER"
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

wait_file_socket() {
    socket_path=$1
    attempts=0
    while [ "$attempts" -lt 80 ]; do
        [ -S "$socket_path" ] && return 0
        attempts=$((attempts + 1))
        sleep 0.25
    done
    die "robotd socket bridge did not become ready"
}

wait_container_socket() {
    container=$1
    socket_path=$2
    attempts=0
    while [ "$attempts" -lt 80 ]; do
        docker exec "$container" test -S "$socket_path" >/dev/null 2>&1 && return 0
        attempts=$((attempts + 1))
        sleep 0.25
    done
    die "robotd did not create its container socket"
}

resolve_uv() {
    if [ -n "${MICRODUCK_UV_BIN:-}" ] && [ -x "$MICRODUCK_UV_BIN" ]; then
        printf '%s\n' "$MICRODUCK_UV_BIN"
        return
    fi
    if command -v uv >/dev/null 2>&1; then
        command -v uv
        return
    fi
    for candidate in "$HOME/.local/bin/uv" /opt/homebrew/bin/uv /usr/local/bin/uv; do
        if [ -x "$candidate" ]; then
            printf '%s\n' "$candidate"
            return
        fi
    done
    die "uv is not installed"
}

ensure_sim_source() {
    commit=$(git -C "$MICRODUCK_REPO" rev-parse "$SIM_REF^{commit}") ||
        die "missing $SIM_REF; fetch it in the microduck repository"
    short=$(printf '%s' "$commit" | cut -c1-12)
    SIM_SOURCE="$RUNTIME_DIR/sim-source-$short"
    export SIM_SOURCE
    if [ ! -d "$SIM_SOURCE" ]; then
        say "extracting isolated robotd --sim source ($short)"
        temporary=$(mktemp -d "$RUNTIME_DIR/.sim-source.XXXXXX")
        git -C "$MICRODUCK_REPO" archive "$commit" | tar -x -C "$temporary"
        mv "$temporary" "$SIM_SOURCE"
    fi
}

ensure_robotd() {
    if [ ! -x "$SIM_SOURCE/target/debug/robotd" ]; then
        say "building robotd --sim in Docker"
        docker run --rm \
            -v "$SIM_SOURCE:/workspace" \
            -w /workspace \
            "$RUST_IMAGE" \
            cargo build -p robotd
    fi
}

ensure_onnxruntime() {
    ort_path="/opt/ort/onnxruntime/capi/libonnxruntime.so.$ORT_VERSION"
    if ! docker run --rm -v "$ORT_VOLUME:/opt/ort" "$PYTHON_IMAGE" \
        test -f "$ort_path"; then
        say "installing ONNX Runtime $ORT_VERSION in an isolated Docker volume"
        docker run --rm -v "$ORT_VOLUME:/opt/ort" "$PYTHON_IMAGE" \
            pip install --no-cache-dir --target /opt/ort "onnxruntime==$ORT_VERSION"
    fi
    ORT_PATH=$ort_path
    export ORT_PATH
}

write_robotd_params() {
    PARAMS_FILE="$RUNTIME_DIR/robotd.toml"
    export PARAMS_FILE
    cat >"$PARAMS_FILE" <<'EOF'
[policy]
enabled = true
walk = "/workspace/policies/alpha_walking.onnx"
stand = "/workspace/policies/alpha_stand.onnx"
sitstand = "/workspace/policies/alpha_sitstand.onnx"
ground_pick = "/workspace/policies/alpha_ground_pick.onnx"
kick_left = "/workspace/policies/ball_kick_left.onnx"
kick_right = "/workspace/policies/ball_kick_right.onnx"
roulade = "/workspace/policies/roulade.onnx"

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

start_robotd() {
    say "starting robotd with the MuJoCo backend and policies"
    docker run --rm -v "$SOCKET_VOLUME:/runtime" "$PYTHON_IMAGE" \
        python -c 'from pathlib import Path; Path("/runtime/robotd.sock").unlink(missing_ok=True)'
    docker run -d --rm --name "$ROBOTD_CONTAINER" \
        -e "ORT_DYLIB_PATH=$ORT_PATH" \
        -v "$SIM_SOURCE:/workspace:ro" \
        -v "$PARAMS_FILE:/config/robotd.toml:ro" \
        -v "$SOCKET_VOLUME:/runtime" \
        -v "$ORT_VOLUME:/opt/ort:ro" \
        "$RUST_IMAGE" \
        /workspace/target/debug/robotd \
        --sim "host.docker.internal:$BODY_PORT" \
        --params /config/robotd.toml \
        --socket /runtime/robotd.sock >/dev/null
    wait_container_socket "$ROBOTD_CONTAINER" /runtime/robotd.sock

    say "starting Docker and host RPC bridges"
    docker run -d --rm --name "$RPC_CONTAINER" \
        -p "127.0.0.1:$BRIDGE_PORT:$BRIDGE_PORT" \
        -v "$SOCKET_VOLUME:/runtime" \
        -v "$SCRIPT_DIR/rpc_bridge.py:/bridge.py:ro" \
        "$PYTHON_IMAGE" \
        python /bridge.py tcp-to-unix \
        --port "$BRIDGE_PORT" --unix-socket /runtime/robotd.sock >/dev/null
    wait_tcp 127.0.0.1 "$BRIDGE_PORT" "Docker RPC bridge"

    # launchd's system Python cannot read scripts below Documents on a default macOS privacy
    # configuration. A scoped temporary copy keeps the service independent of that TCC rule.
    cp "$SCRIPT_DIR/rpc_bridge.py" "$HOST_BRIDGE_SCRIPT"
    launchctl submit -l "$SOCKET_LABEL" \
        -o "$RUNTIME_DIR/socket-bridge.log" -e "$RUNTIME_DIR/socket-bridge.log" -- \
        /usr/bin/python3 "$HOST_BRIDGE_SCRIPT" unix-to-tcp \
        --unix-socket "$HOST_SOCKET" --port "$BRIDGE_PORT"
    wait_file_socket "$HOST_SOCKET"
}

start_web() {
    uv_bin=$(resolve_uv)
    say "starting Microduck Studio"
    cp "$SCRIPT_DIR/run-studio.sh" "$HOST_STUDIO_SCRIPT"
    chmod +x "$HOST_STUDIO_SCRIPT"
    launchctl submit -l "$WEB_LABEL" \
        -o "$RUNTIME_DIR/studio.log" -e "$RUNTIME_DIR/studio.log" -- \
        "$HOST_STUDIO_SCRIPT" "$STUDIO_REPO" "$uv_bin" "$HOST_SOCKET" \
        "$BODY_PORT" "$STUDIO_PORT" "$RUNTIME_DIR/jobs"
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
        'import json,sys; print(json.load(sys.stdin)["simulator"]["trunk"][0])')
    count=0
    while [ "$count" -lt 30 ]; do
        curl -fsS -X POST -H 'content-type: application/json' \
            -d '{"vx":0.2,"vy":0,"vyaw":0}' "$base_url/api/control/move" >/dev/null
        count=$((count + 1))
        sleep 0.1
    done
    curl -fsS -X POST "$base_url/api/control/stop" >/dev/null
    after=$(curl -fsS "$base_url/api/status" | python3 -c \
        'import json,sys; print(json.load(sys.stdin)["simulator"]["trunk"][0])')
    python3 -c '
import sys
before, after = map(float, sys.argv[1:])
delta = after - before
if delta < 0.02:
    raise SystemExit(f"control probe moved only {delta:.3f} m")
print(f"control probe passed: MuJoCo moved forward {delta:.3f} m")
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
    start)
        ;;
    *)
        die "usage: $0 [start|stop|status]"
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
docker image inspect "$RUST_IMAGE" >/dev/null 2>&1 ||
    die "missing Docker image $RUST_IMAGE (set MICRODUCK_RUST_IMAGE to another Rust image)"

mkdir -p "$RUNTIME_DIR/jobs"
ensure_sim_source
ensure_robotd
ensure_onnxruntime
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
start_robotd
start_web
verify_status
verify_control
verify_status
trap - EXIT

say "ready: http://127.0.0.1:$STUDIO_PORT"
show_status
