# Hardware overview

Spectra is built around **HUB75 RGB LED matrix panels** driven by Raspberry Pi
hosts. A typical dual-wall install looks like this:

```
┌──────────────────────────┐     ethernet      ┌─────────────────────┐
│  Raspberry Pi 5          │◄─────────────────►│  Pi 4 — upper wall  │
│  controller              │                   │  9×64×64 → 192×192  │
│  · Mosquitto             │                   └─────────────────────┘
│  · Orchestrator :8090    │     ethernet      ┌─────────────────────┐
│  · Whisper / Meshtastic  │◄─────────────────►│  Pi 4 — lower wall  │
│  · Ansible deploy        │                   │  9×64×64 → 192×192  │
└──────────────────────────┘                   └─────────────────────┘
```

Use a **dedicated ethernet link** (or VLAN) between the controller and the
matrix Pis so MQTT and deploy traffic do not share Wi‑Fi with the rest of the
LAN. Exact hostnames and addresses belong in your private `hosts.yml`.

## LED panels

| Item | Notes |
|------|--------|
| [Adafruit #3649](https://www.adafruit.com/product/3649) 64×64 RGB, 2.5 mm pitch, 1/32 scan | 5-address (ABCDE) multiplex |
| Dual wall | 9 panels each → **192×192** canvas per wall (18 panels total) |
| Mini-Spectra Clock | 1–4 panels on one Pi 4 (often a single 64×64) |

Budget power carefully: Adafruit cites up to **~4 A per panel** at full white.

## Matrix hosts (Raspberry Pi 4)

| Item | Role |
|------|------|
| Raspberry Pi 4 (8 GB recommended) | One per wall (or one for a mini clock) |
| [Electrodragon RGB Matrix Panel Drive Board](https://www.electrodragon.com/) (or Adafruit HAT/Bonnet) | HUB75 interface; Electrodragon for large walls, Adafruit HAT for mini |
| hzeller [`rpi-rgb-led-matrix`](https://github.com/hzeller/rpi-rgb-led-matrix) | GPIO driver + `video-viewer` for MP4 |
| Panel geometry | `matrix.local.json` — chain length, parallel, mapping, brightness ceiling |

## Controller (Raspberry Pi 5)

| Item | Role |
|------|------|
| Raspberry Pi 5 (8 GB) + NVMe | Ansible, Mosquitto, orchestrator UI, bridges |
| Mosquitto | MQTT broker for captions and custom messages |
| Optional: ReSpeaker 4-Mic Array | Whisper speech capture |
| Optional: Meshtastic USB radio (e.g. MeshToad) | Mesh → MQTT captions |
| Optional: GPS HAT (Adafruit Ultimate GPS) | `gpsd` + chrony time source |
| Optional: USB Wi‑Fi | Home-LAN uplink if the Pi5 is not on the house ethernet |

Pi5 onboard Wi‑Fi can be flaky under heavy USB load; the `wifi_stability` role
keeps `wlan0` down while leaving the driver loaded so USB Wi‑Fi still works.

## Optional Whisper offload

| Item | Role |
|------|------|
| Radxa Dragon Q6A (or similar) | Hexagon NPU Whisper inference |
| Dedicated link to controller | Chunk forward + MQTT publish back |

See [`bridges/whisper/README.md`](../bridges/whisper/README.md).

## Power

| Supply | Typical load |
|--------|----------------|
| Large 5 V high-current PSU (e.g. 60 A / 300 W class) | All panels (+ optionally the Pi 4s) |
| Official Pi 5 PSU | Controller only |
| Distribution blocks / bus bars | Split 5 V into short, thick feeds per chain |

Night-dim schedules and per-mode output gain (lava, rainbow, lava lamp) keep
average draw manageable. Prefer short, thick 5 V feeds to the panels — see
[`PARTS_AND_COSTS.md`](PARTS_AND_COSTS.md) for the distribution and HUB75 cabling
lines.

## Mounting (compute)

The Pi 4 walls, Pi 5 controller, and optional Q6A sit on **DIN rail** with
per-board clip brackets (four brackets in the reference build). Panel frames are
separate (2020 extrusion, etc.).

## Mini-Spectra Clock (standalone)

One Pi 4 + Adafruit HAT + 1–4 panels, local Mosquitto, UI on `:8080`. Deploy with
`ansible/playbooks/mini-clocks.yml` from any machine that can SSH to the Pi —
no Pi 5 required. See the README quick start.
