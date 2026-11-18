#!/usr/bin/env bash
# Copy the finished VM artifacts into var/models/t1, record the dataset checks in
# evaluation/datasets/datasets.lock.yaml, and register everything that is there.
#   ahdt/models/ml/vm/pull.sh            run from the repository root
# Works with no finished artifacts: registration then lists every VM model as not trained.
set -euo pipefail
VM=${ATRA_VM:?set ATRA_VM to user@host of the training machine}
KEY=${ATRA_VM_KEY:?set ATRA_VM_KEY to the SSH key file}
ATRA=${ATRA:-/home/ubuntu/atra}
PY=${PY:-.venv/bin/python}
SSH=(ssh -i "$KEY" "$VM")
DEST=var/models/t1
mkdir -p "$DEST" var/models/t1-datasets
# Only directories with a metrics.json are finished; checkpoints stay on the VM.
done_dirs=$("${SSH[@]}" "cd $ATRA/out 2>/dev/null && for d in */; do [ -f \"\$d/metrics.json\" ] && printf '%s ' \"\${d%/}\"; done; true")
if [[ -n "$done_dirs" ]]; then
  # shellcheck disable=SC2086
  "${SSH[@]}" "cd $ATRA/out && tar -czf - --exclude=ckpt $done_dirs" | tar -xzf - -C "$DEST"
  echo "pulled: $done_dirs"
else
  echo "no finished VM artifacts yet"
fi
# The dense guideline index (apdt/knowledge/dense_index.py) lands in var/wp14b/kb_index;
# GuidelineIndex reads it from var/kb_index when its key matches the laptop's section trees.
mkdir -p var/wp14b/kb_index
"${SSH[@]}" "cd $ATRA/var/kb_index 2>/dev/null && tar -czf - --exclude=shards *.npy *.ids.json \
  2>/dev/null || tar -czf - --files-from /dev/null" | tar -xzf - -C var/wp14b/kb_index
"${SSH[@]}" "cd $ATRA/data 2>/dev/null && tar -czf - */FETCHED 2>/dev/null || tar -czf - --files-from /dev/null" \
  | tar -xzf - -C var/models/t1-datasets
"$PY" -m ahdt.models.ml datasets var/models/t1-datasets
"$PY" -m ahdt.models.ml register
