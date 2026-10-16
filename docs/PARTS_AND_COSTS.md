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
| [5 V 300 W display PSU](#display-power) | 1 | **~$26** | Panels + both Pi 4s |
| MeshToad V3 (Meshtastic USB) | 1 | **~$45** | Optional |
| Electrodragon drivers | 2 | **~$16** | + shipping |
| GbE switch (5-port unmanaged) | 1 | **~$33 ref** | Matrix ethernet link |
| Pi 5 controller stack | 1 | ~$200+ | Pi / NVMe / GPS — est. |
| Pi 4 hosts × 2 | 2 | TBD | Powered from display PSU |
| Radxa Dragon Q6A (optional) | 1 | **~$129+ ref** | Whisper offload |
| Mount / extrusion / power distro | — | TBD | Frame hardware |
| **Documented subtotal (known lines)** | | **~$1,100** | excl. Pis, frame, offload extras |
| **Full build (2026 dollars, rough)** | | **~$1,500 – $2,200** | owner ballpark |

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
| 2020 aluminum extrusion + mounts | Frame; cost varies widely |
| Diffusion / face treatment | Optional acrylic / fabric inserts |

---

## References

- [Adafruit 64×64 RGB Matrix 2.5 mm (#3649)](https://www.adafruit.com/product/3649)
- [Radxa Dragon Q6A](https://www.radxa.com/products/dragon/q6a/)
- [`HARDWARE.md`](HARDWARE.md) — roles and topology (no site-specific addresses)
- [`ORCHESTRATION.md`](ORCHESTRATION.md) — deploy layout
