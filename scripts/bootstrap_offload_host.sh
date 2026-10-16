#!/usr/bin/env bash
# Bootstrap an inference-offload host (e.g. Radxa Q6A) for Spectra.
# Creates the spectra user, /data/spectra layout, and installs the Pi5
# controller deploy key so ansible/rsync can manage the host as spectra@.
#
# Run as root ON the target host:
#   sudo bash bootstrap_offload_host.sh "<controller_pubkey_line>"
set -euo pipefail

PUBKEY="${1:-}"
SPECTRA_USER=spectra
SPECTRA_GROUP=spectra
DATA_ROOT=/data/spectra

if [[ -z "$PUBKEY" ]]; then
  echo "Usage: sudo bash $0 '<controller ssh public key line>'" >&2
  exit 1
fi

getent group "$SPECTRA_GROUP" >/dev/null || groupadd "$SPECTRA_GROUP"
if ! id "$SPECTRA_USER" >/dev/null 2>&1; then
  useradd -m -g "$SPECTRA_GROUP" -G sudo,audio -s /bin/bash "$SPECTRA_USER"
fi

cat > "/etc/sudoers.d/$SPECTRA_USER" <<EOF
$SPECTRA_USER ALL=(ALL) NOPASSWD:ALL
EOF
chmod 0440 "/etc/sudoers.d/$SPECTRA_USER"
visudo -cf "/etc/sudoers.d/$SPECTRA_USER"

mkdir -p /data
for d in "" /config /repos /audio-capture/chunks /audio-capture/transcripts /logs; do
  mkdir -p "$DATA_ROOT$d"
done
chown -R "$SPECTRA_USER:$SPECTRA_GROUP" "$DATA_ROOT"
chmod 0755 "$DATA_ROOT"
chmod 0750 "$DATA_ROOT/config"

install -d -m 0700 -o "$SPECTRA_USER" -g "$SPECTRA_GROUP" "/home/$SPECTRA_USER/.ssh"
AUTH="/home/$SPECTRA_USER/.ssh/authorized_keys"
touch "$AUTH"
grep -qF "$PUBKEY" "$AUTH" || echo "$PUBKEY" >> "$AUTH"
chown "$SPECTRA_USER:$SPECTRA_GROUP" "$AUTH"
chmod 0600 "$AUTH"

apt-get update -qq
apt-get install -y -qq python3-venv rsync ffmpeg >/dev/null

echo "Bootstrap complete: $SPECTRA_USER@$(hostname) ready for Spectra deploys."
