"""Load gitignored local secrets."""

from __future__ import annotations

import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
SECRETS_PATH = os.path.join(ROOT, "config", "secrets.local.json")
SECRETS_EXAMPLE = os.path.join(ROOT, "config", "secrets.example.json")

DEFAULTS = {
    "openweathermap_api_key": "",
    "city": "YourCity",
    "ntp_server": "pool.ntp.org",
}


def load_secrets() -> dict:
    path = SECRETS_PATH if os.path.isfile(SECRETS_PATH) else SECRETS_EXAMPLE
    if not os.path.isfile(path):
        return dict(DEFAULTS)
    with open(path, encoding="utf-8") as fp:
        data = json.load(fp)
    merged = dict(DEFAULTS)
    merged.update(data)
    return merged
