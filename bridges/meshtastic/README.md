# Meshtastic bridge (controller)

USB Meshtastic radio → **meshtasticd** (systemd) → TCP `:4403` → bridge → MQTT
`meshtastic/message`.

## Services

| Unit | Role |
|------|------|
| `meshtasticd` | Meshtastic daemon (USB radio) |
| `spectra-meshtastic-bridge` | TCP `:4403` → MQTT overlay payloads |

Config: `/data/spectra/config/meshtastic-bridge.local.json`.

## Deploy

```bash
cd ansible
ansible-playbook playbooks/controller.yml -i inventory/hosts.yml
```

## Verify

```bash
systemctl status meshtasticd spectra-meshtastic-bridge
journalctl -u spectra-meshtastic-bridge -f
```

Send mesh text from another node; the bridge publishes `{text, ttl, color}` to MQTT.
Use a private channel / PSK in production — the Meshtastic default channel is not secure.
