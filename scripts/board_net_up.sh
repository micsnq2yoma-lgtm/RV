#!/bin/sh
# Task 008-r2: temporary eth0 configuration; run as root in Buildroot.
set -eu

if [ "$#" -gt 1 ]; then
    echo "Usage: sh board_net_up.sh [UTC-time: YYYY-MM-DD HH:MM:SS]" >&2
    exit 2
fi
if [ "$(id -u)" != 0 ]; then
    echo "Run as root." >&2
    exit 1
fi

ip link set eth0 up
if ! ip -4 addr show dev eth0 | grep -Fq 'inet 192.168.50.2/24 '; then
    ip addr add 192.168.50.2/24 dev eth0
fi
# Remove only the known obsolete ICS route; preserve unrelated routing.
if ip route show | grep -Fq 'default via 192.168.137.1 dev eth0'; then
    ip route del default via 192.168.137.1 dev eth0
fi
if [ "$#" -eq 1 ]; then
    date -u -s "$1"
fi
ip addr show eth0
ip route
date -u
cat /sys/class/net/eth0/carrier
