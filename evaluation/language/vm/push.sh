#!/usr/bin/env bash
# Copy the training code and the prepared data to the VM (run from the repository root).
#   evaluation/language/vm/push.sh
set -euo pipefail
VM=${ATRA_VM:?set ATRA_VM to user@host of the training machine}
KEY=${ATRA_VM_KEY:?set ATRA_VM_KEY to the SSH key file}
ATRA=${ATRA:-/home/ubuntu/atra}
W="$ATRA/wp14d"
SSH=(ssh -i "$KEY" "$VM")
"${SSH[@]}" "mkdir -p $W/queue $ATRA/logs $ATRA/out/wp14d && rm -rf $W/code.new && mkdir $W/code.new"
# The new tree replaces code/ in one rename, so a running job keeps its own script files.
tar -czf - --exclude=__pycache__ --exclude='*.pyc' \
  pyproject.toml atra evaluation/__init__.py evaluation/language ahdt/__init__.py ahdt/models/__init__.py \
  ahdt/models/language \
  | "${SSH[@]}" "tar -xzf - -C $W/code.new && \
      rm -rf $W/code.old && { [ ! -d $W/code ] || mv $W/code $W/code.old; } && \
      mv $W/code.new $W/code && rm -rf $W/code.old"
"${SSH[@]}" "chmod +x $W/code/evaluation/language/vm/*.sh; \
  cp $W/code/evaluation/language/vm/jobs.txt $W/queue/jobs.txt"
echo "pushed to $VM:$W/code"
