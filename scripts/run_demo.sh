#!/bin/sh
# Task 014, simulation only. Run inside Ubuntu, with Buildroot /tmp bound here.
set -eu
base=${1:-/tmp/rv014}
case "$base" in /tmp/*) ;; *) echo 'Use a RAM directory under /tmp' >&2; exit 2;; esac
test -x "$base/rt_ctl/rt_ctl"
test ! -e /tmp/rt_ctl.sock
test ! -e "$base/sim.sock"
mkdir -p /tmp/runs
export PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1
"$base/rt_ctl/rt_ctl" --cpu 1 > /tmp/rt_ctl.stats 2>&1 &
rt=$!
echo "$rt" > "$base/rt.pid"
taskset -c 0 tail -n +1 -f /tmp/rt_ctl.stats &
tail_pid=$!
dashboard=
cleanup() {
    if [ -n "$dashboard" ]; then kill -TERM "$dashboard" 2>/dev/null || true; wait "$dashboard" 2>/dev/null || true; fi
    kill -INT "$rt" 2>/dev/null || true
    wait "$rt" 2>/dev/null || true
    kill -TERM "$tail_pid" 2>/dev/null || true
    wait "$tail_pid" 2>/dev/null || true
}
trap cleanup EXIT
trap 'exit 130' INT TERM
taskset -c 0 python3 -u "$base/agent/dashboard.py" &
dashboard=$!
echo "$dashboard" > "$base/dashboard.pid"
wait "$dashboard"
