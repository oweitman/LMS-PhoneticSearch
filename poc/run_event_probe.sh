#!/bin/sh
# Isolated LMS 9.2 only. Installs a disposable event probe, then archives it.
set -eu
cd "$(dirname "$0")/.."
test -f compose.poc.yaml
test -d data/9.2/config/cache/InstalledPlugins/Plugins
active=data/9.2/config/cache/InstalledPlugins/Plugins/PhoneticEventProbe
test ! -e "$active"
mkdir -p .poc-build
archive=$(mktemp -d .poc-build/event-probe-XXXXXXXX)
log=data/9.2/config/logs/server.log
offset=$(wc -c < "$log")

cleanup() {
    if [ -d "$active" ]; then
        mv "$active" "$archive/PhoneticEventProbe"
        docker compose -f compose.poc.yaml restart lms92 >/dev/null
    fi
}
trap cleanup EXIT

install -d "$active"
cp poc/lms_event_probe_plugin/Plugin.pm poc/lms_event_probe_plugin/install.xml "$active/"
docker compose -f compose.poc.yaml restart lms92 >/dev/null

ready=0
for attempt in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do
    if python3 poc/lms_rpc.py 9002 serverstatus 0 10 > "$archive/serverstatus.json" 2>/dev/null; then
        ready=1
        break
    fi
    sleep 1
done
test "$ready" -eq 1
sleep 12
python3 poc/lms_rpc.py 9002 rescan > "$archive/rescan.json"

seen=0
for attempt in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25 26 27 28 29 30; do
    if tail -c +$((offset + 1)) "$log" | grep -q 'PHONETIC_EVENT_PROBE deferred_scan_check='; then
        seen=1
        break
    fi
    sleep 1
done
test "$seen" -eq 1

python3 - "$log" "$offset" <<'PY'
from datetime import datetime
import re
import sys

with open(sys.argv[1], 'rb') as stream:
    stream.seek(int(sys.argv[2]))
    lines = stream.read().decode('utf-8', errors='replace').splitlines()
probe = [line for line in lines if 'PHONETIC_EVENT_PROBE ' in line]
ticks = []
for line in probe:
    if 'PHONETIC_EVENT_PROBE tick=' in line:
        match = re.match(r'\[\d\d-\d\d-\d\d (\d\d:\d\d:\d\d\.\d+)\]', line)
        if match:
            ticks.append(datetime.strptime(match.group(1), '%H:%M:%S.%f'))
events = sum('PHONETIC_EVENT_PROBE scan_done=' in line for line in probe)
deferred = sum('PHONETIC_EVENT_PROBE deferred_scan_check=' in line for line in probe)
assert len(ticks) >= 2, probe
intervals = [(b - a).total_seconds() for a, b in zip(ticks, ticks[1:])]
assert all(4.5 <= interval <= 5.5 for interval in intervals), intervals
assert events >= 1 and deferred >= 1, probe
print(f'version=9.2 events={events} deferred={deferred} ticks={len(ticks)} '
      f'tick_intervals_s={intervals} log={sys.argv[1]}')
PY

cleanup
trap - EXIT
python3 - "$log" "$offset" <<'PY'
import sys
with open(sys.argv[1], 'rb') as stream:
    stream.seek(int(sys.argv[2]))
    text = stream.read().decode('utf-8', errors='replace')
assert 'PHONETIC_EVENT_PROBE shutdown' in text, text
print('shutdown=observed active_probe=removed')
PY
