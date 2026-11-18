#!/usr/bin/env bash
# Progress of the job queue: unit state, current job, finished and failed jobs, recent log.
ATRA=${ATRA:-/home/ubuntu/atra}
Q="$ATRA/queue"
systemctl status atra-wp14b-queue --no-pager 2>/dev/null | sed -n '1,4p'
echo "current: $(cat "$Q/current" 2>/dev/null || echo none)"
echo "done:    $(ls "$Q/done" 2>/dev/null | tr '\n' ' ')"
echo "failed:  $(ls "$Q/failed" 2>/dev/null | tr '\n' ' ')"
echo "pending: $(grep -v '^\s*\(#\|$\)' "$Q/jobs.txt" | awk '{print $1}' | while read -r n; do
  [[ -e "$Q/done/$n" || -e "$Q/failed/$n" ]] || printf '%s ' "$n"; done)"
df -h "$ATRA" | tail -1
if [[ -f "$Q/current" ]]; then
  systemctl status "atra-wp14b-job-$(cat "$Q/current")" --no-pager 2>/dev/null | grep -E "Active|Memory|CPU"
  echo "--- logs/$(cat "$Q/current").log"
  tail -n "${1:-5}" "$ATRA/logs/$(cat "$Q/current").log"
fi
