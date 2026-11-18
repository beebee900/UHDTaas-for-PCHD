#!/usr/bin/env bash
# The WP14d job queue: runs the jobs of wp14d/queue/jobs.txt one after another.
#
# Each line of jobs.txt is `<name> <MemoryMax> <command...>`; `#` starts a comment. The file is
# read again before every job, so jobs can be appended while the queue runs. Each job runs as
# its own transient unit atra-wp14d-job-<name> (one core, nice 19, its MemoryMax, no swap, at
# most 12 h). A job that exits 0 gets queue/done/<name>; a failed job gets queue/failed/<name>
# and the queue goes on. Delete a marker to run that job again. Jobs log to
# logs/wp14d-<name>.log and resume from their own checkpoints.
set -uo pipefail
ATRA=${ATRA:-/home/ubuntu/atra}
W="$ATRA/wp14d"
Q="$W/queue"
mkdir -p "$Q/done" "$Q/failed" "$ATRA/logs" "$ATRA/out/wp14d"

next_job() {
  grep -v '^\s*\(#\|$\)' "$Q/jobs.txt" | while read -r name mem cmd; do
    if [[ ! -e "$Q/done/$name" && ! -e "$Q/failed/$name" ]]; then
      echo "$name $mem $cmd"
      break
    fi
  done
}

while true; do
  line=$(next_job)
  [[ -z "$line" ]] && { echo "$(date -u +%FT%TZ) queue empty"; exit 0; }
  read -r name mem cmd <<< "$line"
  echo "$(date -u +%FT%TZ) start $name (MemoryMax $mem): $cmd"
  echo "$name" > "$Q/current"
  start=$(date +%s)
  sudo systemctl reset-failed "atra-wp14d-job-$name" 2>/dev/null || true
  if sudo systemd-run --unit="atra-wp14d-job-$name" --uid=ubuntu --gid=ubuntu --wait --collect \
      -p CPUQuota=100% -p Nice=19 -p MemoryMax="$mem" -p MemorySwapMax=0 -p RuntimeMaxSec=43200 \
      -p StandardOutput=append:"$ATRA/logs/wp14d-$name.log" \
      -p StandardError=append:"$ATRA/logs/wp14d-$name.log" \
      --working-directory="$W/code" --setenv=ATRA="$ATRA" --setenv=HOME=/home/ubuntu \
      --setenv=PYTHONPATH="$W/code" --setenv=PATH="$ATRA/venv/bin:/usr/bin:/bin" \
      --setenv=HF_HOME="$W/hf" --setenv=HF_HUB_DISABLE_TELEMETRY=1 \
      --setenv=OMP_NUM_THREADS=1 --setenv=MKL_NUM_THREADS=1 --setenv=TOKENIZERS_PARALLELISM=false \
      --setenv=PYTHONWARNINGS=ignore \
      /bin/bash -c "$cmd"; then
    echo "$(( $(date +%s) - start ))" > "$Q/done/$name"
    echo "$(date -u +%FT%TZ) done $name in $(( $(date +%s) - start )) s"
  else
    code=$?
    echo "exit $code after $(( $(date +%s) - start )) s" > "$Q/failed/$name"
    echo "$(date -u +%FT%TZ) FAILED $name (exit $code), see logs/wp14d-$name.log"
  fi
  rm -f "$Q/current"
done
