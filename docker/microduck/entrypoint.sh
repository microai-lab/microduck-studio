#!/bin/sh
set -eu

if [ "${1:-}" = robotd ]; then
    rm -f /runtime/robotd.sock
fi

exec "$@"
