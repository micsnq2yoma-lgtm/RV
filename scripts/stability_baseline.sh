#!/bin/sh
# Task 012: transient diagnostics only; execute after each boot in Buildroot.
set -eu
dmesg -n 8
if [ -w /proc/sys/kernel/sysrq ]; then echo 1 > /proc/sys/kernel/sysrq; fi
for name in sysrq sched_rt_runtime_us sched_rt_period_us watchdog softlockup_panic hung_task_timeout_secs panic; do
    file=/proc/sys/kernel/$name
    if [ -f "$file" ]; then printf '%s=' "$file"; cat "$file"; else echo "$file: absent"; fi
done
ls /proc/sys/kernel/ | grep -iE 'watchdog|lockup|hung|panic' || true
cat /proc/interrupts
ps -o pid,comm 2>/dev/null | head -80
for dir in /proc/irq/[0-9]*; do
    [ -d "$dir" ] || continue
    for name in smp_affinity_list effective_affinity_list; do
        [ ! -r "$dir/$name" ] || { printf '%s=' "$dir/$name"; cat "$dir/$name"; }
    done
done
for file in /sys/class/thermal/thermal_zone*/temp; do
    [ ! -r "$file" ] || { printf '%s=' "$file"; cat "$file"; }
done
if [ -r /proc/config.gz ]; then
    zcat /proc/config.gz | grep -E 'CONFIG_(MAGIC_SYSRQ|DETECT_HUNG_TASK|SOFTLOCKUP_DETECTOR|HARDLOCKUP_DETECTOR|LOCKUP_DETECTOR)=' || true
fi
