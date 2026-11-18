#!/usr/bin/env bash
# Download the T1 training datasets to $ATRA/data and check them.
#   fetch_datasets.sh [mitdb|ptb-xl|sleep-edfx|wesad ...]   (default: all four)
# PhysioNet files are checked against the project's SHA256SUMS.txt. WESAD publishes no
# checksum, so its archive hash is recorded. Each finished dataset writes data/<id>/FETCHED
# (JSON: archive url, bytes, sha256, check, date); a dataset with that file is skipped.
set -euo pipefail
ATRA=${ATRA:-/home/ubuntu/atra}
DATA="$ATRA/data"
MIN_FREE_GB=${MIN_FREE_GB:-8}
mkdir -p "$DATA"

log() { echo "$(date -u +%FT%TZ) fetch: $*"; }

free_gb() { df --output=avail -BG "$DATA" | tail -1 | tr -dc 0-9; }

need_space() {
  local want=$1
  if (( $(free_gb) - want < MIN_FREE_GB )); then
    log "not enough disk: $(free_gb) GB free, $want GB needed, $MIN_FREE_GB GB kept free"
    exit 3
  fi
}

record() {  # id url bytes sha256 check
  printf '{"id": "%s", "url": "%s", "bytes": %s, "sha256": "%s", "check": "%s", "accessed": "%s"}\n' \
    "$1" "$2" "$3" "$4" "$5" "$(date -u +%F)" > "$DATA/$1/FETCHED"
}

physionet() {  # id version size_gb
  # Files come from the PhysioNet open-data mirror on AWS (the physionet.org file server
  # throttles to about 40 kB/s); SHA256SUMS.txt comes from physionet.org itself.
  local id=$1 version=$2 size=$3
  local primary="https://physionet.org/files/$id/$version"
  local mirror="https://physionet-open.s3.amazonaws.com/$id/$version"
  [[ -f "$DATA/$id/FETCHED" ]] && { log "$id already fetched"; return; }
  need_space "$size"
  mkdir -p "$DATA/$id"
  cd "$DATA/$id"
  curl -fsSL --retry 5 -o SHA256SUMS.txt "$primary/SHA256SUMS.txt"
  local round
  for round in 1 2 3; do
    : > .missing
    while read -r sum path; do
      if [[ ! -f "$path" ]] || [[ "$(sha256sum "$path" | cut -d' ' -f1)" != "$sum" ]]; then
        printf 'url = "%s/%s"\noutput = "%s"\n' "$mirror" "$path" "$path" >> .missing
      fi
    done < SHA256SUMS.txt
    local n
    n=$(grep -c '^url' .missing || true)
    (( n == 0 )) && break
    log "$id: round $round, downloading $n files"
    curl -Z --parallel-max 8 --create-dirs -fsSL --retry 5 -K .missing || true
  done
  rm -f .missing
  sha256sum --quiet -c SHA256SUMS.txt || { log "$id: files do not match SHA256SUMS.txt"; exit 4; }
  local bytes files
  bytes=$(du -sb --exclude=FETCHED . | cut -f1)
  files=$(wc -l < SHA256SUMS.txt)
  record "$id" "$mirror/" "$bytes" "$(sha256sum SHA256SUMS.txt | cut -d' ' -f1)" \
    "every file matches SHA256SUMS.txt of $primary (sha256 given is of SHA256SUMS.txt)"
  cd "$ATRA"
  log "$id: done ($files files, $bytes bytes)"
}

wesad() {
  local id=wesad url=https://uni-siegen.sciebo.de/s/HGdUkoNlW1Ub0Gx/download
  [[ -f "$DATA/$id/FETCHED" ]] && { log "$id already fetched"; return; }
  # 2.3 GB archive + 13 GB of pickles before wesad_compact.py shrinks them to about 0.6 GB.
  need_space 16
  mkdir -p "$DATA/$id"
  local zip="$DATA/$id.zip"
  log "$id: downloading $url"
  curl -fsSL --retry 5 -C - -o "$zip" "$url"
  local bytes sha
  bytes=$(stat -c %s "$zip")
  sha=$(sha256sum "$zip" | cut -d' ' -f1)
  log "$id: $bytes bytes, sha256 $sha; extracting the subject pickles and readmes"
  python3 - "$zip" "$DATA/$id" <<'PY'
import sys, zipfile
z = zipfile.ZipFile(sys.argv[1])
z.testzip()
for name in z.namelist():
    if name.endswith((".pkl", "_readme.txt", "_quest.csv")) or name.endswith("readme.pdf"):
        z.extract(name, sys.argv[2])
PY
  rm -f "$zip"
  "$ATRA/venv/bin/python" "$ATRA/code/ahdt/models/ml/vm/wesad_compact.py" "$DATA/$id/WESAD"
  record "$id" "$url" "$bytes" "$sha" "zip CRC check; no published checksum"
  log "$id: done"
}

ids=("$@")
(( ${#ids[@]} )) || ids=(mitdb ptb-xl sleep-edfx wesad)
for id in "${ids[@]}"; do
  case $id in
    mitdb) physionet mitdb 1.0.0 1 ;;
    ptb-xl) physionet ptb-xl 1.0.3 4 ;;
    sleep-edfx) physionet sleep-edfx 1.0.0 10 ;;
    wesad) wesad ;;
    *) log "unknown dataset $id"; exit 2 ;;
  esac
done
