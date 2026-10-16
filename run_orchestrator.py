#!/usr/bin/env python3
"""
Pi5 Spectra orchestrator — unified web UI on :8090.

Proxies matrix wall display APIs (:8080). No GPIO on Pi5.

Usage:
    .venv/bin/python run_orchestrator.py

Environment:
    SPECTRA_ORCHESTRATOR_CONFIG  path to orchestrator.local.json
    SPECTRA_DATA_ROOT            default /data/spectra
    ORCHESTRATOR_HOST            bind address (default 0.0.0.0)
    ORCHESTRATOR_PORT            listen port (default 8090)
"""

from __future__ import annotations

import os

import uvicorn

from orchestrator.config import load_config


def main() -> None:
    cfg = load_config()
    host = os.environ.get("ORCHESTRATOR_HOST", cfg.host)
    port = int(os.environ.get("ORCHESTRATOR_PORT", str(cfg.port)))
    print(f"Orchestrator: http://{host}:{port}/", flush=True)
    uvicorn.run(
        "orchestrator.app:app",
        host=host,
        port=port,
        log_level="info",
    )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        raise SystemExit(0)
