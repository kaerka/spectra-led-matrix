"""Load gitignored local secrets."""

from __future__ import annotations

import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
DATA_ROOT = os.environ.get("SPECTRA_DATA_ROOT", "/data/spectra")
# Ansible deploys secrets to the data root; the repo copy is for dev checkouts.
SECRETS_PATHS = (
    os.path.join(DATA_ROOT, "config", "secrets.local.json"),
    os.path.join(ROOT, "config", "secrets.local.json"),
)
SECRETS_EXAMPLE = os.path.join(ROOT, "config", "secrets.example.json")

DEFAULTS = {
    "openweathermap_api_key": "",
    "city": "YourCity",
    "ntp_server": "pool.ntp.org",
}


def load_secrets(paths=SECRETS_PATHS) -> dict:
    path = next((p for p in paths if os.path.isfile(p)), SECRETS_EXAMPLE)
    if not os.path.isfile(path):
        return dict(DEFAULTS)
    with open(path, encoding="utf-8") as fp:
        data = json.load(fp)
    merged = dict(DEFAULTS)
    merged.update(data)
    return merged
