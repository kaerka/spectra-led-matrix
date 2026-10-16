#!/usr/bin/env bash
# Throttled rsync from Pi5 canonical /data/spectra/media/ to a Pi4 matrix host.
# Inverse of sync-media-from-pi4.sh. Does not touch ~/matrix-*-animations.
set -euo pipefail

DEST_HOST="${1:?usage: $0 <pi4-hostname-or-ip> [gifs|mp4|all]}"
KIND="${2:-all}"
SRC_ROOT="${SPECTRA_DATA_ROOT:-/data/spectra}/media"
BWLIMIT="${MEDIA_SYNC_BWLIMIT_KBPS:-8000}"   # KB/s
SSH_KEY="${CONTROLLER_SSH_KEY:-/data/spectra/config/controller_id_rsa}"
REMOTE_USER="${SPECTRA_USER:-spectra}"

case "$KIND" in
  gifs) SUBS=(gifs) ;;
  mp4)  SUBS=(mp4) ;;
  all)  SUBS=(gifs mp4) ;;
  *) echo "kind must be gifs, mp4, or all" >&2; exit 2 ;;
esac

echo "Push ${SRC_ROOT} -> ${REMOTE_USER}@${DEST_HOST}:${SRC_ROOT} (bwlimit=${BWLIMIT} KB/s)"

for sub in "${SUBS[@]}"; do
  mkdir -p "${SRC_ROOT}/${sub}"
  rsync -av --delete --no-owner --no-group --omit-dir-times --partial \
    --bwlimit="${BWLIMIT}" \
    --rsync-path="sudo rsync" \
    -e "ssh -i ${SSH_KEY} -o StrictHostKeyChecking=no -o IdentitiesOnly=yes" \
    "${SRC_ROOT}/${sub}/" \
    "${REMOTE_USER}@${DEST_HOST}:${SRC_ROOT}/${sub}/"
done

echo "Done."
