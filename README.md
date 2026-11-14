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

## Update the code on your Pi over SSH

From your laptop or desktop you can refresh the Pi in one step over SSH:

```bash
ssh pi@<YOUR_PI_HOSTNAME_OR_IP> "cd ~/Local_Madonna_Campsites && git pull"
```

Whenever you want the latest changes from GitHub, SSH into the Pi and run:

```bash
cd ~/Local_Madonna_Campsites

# stop the service so nothing is touching the code while we update
sudo systemctl stop campsites.service

# optional but nice if you care about the venv:
source ~/.venv/campsites/bin/activate

# update code
git pull

# start the service again
sudo systemctl start campsites.service

```

If you do not use `systemd`, simply rerun the command for your chosen
`RUN_MODE` after pulling (for example: `RUN_MODE=inky python
local_madonna_sites.py`).

## Requirements

* Raspberry Pi Zero W (or newer) running Raspberry Pi OS Bookworm/Bullseye
* Python 3.9+
* Virtual environment with the following packages:
  * `requests`
  * `Pillow`
  * `beautifulsoup4`
  * `inky` (installable from Pimoroni's package repository)
  * `lgpio` (for stable GPIOZero button handling)
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
pip install requests pillow beautifulsoup4 "inky[rpi]" lgpio
# Install Flask only if you plan to run the HTTP server
pip install flask
```

If you see `Inky display support requires the 'inky' library` when running
`RUN_MODE=inky`, ensure you are inside the same virtual environment and run:

```bash
pip install --no-cache-dir "inky[rpi]"
sudo apt install -y python3-rpi.gpio python3-spidev
```

The apt packages provide the Raspberry Pi GPIO/SPI drivers that the Inky
library expects at import time.

### Enable SPI for the Inky HAT

Some Raspberry Pi models (notably Pi 5) need an explicit SPI overlay for the
Inky Impression HAT. If you see Inky errors even after installing dependencies,
update `/boot/firmware/config.txt` on the Pi:

1. Open the config file: `sudo nano /boot/firmware/config.txt`
2. Scroll to the SPI section and ensure it contains both lines:
   ```
   dtparam=spi=on
   dtoverlay=spi0-0cs
   ```
3. Save, exit, and reboot the Pi.

This ensures the SPI bus is enabled with chip-select 0 for the display.

## Environment variables

The renderer is controlled by environment variables.  Important ones for the
Pi build:

| Variable | Purpose | Default |
| --- | --- | --- |
| `RUN_MODE` | `server`, `once`, `inky`, or `inky_once` | `server` |
| `TZ_NAME` | Local timezone for timestamps | `America/Los_Angeles` |
| `RES_W`/`RES_H` | Override canvas width/height (auto-set in Inky modes) | `800` / `480` |
| `INKY_REFRESH_SECONDS` | Loop delay between hardware updates | `10800` |
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

The loop refreshes every `INKY_REFRESH_SECONDS` seconds (3 hours by default).  Use `RUN_MODE=inky_once`
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
Environment="GPIOZERO_PIN_FACTORY=lgpio"
ExecStart=/home/pi/.venv/campsites/bin/python local_madonna_sites.py
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

Install `lgpio` inside the same virtual environment used by the service (this
prevents GPIOZero from falling back to slower drivers and fixes button edge
notifications):

```bash
source ~/.venv/campsites/bin/activate
pip install lgpio
deactivate
```

After editing the service file, reload and restart:

```bash
sudo systemctl daemon-reload
sudo systemctl restart campsites.service
```

With `GPIOZERO_PIN_FACTORY=lgpio` the Inky buttons will bind cleanly and you
should see log entries such as `[INFO] Button B pressed; switching to group`
when pressing the physical controls.

Enable it with:

```bash
sudo systemctl enable --now campsites.service
```

This will keep the Inky display updated as soon as the network is available.


## Reservation website compatibility

The scraper uses the current public grid request (`reservation_type=camping`)
and reads the redesigned `grid_table`, month/day headings, and `td_cell_*`
status classes. Group and Uvas views also request `reservation_type=day_use`
so picnic areas remain visible. No browser automation or new dependency is required.

Campsite labels exclude the campground description appended by the website.
Booked, held, in-cart, and departure-only cells are treated as unavailable
(reserved); departure-only dates cannot start an overnight stay. Unknown
status classes and missing date columns are omitted rather than assumed vacant.
Legacy grid markup remains supported.

Run the scraper regression tests after installing the normal dependencies:

```bash
python -m unittest -v test_reservation_grid
```


## Automatic nightly updates on the Pi

After merging the nightly updater pull request, SSH into the Pi as the account
that owns the checkout (for example, `ssh james@campsitepi.local`) and run:

```bash
cd ~/Local_Madonna_Campsites
git pull --ff-only
sudo python3 scripts/install_auto_update.py
systemctl list-timers campsites-auto-update.timer
```

This installs a systemd timer that checks the checkout's GitHub `origin/main`
each night between **3:00 and 3:10 AM America/Los_Angeles**, including daylight
saving changes. If the Pi was off at the scheduled time, systemd makes up the
missed check when it next starts. The Pi needs an internet connection and Git
access that works without a password prompt. A public HTTPS clone works without
extra credentials.

Only merged commits on `main` are installed. If there is a new commit, the
updater stops a running `campsites.service`, fast-forwards the checkout, and
starts the service again. An inactive display service stays inactive. No new
commit means no restart. Git commands run as your normal Pi account, so updates
do not create root-owned files in the checkout.

The updater refuses to change another branch, overwrite tracked local edits,
or replace divergent/local commit history. Fetch failures leave the display
running, and a failed merge attempts to restore a previously running service.
Generated untracked PNGs do not prevent updates; an untracked file that conflicts
with a new upstream file is preserved and the update fails. Package/dependency
installation remains manual.

Check now or inspect the latest logs:

```bash
sudo systemctl start campsites-auto-update.service
journalctl -u campsites-auto-update.service -n 50 --no-pager
```

Disable automatic updates:

```bash
sudo systemctl disable --now campsites-auto-update.timer
```

The installer copies the updater to `/usr/local/lib/campsites` and installs
`campsites-auto-update.service` and `campsites-auto-update.timer` under
`/etc/systemd/system`. Run the installer again if a future release changes the
updater itself. This uses the existing `campsites.service` name from the setup
above; install that display service first.

Developer checks (no Pi hardware or third-party packages needed):

```bash
python3 -m unittest -v test_auto_update
```
