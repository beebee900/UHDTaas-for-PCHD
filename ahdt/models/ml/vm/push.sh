#!/usr/bin/env bash
# Copy the training code (and the kb section trees for the dense index) to the VM.
#   ahdt/models/ml/vm/push.sh            run from the repository root
set -euo pipefail
VM=${ATRA_VM:?set ATRA_VM to user@host of the training machine}
KEY=${ATRA_VM_KEY:?set ATRA_VM_KEY to the SSH key file}
ATRA=${ATRA:-/home/ubuntu/atra}
SSH=(ssh -i "$KEY" "$VM")
# The new tree replaces code/ in one rename, so a job that is running keeps reading its
# own (now unlinked) script files.
"${SSH[@]}" "mkdir -p $ATRA/var $ATRA/logs $ATRA/out $ATRA/queue && rm -rf $ATRA/code.new && mkdir $ATRA/code.new"
tar -czf - --exclude=__pycache__ --exclude='*.pyc' \
  pyproject.toml atra ahdt/__init__.py ahdt/models/__init__.py ahdt/models/ml \
  apdt/__init__.py apdt/knowledge kb evaluation/__init__.py evaluation/models \
  | "${SSH[@]}" "tar -xzf - -C $ATRA/code.new && ln -sfn $ATRA/var $ATRA/code.new/var && \
      rm -rf $ATRA/code.old && { [ ! -d $ATRA/code ] || mv $ATRA/code $ATRA/code.old; } && \
      mv $ATRA/code.new $ATRA/code && rm -rf $ATRA/code.old"
# The VM keeps its own copy of the trees when the laptop has none.
if [[ -d var/kb_sections ]]; then
  tar -czf - -C var/ kb_sections | "${SSH[@]}" "tar -xzf - -C $ATRA/var"
fi
"${SSH[@]}" "chmod +x $ATRA/code/ahdt/models/ml/vm/*.sh; cp $ATRA/code/ahdt/models/ml/vm/jobs.txt $ATRA/queue/jobs.txt"
echo "pushed to $VM:$ATRA/code"
