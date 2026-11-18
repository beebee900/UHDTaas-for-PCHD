#!/usr/bin/env bash
# Add the language-model training packages to the shared VM venv (versions of all.lock; the
# venv's torch, numpy and scipy stay as they are). Safe to run again.
set -euo pipefail
ATRA=${ATRA:-/home/ubuntu/atra}
cd "$ATRA"
venv/bin/python -m pip install --quiet -c pins.txt peft==0.21.2 accelerate==1.15.0 \
  sentencepiece faster-whisper==1.2.1 sacrebleu==2.6.0 Cython
venv/bin/python -c "import peft, accelerate, faster_whisper, sacrebleu, torch; print('setup ok', peft.__version__, torch.__version__)"
