#!/usr/bin/env bash
# Copy the finished language artifacts from the VM into var/wp14d/pulled, install and register
# them, and write the evaluation report (run from the repository root).
#   evaluation/language/vm/pull.sh
set -euo pipefail
VM=${ATRA_VM:?set ATRA_VM to user@host of the training machine}
KEY=${ATRA_VM_KEY:?set ATRA_VM_KEY to the SSH key file}
ATRA=${ATRA:-/home/ubuntu/atra}
PY=${PY:-.venv/bin/python}
SSH=(ssh -i "$KEY" "$VM")
DEST=var/wp14d/pulled
mkdir -p "$DEST"
# Only folders with a metrics.json are finished; training state stays on the VM.
done_dirs=$("${SSH[@]}" "cd $ATRA/out/wp14d 2>/dev/null && for d in lora-* mms-tts-ibo-ft; do [ -f \"\$d/metrics.json\" ] && printf '%s ' \"\$d\"; done; true")
if [[ -n "$done_dirs" ]]; then
  # shellcheck disable=SC2086
  "${SSH[@]}" "cd $ATRA/out/wp14d && tar -czf - --exclude=work --exclude=state.pt $done_dirs eval downloads.json 2>/dev/null" \
    | tar -xzf - -C "$DEST"
  echo "pulled: $done_dirs"
else
  echo "no finished artifacts yet"
fi
[[ -f "$DEST/downloads.json" ]] && cp "$DEST/downloads.json" evaluation/language/downloads.json
"$PY" -m evaluation.language.report --src "$DEST"
"$PY" -m ahdt.models.language register --src "$DEST" --dest var/wp14d/models
