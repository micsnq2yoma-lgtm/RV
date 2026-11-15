#!/bin/sh
# LIBERO demo workbench (simulation only). Run inside Ubuntu, with Buildroot /tmp bound here.
# The PC runs sim_agent/pc/libero_server.py --agent-ip 192.168.50.2 and connects in on TCP 15004.
set -eu
base=${1:-/tmp/rv014}
case "$base" in /tmp/*) ;; *) echo 'Use a RAM directory under /tmp' >&2; exit 2;; esac
test -f "$base/libero/libero_dashboard.py"
mkdir -p /tmp/runs
export PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1
taskset -c 0 python3 -u "$base/libero/libero_dashboard.py" &
pid=$!
echo "$pid" > "$base/libero_dashboard.pid"
trap 'kill -TERM "$pid" 2>/dev/null || true; wait "$pid" 2>/dev/null || true' EXIT INT TERM
wait "$pid"
