#!/usr/bin/env bash
# Forward fresh ReSpeaker audio chunks to a remote Whisper inference host.
# Only files modified in the last FORWARD_WINDOW_MIN minutes are pushed, so
# a backlog of historical chunks is never replayed on the offload host.
set -euo pipefail

CHUNKS_DIR="${SPECTRA_CHUNKS_DIR:-/data/spectra/audio-capture/chunks}"
REMOTE="${SPECTRA_FORWARD_REMOTE:?set SPECTRA_FORWARD_REMOTE (user@host)}"
REMOTE_DIR="${SPECTRA_FORWARD_DIR:-/data/spectra/audio-capture/chunks}"
SSH_KEY="${SPECTRA_FORWARD_KEY:-/data/spectra/config/controller_id_rsa}"
INTERVAL="${SPECTRA_FORWARD_INTERVAL:-2}"
WINDOW_MIN="${SPECTRA_FORWARD_WINDOW_MIN:-5}"

echo "Forwarding $CHUNKS_DIR -> $REMOTE:$REMOTE_DIR (window ${WINDOW_MIN}m, every ${INTERVAL}s)"

while true; do
  files=$(cd "$CHUNKS_DIR" && find . -maxdepth 1 -name '*.wav' -mmin "-$WINDOW_MIN" -printf '%P\n' 2>/dev/null || true)
  if [[ -n "$files" ]]; then
    rsync -a --no-owner --no-group --omit-dir-times \
      -e "ssh -i $SSH_KEY -o StrictHostKeyChecking=no -o IdentitiesOnly=yes -o ConnectTimeout=5" \
      --files-from=<(printf '%s\n' "$files") \
      "$CHUNKS_DIR/" "$REMOTE:$REMOTE_DIR/" \
      || echo "rsync failed; retrying in ${INTERVAL}s" >&2
  fi
  sleep "$INTERVAL"
done
