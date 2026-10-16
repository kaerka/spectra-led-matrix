#!/usr/bin/env bash
# Throttled rsync from a Pi4 matrix host to Pi5 /data/spectra/media/.
# Use a low --bwlimit to avoid wedging Pi5 built-in WiFi under USB load.
set -euo pipefail

SRC_HOST="${1:?usage: $0 <pi4-hostname-or-ip> [gifs|mp4|all]}"
KIND="${2:-all}"
DEST_ROOT="${SPECTRA_DATA_ROOT:-/data/spectra}/media"
BWLIMIT="${MEDIA_SYNC_BWLIMIT_KBPS:-8000}"   # KB/s

case "$KIND" in
  gifs) PAIRS=("matrix-gif-animations:gifs") ;;
  mp4)  PAIRS=("matrix-mp4-animations:mp4") ;;
  all)  PAIRS=("matrix-gif-animations:gifs" "matrix-mp4-animations:mp4") ;;
  *) echo "kind must be gifs, mp4, or all" >&2; exit 2 ;;
esac

echo "Pull from ${SRC_HOST} -> ${DEST_ROOT} (bwlimit=${BWLIMIT} KB/s)"

for pair in "${PAIRS[@]}"; do
  remote="${pair%%:*}"
  sub="${pair##*:}"
  mkdir -p "${DEST_ROOT}/${sub}"
  rsync -av --partial --progress \
    --bwlimit="${BWLIMIT}" \
    "${SPECTRA_SSH_USER:-spectra}@${SRC_HOST}:~/${remote}/" \
    "${DEST_ROOT}/${sub}/"
done

echo "Done."
