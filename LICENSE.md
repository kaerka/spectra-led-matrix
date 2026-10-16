# MIT License

Copyright (c) 2026 Kaerka Phillips

Portions copyright (c) 2020 John Park for Adafruit Industries  
(original "Metro Matrix Clock" and "Game of Life" examples, MIT licensed —  
https://github.com/adafruit/Adafruit_Learning_System_Guides)

The **flame** and **lava** display modes adapt the procedural fire effect from Pimoroni's
Galactic Unicorn MicroPython examples (MIT licensed —  
https://github.com/pimoroni/unicorn, file `examples/galactic_unicorn/fire_effect.py`).

Compact world-clock rendering in this repository is original. Large-wall
world-clock layouts may optionally use a separate companion checkout configured
via Ansible (`repo_urls.world_clock`).

## Third-party dependencies (not included in this repository)

This software is designed to run alongside separately installed open-source
components. See each project for its license terms:

| Component | License | Notes |
| --- | --- | --- |
| [hzeller/rpi-rgb-led-matrix](https://github.com/hzeller/rpi-rgb-led-matrix) | GPL-2.0+ | Python bindings and `video-viewer`; clone and build locally |
| [FastAPI](https://github.com/tiangolo/fastapi) | MIT | Web control plane |
| [Pillow](https://github.com/python-pillow/Pillow) | PIL License | Image rendering |
| [Pimoroni unicorn examples](https://github.com/pimoroni/unicorn) | MIT | Galactic Unicorn fire effect (adapted in `display/modes/fire_mode.py`) |
| [OpenCV](https://github.com/opencv/opencv) | Apache 2.0 | Video frame decode (headless) |

---

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
