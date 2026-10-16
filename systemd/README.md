# Systemd unit (not installed by default)

The service file lives here so it can be version-controlled and copied to each
Pi when you're ready. It is **not** deployed automatically.

## Prerequisites on the Pi

```bash
cd ~/spectra-led-matrix
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt   # Pillow 9.x — see requirements.txt

cp config/secrets.example.json config/secrets.local.json
cp config/display_state.example.json config/display_state.json
# edit secrets.local.json
```

Ensure `rpi-rgb-led-matrix` bindings are built under
`~/spectra-led-matrix/rpi-rgb-led-matrix/bindings/python`.

## Install on a Pi

```bash
sudo cp ~/spectra-led-matrix/systemd/spectra-matrix-controller.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now spectra-matrix-controller
```

Check status:

```bash
sudo systemctl status spectra-matrix-controller
journalctl -u spectra-matrix-controller -b -f
```

## Two-Pi setup (wall-upper / wall-lower)

Each Pi runs its own copy of the service with its own local
`config/display_state.json`. Both can use port 8080 on their own IP.

If you ever need different ports on one host, use a drop-in:

```bash
sudo systemctl edit spectra-matrix-controller
```

```ini
[Service]
Environment=MATRIX_WEB_PORT=8081
```

A future central controller can call each Pi's `PUT /api/mode/{id}` over the LAN.

## Stop / replace legacy services

If an older script was started manually or via another unit, stop it before
enabling this one — only one process may own the matrix GPIO.

```bash
sudo systemctl stop worldclock   # if the world-clock unit is on this Pi
```
