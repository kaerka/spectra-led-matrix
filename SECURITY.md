# Security

Spectra is designed for a **trusted home or lab LAN**. Defaults favour easy
bring-up over internet exposure.

## Trust assumptions

| Surface | Default | Risk |
|---------|---------|------|
| Wall UI / API `:8080` | Listen `0.0.0.0`, **no auth** | Anyone on the LAN can change modes, media, MQTT overlay, messages |
| Orchestrator `:8090` | Same | Can drive all walls, toggle Whisper, purge queues, publish MQTT tests |
| Mosquitto `:1883` | Often `allow_anonymous` | Captions and retained messages are readable/writable on the LAN |

Do **not** port-forward these services to the public internet without adding
authentication and tightening MQTT.

## Secrets

- Put API keys in `config/secrets.local.json` (gitignored) or Ansible vault.
- Never commit real inventory (`ansible/inventory/hosts.yml`) or `*.local.json`.
- Example configs use placeholders only (`YourCity`, `*.local` hostnames).

## Hardening ideas

1. Firewall `:8080` / `:8090` / `:1883` to the matrix subnet only.
2. Bind services to the controller–wall ethernet interface.
3. Add MQTT username/password (or ACL) and disable anonymous access.
4. Put a reverse proxy with basic auth / token in front of the orchestrator.
5. Replace `StrictHostKeyChecking=no` in deploy helpers with a managed known_hosts.
6. Narrow `spectra` sudo from `NOPASSWD:ALL` to the commands deploy actually needs.

## Reporting

If you find a vulnerability in this public repository, please open a private
security advisory on GitHub or contact the maintainer via the profile listed on
the repo.
