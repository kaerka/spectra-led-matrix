#!/usr/bin/env python3
"""Matrix display loop — run as a child process so GPIO can be released for video-viewer."""

from __future__ import annotations

import sys

from display.runner import run_display_loop

if __name__ == "__main__":
    try:
        run_display_loop()
    except SystemExit as exc:
        raise
    except KeyboardInterrupt:
        sys.exit(0)
