# /data/spectra layout

Runtime data lives outside the git repo under `/data/spectra` on Spectra hosts
(controller and matrix nodes).

```
/data/spectra/
├── config/                    # gitignored — Ansible templated
│   ├── secrets.local.json
│   ├── display_state.json
│   ├── mqtt.local.json
│   └── controller_id_rsa.pub  # controller pubkey for wall SSH
├── repos/
│   ├── spectra-led-matrix/
│   ├── world-clock/
│   ├── whisper-audio-capture/   # controller only
│   └── rpi-rgb-led-matrix/      # matrix hosts
├── media/
│   ├── gifs/
│   └── mp4/
├── audio-capture/               # controller only
│   ├── chunks/
│   └── transcripts/
└── logs/
```

Environment variable: `SPECTRA_DATA_ROOT=/data/spectra` (systemd units set this).

Media canonical store is on the **controller**. Sync is a dedicated playbook
(not part of `site.yml`): harvest wall `~/matrix-{gif,mp4}-animations` into
`/data/spectra/media/{gifs,mp4}`, then push that tree to the walls
(`playbooks/sync-media.yml`). Ad-hoc helpers:
`scripts/sync-media-from-pi4.sh` and `scripts/sync-media-to-pi4.sh`.
`display/media_paths.py` prefers `SPECTRA_DATA_ROOT/media/...` when present.
