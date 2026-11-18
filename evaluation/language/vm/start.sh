#!/usr/bin/env bash
# Start the WP14d job queue as one transient unit (one core, nice 19, 6 GB, no swap). Does
# nothing if the queue already runs; refuses while any other atra unit is active.
set -euo pipefail
ATRA=${ATRA:-/home/ubuntu/atra}
UNIT=atra-wp14d-queue
if systemctl is-active --quiet "$UNIT"; then
  echo "$UNIT is already running"; exit 0
fi
others=$(systemctl list-units 'atra-*' --state=active --no-legend | grep -v "^ *$UNIT" || true)
if [[ -n "$others" ]]; then
  echo "another atra job is active:"; echo "$others"; exit 1
fi
sudo systemctl reset-failed "$UNIT" 2>/dev/null || true
sudo systemd-run --unit="$UNIT" --uid=ubuntu --gid=ubuntu \
  -p CPUQuota=100% -p Nice=19 -p MemoryMax=6G -p MemorySwapMax=0 \
  -p StandardOutput=append:"$ATRA/logs/wp14d-queue.log" \
  -p StandardError=append:"$ATRA/logs/wp14d-queue.log" \
  --working-directory="$ATRA" --setenv=ATRA="$ATRA" --setenv=HOME=/home/ubuntu \
  /bin/bash "$ATRA/wp14d/code/evaluation/language/vm/runner.sh"
echo "started $UNIT"
