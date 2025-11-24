# Local Madonna Campsites — Raspberry Pi Display

This repository contains a Raspberry Pi friendly renderer for Mt. Madonna
campsite availability.  It can serve a PNG to browsers or update a Pimoroni
Inky Impression 7.3" e-paper display directly.

## Get the code onto your Pi

Clone the repository using your own GitHub username or organization in the
URL (replace the placeholder, and do **not** include the angle brackets):

```bash
sudo apt update && sudo apt install -y git
git clone https://github.com/<YOUR_GITHUB_USERNAME_OR_ORG>/Local_Madonna_Campsites.git
cd Local_Madonna_Campsites
```

If you downloaded a ZIP instead of cloning, unzip it and `cd` into the
extracted `Local_Madonna_Campsites` folder before continuing.

## Requirements

* Raspberry Pi Zero W (or newer) running Raspberry Pi OS Bookworm/Bullseye
* Python 3.9+
* Virtual environment with the following packages:
  * `requests`
  * `Pillow`
  * `beautifulsoup4`
  * `inky` (installable from Pimoroni's package repository)
  * `flask` **(optional; only required for the HTTP server mode)**
* Network access to `https://gooutsideandplay.org` and `https://api.weather.gov`

On the Pi you can install dependencies into a virtual environment:

```bash
sudo apt update
sudo apt install python3-venv python3-pip libjpeg-dev zlib1g-dev libopenjp2-7
# libopenjp2-7 satisfies Pillow's JPEG2000 dependency (fixes libopenjp2.so.7 errors)
python3 -m venv ~/.venv/campsites
source ~/.venv/campsites/bin/activate
pip install -U pip wheel
pip install requests pillow beautifulsoup4 inky
# Install Flask only if you plan to run the HTTP server
pip install flask
```

## Environment variables

The renderer is controlled by environment variables.  Important ones for the
Pi build:

| Variable | Purpose | Default |
| --- | --- | --- |
| `RUN_MODE` | `server`, `once`, `inky`, or `inky_once` | `server` |
| `TZ_NAME` | Local timezone for timestamps | `America/Los_Angeles` |
| `RES_W`/`RES_H` | Override canvas width/height (auto-set in Inky modes) | `800` / `480` |
| `INKY_REFRESH_SECONDS` | Loop delay between hardware updates | `900` |
| `INKY_SATURATION` | Passed to `inky.set_image(..., saturation=…)` | `0.7` |
| `INKY_ROTATE` | Rotate 0 or 180 degrees before sending to the panel | `0` |
| `INKY_BORDER` | Border colour (`white`, `black`, etc.) or `none` | `white` |

The networking and layout related environment variables from the TRMNL build
(`SAFE_LEFT`, `TITLE`, etc.) are also supported.

> **Note:** When you run with `RUN_MODE=inky`, `inky_once`, or `once`, the Flask
> dependency is not needed—the script talks directly to the display or writes a
> PNG and exits.

## Usage

### One-shot PNG render

```bash
RUN_MODE=once OUTPUT=/tmp/render.png TZ_NAME=America/Los_Angeles python local_madonna_sites.py
```

### Flask server (development/testing)

```bash
PORT=8080 TZ_NAME=America/Los_Angeles python local_madonna_sites.py
# Visit http://<pi-address>:8080/render.png
```

### Inky Impression loop

```bash
RUN_MODE=inky TZ_NAME=America/Los_Angeles python local_madonna_sites.py
```

The loop refreshes every `INKY_REFRESH_SECONDS` seconds.  Use `RUN_MODE=inky_once`
to perform a single hardware refresh (useful for testing or cron jobs).

## Raspberry Pi boot service

To refresh the display at boot you can wrap the script in a `systemd` unit:

```ini
[Unit]
Description=Mt. Madonna campsite display
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/home/pi/Local_Madonna_Campsites
Environment="TZ_NAME=America/Los_Angeles"
Environment="RUN_MODE=inky"
ExecStart=/home/pi/.venv/campsites/bin/python local_madonna_sites.py
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

Enable it with:

```bash
sudo systemctl enable --now campsites.service
```

This will keep the Inky display updated as soon as the network is available.
