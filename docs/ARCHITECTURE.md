# Architecture

Spectra splits into **display hosts** (GPIO + LED matrix) and an optional
**controller** (MQTT, deploy, orchestrator UI).

## Processes

| Host | Service | Port | Job |
|------|---------|------|-----|
| Each matrix Pi | `spectra-matrix-controller` | `:8080` | FastAPI mode UI + display runner (modes, MQTT overlay, media) |
| Controller (Pi 5) | `spectra-orchestrator` | `:8090` | Dashboard that proxies both walls |
| Controller | Mosquitto | `:1883` | Captions, custom messages |
| Controller | Whisper / Meshtastic bridges | — | Publish short-lived MQTT overlays |

Display modes are registered in `display/modes/registry.py`. The runner swaps
modes without restarting the process. Per-mode settings live in
`config/display_state.json` under `mode_config`.

Procedural effects (rainbow, sparkle, lava lamp) share
`display/modes/effect_config.py` and `/api/mode/{id}/effect` on the wall; the
orchestrator proxies the same path per host.

## Data layout

Canonical paths under `/data/spectra` are described in
[`DATA_LAYOUT.md`](DATA_LAYOUT.md). Secrets and inventory stay out of git:

- `config/secrets.local.json` — OpenWeatherMap key, city, NTP
- `ansible/inventory/hosts.yml` — real hostnames / IPs
- `*.local.json` — MQTT, brightness schedule, matrix geometry

## Trust model

By default the wall and orchestrator APIs listen on all interfaces with **no
authentication**, and Mosquitto may allow anonymous LAN clients. Treat this as
a **home / lab LAN** stack. See [`SECURITY.md`](../SECURITY.md).
