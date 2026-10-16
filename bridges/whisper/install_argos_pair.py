#!/usr/bin/env python3
"""Pre-install Argos Translate language pair(s) for whisper post-ASR translation."""

from __future__ import annotations

import argparse
import sys

from translate import ensure_argos_language_pair, normalize_lang


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("from_code", nargs="?", default="en")
    parser.add_argument("to_code", nargs="?", default="ru")
    args = parser.parse_args()

    from_code = normalize_lang(args.from_code)
    to_code = normalize_lang(args.to_code)
    print(f"Ensuring Argos package {from_code}→{to_code}...", flush=True)
    ensure_argos_language_pair(from_code, to_code)
    print("OK", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
