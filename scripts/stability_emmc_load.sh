#!/bin/sh
# Run inside Ubuntu with its normal eMMC /tmp, never with a RAM bind on /tmp.
set -eu
file=$(mktemp /tmp/rv012-stress.XXXXXX)
child=
cleanup() {
    if [ -n "$child" ]; then kill -TERM "$child" 2>/dev/null || true; wait "$child" 2>/dev/null || true; fi
    rm -f -- "$file"
}
trap 'exit 0' INT TERM
trap cleanup EXIT
count=0
while :; do
    dd if=/dev/zero of="$file" bs=1M count=50 conv=fsync &
    child=$!
    wait "$child"
    child=
    rm -f -- "$file"
    count=$((count + 1))
    echo "emmc_write_round=$count bytes=52428800"
done
