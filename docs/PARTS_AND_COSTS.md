# Parts list & cost estimate

Bill of materials for a **two-wall LED matrix + Pi 5 controller + optional
Whisper offload host**. Prices below are historical purchase / reference figures
(USD); treat them as a starting point, not a quote.

See also [`HARDWARE.md`](HARDWARE.md).

---

## Summary

| Category | Qty | Documented | Notes |
| --- | ---: | ---: | --- |
| [64×64 RGB panels](#led-panels-adafruit-3649) | 18 | **~$989** | $54.95 ea (2023) |
| [5 V 300 W display PSU](#display-power) | 1 | **~$26** | Panels (+ optionally Pi 4s) |
| [Power distribution](#power-distribution) | — | TBD | Blocks / bus bars / heavy 5 V cabling |
| MeshToad V3 (Meshtastic USB) | 1 | **~$45** | Optional |
| Electrodragon drivers | 2 | **~$16** | + shipping |
| [HUB75 custom cabling](#hub75-custom-cabling) | kit | **~$37** | IDC + ribbon + crimp tool (2026 cart) |
| GbE switch (5-port unmanaged) | 1 | **~$33 ref** | Matrix ethernet link |
| Pi 5 controller stack | 1 | ~$200+ | Pi / NVMe / GPS — est. |
| Pi 4 hosts × 2 | 2 | TBD | Often powered from display PSU |
| Radxa Dragon Q6A (optional) | 1 | **~$129+ ref** | Whisper offload |
| [DIN rail mounts](#din-rail-mounting) | 4 | **~$60** | Pi 4 × 2, Pi 5, Q6A (~$15 ea) |
| DIN rail (TS35) | TBD | TBD | Length for the four compute boards |
| Mount / extrusion / face | — | TBD | Panel frame hardware |
| **Documented subtotal (known lines)** | | **~$1,200** | excl. Pis, rail length, power distro, frame |
| **Full build (2026 dollars, rough)** | | **~$1,600 – $2,300** | owner ballpark |

Panel cost dominates: **18 × 64×64** modules (9 per wall, 192×192 each).

---

## LED panels (Adafruit #3649)

| Item | Qty | Unit (2023) | Line |
| --- | ---: | ---: | ---: |
| [64×64 RGB LED Matrix — 2.5 mm pitch, 1/32 scan](https://www.adafruit.com/product/3649) | 18 | $54.95 | **$989.10** |

Notes from [Adafruit 3649](https://www.adafruit.com/product/3649):

- 4096 RGB LEDs per module; **5-address (ABCDE)** multiplex — not all HATs support this.
  Large Spectra walls use **Electrodragon** + hzeller `regular` mapping.
- Up to **~4 A per panel** at full white — size the PSU accordingly.

| Wall | Panels |
| --- | ---: |
| Upper | 9 |
| Lower | 9 |
| **Both** | **18** |

---

## Display power

One high-current **5 V / 60 A / 300 W** supply can feed both walls. Example unit
used in the reference build: [SHNITPWR 5 V 60 A](https://www.amazon.com/dp/B07TXWFSZ9)
(since discontinued — any reputable 5 V high-current supply with adequate
headroom works).

| Channel | Typical load |
| --- | --- |
| Primary | All panels |
| Secondary | Both Pi 4 matrix hosts |

Keep the **Pi 5 on its own official PSU**. Night-dim and mode output gains lower
average LED draw.

### Power distribution

The big PSU alone is not enough — you need a **distribution layer** between the
supply and the panel chains (and optionally the Pi 4s):

| Item | Qty | Notes |
| --- | ---: | --- |
| Terminal / distribution blocks (or bus bars) | TBD | Split 5 V into short, thick feeds per chain / wall |
| Heavy-gauge 5 V / GND cable | TBD | Keep runs short; panels want low voltage drop |
| Ring / fork terminals, ferrules | TBD | Cleaner landing on PSU and blocks |
| Fusing / breakers (optional) | TBD | Per wall or per channel |

Exact SKUs vary by how the frame is wired; treat this as a required BOM line even
when the PSU itself is already listed.

---

## HUB75 custom cabling

Stock panel ribbons are often too long or too short. A small DIY kit covers
custom lengths between Electrodragon boards and the 16-pin HUB75 IDC headers:

| Item | Qty | Unit (2026) | Line | Notes |
| --- | ---: | ---: | ---: | --- |
| FC-16P IDC female connectors (2.54 mm) | 20-pack | ~$10 | **~$10** | Insulation-displacement; pair with 1.27 mm ribbon |
| 16-conductor flat ribbon (1.27 mm pitch) | 16 ft | ~$10 | **~$10** | Rainbow-coded rolls are easy to orient |
| IDC ribbon crimp tool | 1 | ~$17 | **~$17** | Presses the whole connector in one go |
| **Kit subtotal** | | | **~$37** | Plus cut-to-length labour |

HUB75 is **16 pins**; do not substitute 10-pin IDC (that's a different interface).
Mark pin-1 / the red stripe consistently so you don't reverse a cable into a panel.

---

## DIN rail mounting

Compute boards sit on **35 mm DIN rail (TS35)** behind / beside the display rather
than loose on a shelf:

| Item | Qty | Unit (2026) | Notes |
| --- | ---: | ---: | --- |
| DIN rail mount bracket (Pi / SBC class) | **4** | ~$15 | Pi 4 upper, Pi 4 lower, Pi 5 controller, Radxa Q6A |
| DIN rail (TS35 / “top hat”) | TBD length | TBD | Steel or aluminium; cut to fit the four brackets + spare |

Reference build status: three brackets already installed (both Pi 4s + Q6A); one
more bracket ordered for the Pi 5. Rail length is still TBD for the BOM.

Generic Pi-compatible brackets (Pi 4 / Pi 5 / similar SBCs) are widely available;
confirm standoff clearance for HATs (GPS, Electrodragon is on the Pi 4s, not the
Pi 5).

---

## Pi 5 controller

| Item | Qty | Est. | Notes |
| --- | ---: | ---: | --- |
| Raspberry Pi 5 Model B (8 GB) | 1 | ~$80 | NVMe boot recommended |
| Active cooler / case | 1 | ~$15 | |
| NVMe SSD + M.2 HAT | 1 | ~$60 | `/data/spectra` |
| Pi 5 USB-C PSU (27 W class) | 1 | ~$15 | Separate from panel PSU |
| Adafruit Ultimate GPS HAT | 0–1 | ~$45 | Optional time source |
| ReSpeaker 4-Mic Array | 0–1 | ~$70 | Whisper capture |
| MeshToad / Meshtastic USB | 0–1 | ~$45 | Mesh captions |
| USB Wi‑Fi adapter (MT7612U class) | 0–1 | ~$60 | If not on house ethernet |
| Google Coral USB | 0–1 | ~$60 | Optional; Whisper path prefers NPU offload |

---

## Pi 4 matrix hosts

| Item | Qty | Notes |
| --- | ---: | --- |
| Raspberry Pi 4 Model B (8 GB recommended) | 2 | One per wall |
| Electrodragon RGB matrix board | 2 | `hardware_mapping = regular` |
| microSD | 2 | |
| Panels | 18 | See above |

Mini-Spectra: one Pi 4 + Adafruit HAT + 1–4 panels instead of Electrodragon.

---

## Whisper offload (optional)

| Item | Notes |
| --- | --- |
| [Radxa Dragon Q6A](https://www.radxa.com/products/dragon/q6a/) (12 GB) | ~$129 board ref |
| NVMe + board PSU | Separate from matrix PSU |
| Dedicated ethernet to controller | Chunk forward / Ansible |

See [`bridges/whisper/README.md`](../bridges/whisper/README.md).

---

## Networking & frame

| Item | Notes |
| --- | --- |
| Unmanaged 5-port GbE switch | Dedicated controller ↔ walls (+ optional offload) |
| Ethernet patch cables | One per host on the matrix link |
| 2020 aluminum extrusion + mounts | Panel frame; cost varies widely |
| Diffusion / face treatment | Optional acrylic / fabric inserts |
| DIN rail + brackets | See [DIN rail mounting](#din-rail-mounting) |

---

## References

- [Adafruit 64×64 RGB Matrix 2.5 mm (#3649)](https://www.adafruit.com/product/3649)
- [Radxa Dragon Q6A](https://www.radxa.com/products/dragon/q6a/)
- [`HARDWARE.md`](HARDWARE.md) — roles and topology (no site-specific addresses)
- [`ORCHESTRATION.md`](ORCHESTRATION.md) — deploy layout
