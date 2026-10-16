# Ansible orchestration

The controller host runs Ansible and configures itself plus downstream matrix
Pis. Example inventory uses placeholder names (`spectra-controller`,
`wall-upper`, `wall-lower`) — replace them with your own in the gitignored
`hosts.yml`.

## Quick start

```bash
cd ~/spectra-led-matrix/ansible

# 1. Copy inventory template (gitignored — fill real addresses)
cp inventory/hosts.example.yml inventory/hosts.yml

# 2. Bootstrap controller (spectra user + /data/spectra)
ansible-playbook playbooks/bootstrap.yml -i inventory/hosts.yml -l controller \
  -e ansible_user="$USER"

# 3. Bootstrap matrix Pis (first run as your SSH login user)
ansible-playbook playbooks/bootstrap-pi4.yml -i inventory/hosts.yml \
  -e ansible_user="$USER"

# 4. Full deploy
ansible-playbook playbooks/site.yml -i inventory/hosts.yml
```

Pi4 deploy rsync runs **on the controller**, SSHs as `spectra@<wall>`, and uses
remote `sudo rsync` (`spectra` gets passwordless sudo from bootstrap). Run
`bootstrap-pi4.yml` once so the walls accept the controller deploy key.

## Playbooks

| Playbook | Purpose |
|----------|---------|
| `bootstrap.yml` | Controller: spectra user, `/data/spectra`, apt deps |
| `bootstrap-pi4.yml` | Walls: spectra user, SSH keys |
| `controller.yml` | Controller: Mosquitto, whisper, meshtastic, **orchestrator UI** |
| `wifi-stability.yml` | Controller: Wi‑Fi powersave / keep onboard `wlan0` down |
| `gps-chrony.yml` | Controller: gpsd + chrony (optional GPS time) |
| `matrix-pis.yml` | Walls: rgbmatrix, repos, venv, systemd |
| `whisper-offload.yml` | Optional NPU offload host (not in `site.yml`) |
| `mini-clocks.yml` | Standalone Mini-Spectra Clocks (no controller required) |
| `sync-media.yml` | Canonical media harvest / push |
| `health-check.yml` | Read-only status probes |
| `site.yml` | Controller + walls (except media sync / offload / mini) |

## Secrets

Never commit `inventory/hosts.yml`, `*.local.json`, or vault plaintext.
Use `ansible-vault` for API keys and MQTT credentials.

## Orchestrator UI

Controller FastAPI dashboard on port **8090** (`spectra-orchestrator.service`):

```bash
curl http://127.0.0.1:8090/api/health
```

Browse `http://<controller>:8090/` for sync-both-walls, per-wall mode controls,
Whisper status, custom messages, and self-test.
