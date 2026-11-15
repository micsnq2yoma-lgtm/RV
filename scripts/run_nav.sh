#!/bin/sh
# Navigation demo (simulation only). Run inside Ubuntu, with Buildroot /tmp bound here.
# No real-time loop is needed: the board drives the simulated robot over TCP at 20 Hz.
set -eu
base=${1:-/tmp/rv014}
case "$base" in /tmp/*) ;; *) echo 'Use a RAM directory under /tmp' >&2; exit 2;; esac
test -f "$base/nav/nav_dashboard.py"
mkdir -p /tmp/runs
export PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1
taskset -c 0 python3 -u "$base/nav/nav_dashboard.py" &
pid=$!
echo "$pid" > "$base/nav_dashboard.pid"
trap 'kill -TERM "$pid" 2>/dev/null || true; wait "$pid" 2>/dev/null || true' EXIT INT TERM
wait "$pid"
