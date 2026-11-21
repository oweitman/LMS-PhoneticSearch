#!/bin/sh
# Isolated 9.2 test server only. This starts a read-only poll and one rescan.
set -eu
cd "$(dirname "$0")/.."
mkdir -p .poc-build
docker compose -f compose.poc.yaml --profile build run --rm builder \
  python3 -m poc.lms_live_poll_probe > .poc-build/live-poll.log 2>&1 &
worker_pid=$!
trap 'kill "$worker_pid" 2>/dev/null || true' EXIT
ready=0
for attempt in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do
  if grep -q '"event": "ready"' .poc-build/live-poll.log; then
    ready=1
    break
  fi
  if ! kill -0 "$worker_pid" 2>/dev/null; then
    cat .poc-build/live-poll.log
    wait "$worker_pid"
    exit 1
  fi
  sleep 0.5
done
if [ "$ready" -ne 1 ]; then
  cat .poc-build/live-poll.log
  exit 1
fi
sleep 1
python3 poc/lms_rpc.py 9002 rescan
wait "$worker_pid"
trap - EXIT
cat .poc-build/live-poll.log
