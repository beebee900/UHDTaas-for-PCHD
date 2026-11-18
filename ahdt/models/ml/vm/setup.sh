#!/usr/bin/env bash
# Create the training venv on the VM. Safe to run again: pip skips what is installed.
set -euo pipefail
ATRA=${ATRA:-/home/ubuntu/atra}
HERE=$(cd "$(dirname "$0")" && pwd)
cd "$ATRA"
test -x venv/bin/python || python3.12 -m venv venv
venv/bin/python -m pip install --quiet --upgrade pip
printf 'numpy==2.2.6\nscipy==1.15.3\ntorch==2.7.0\n' > pins.txt
venv/bin/python -m pip install --quiet torch==2.7.0 torchvision==0.22.0 \
  --index-url https://download.pytorch.org/whl/cpu
venv/bin/python -m pip install --quiet -c pins.txt -r "$HERE/requirements.txt"
# Avalanche without its QP solvers: only the GEM plugins call one, and they are not used.
venv/bin/python -m pip install --quiet -c pins.txt gdown==6.4.2 tensorboard==2.21.0 wandb==0.30.0
venv/bin/python -m pip install --quiet --no-deps avalanche-lib==0.6.0 pytorchcv==0.0.74 \
  qpsolvers==4.13.0 gputil==1.4.0 dill==0.3.9
venv/bin/python -c "import torch, avalanche.training, wfdb, mne, onnxruntime, lightgbm, sentence_transformers; print('setup ok', torch.__version__)"
