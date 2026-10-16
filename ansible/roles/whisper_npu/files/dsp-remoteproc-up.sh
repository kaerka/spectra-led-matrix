#!/bin/bash
# Boot the Hexagon compute DSP. QCS6490's PAS remoteproc does not auto_boot,
# so FastRPC/NPU is unavailable until something starts it explicitly.
set -u
for rp in /sys/class/remoteproc/remoteproc*; do
    [ -r "$rp/name" ] || continue
    name=$(cat "$rp/name")
    case "$name" in
        *cdsp*)
            state=$(cat "$rp/state")
            if [ "$state" != "running" ]; then
                echo "starting $name ($rp)"
                echo start > "$rp/state" || echo "failed to start $name" >&2
            fi
            ;;
    esac
done
# udev settles the device node; wait briefly so dependent units see it
for _ in $(seq 1 20); do [ -e /dev/fastrpc-cdsp ] && break; sleep 0.25; done
[ -e /dev/fastrpc-cdsp ] && echo "/dev/fastrpc-cdsp ready" || { echo "/dev/fastrpc-cdsp missing" >&2; exit 1; }
