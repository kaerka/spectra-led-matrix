#!/usr/bin/env bash
# Configure Spectra Pi5 meshtasticd identity/region (single TCP :4403 client).
# Stops spectra-meshtastic-bridge briefly, applies settings, restarts bridge.
set -euo pipefail

ROOT="${SPECTRA_REPO:-$(cd "$(dirname "$0")/.." && pwd)}"
VENV="${ROOT}/bridges/meshtastic/.venv"
MESHTASTIC="${VENV}/bin/meshtastic"
HOST="${MESHTASTIC_HOST:-localhost}"

LONG_NAME="${MESHTASTIC_LONG_NAME:-Spectra Wall}"
SHORT_NAME="${MESHTASTIC_SHORT_NAME:-SP1}"
REGION="${MESHTASTIC_REGION:-US}"

if [[ ! -x "$MESHTASTIC" ]]; then
  echo "Missing bridge venv: $MESHTASTIC" >&2
  exit 1
fi

echo "Stopping spectra-meshtastic-bridge (TCP :4403 contention)..."
sudo systemctl stop spectra-meshtastic-bridge

sleep 1

echo "Setting LoRa region ${REGION}..."
"$MESHTASTIC" --host "$HOST" --set "lora.region" "$REGION" || true

echo "Setting mesh identity: ${LONG_NAME} (${SHORT_NAME})..."
"$MESHTASTIC" --host "$HOST" --set-owner "$LONG_NAME" --set-owner-short "$SHORT_NAME"

echo "Mesh info:"
"$MESHTASTIC" --host "$HOST" --info | head -45

echo "Starting spectra-meshtastic-bridge..."
sudo systemctl start spectra-meshtastic-bridge
sleep 1
systemctl is-active spectra-meshtastic-bridge meshtasticd
