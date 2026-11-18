#!/usr/bin/env bash
# Start the job queue as one transient systemd unit with the VM caps (wt/AGENT_RULES.md):
# one core, nice 19, 6 GB memory, no swap. Does nothing if the queue already runs or another
# atra job is active.
set -euo pipefail
ATRA=${ATRA:-/home/ubuntu/atra}
UNIT=atra-wp14b-queue
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
  -p StandardOutput=append:"$ATRA/logs/queue.log" -p StandardError=append:"$ATRA/logs/queue.log" \
  --working-directory="$ATRA" --setenv=ATRA="$ATRA" --setenv=HOME=/home/ubuntu \
  /bin/bash "$ATRA/code/ahdt/models/ml/vm/runner.sh"
echo "started $UNIT"
