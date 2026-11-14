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


## Update GitHub code using buttons 1 and 4 (A + D)

This option installs updates only when requested. There is no nightly update
schedule. On the Inky Impression, buttons 1 and 4 are **A and D**.

After merging the button-update pull request, SSH into the Pi and run once:

```bash
cd ~/Local_Madonna_Campsites
git pull --ff-only
sudo python3 scripts/install_button_update.py
sudo systemctl restart campsites.service
```

Run the installer from the account that owns the checkout and runs the display
service (or the checkout owner if the display service runs as root). This uses
the existing `campsites.service` name. The installer creates a separate
`campsites-update.service`, copies its helper into `/usr/local/lib/campsites`,
and grants the installing user permission to request only that specific service
start without a password. If the previous nightly timer was installed, the
installer disables it. Do not install the nightly option as well.

**Hold A and D together for ten seconds, then release both.** The Pi checks
the checkout's `origin/main` and installs new merged commits. A running display
service is stopped during the update and started again afterward. No new
commits means no restart. Release both buttons before requesting another check.
A short simultaneous press does nothing. A alone selects the normal campsite
view on release; B and C continue to select their views on press. D alone opens the detailed NWS advisory view and advances its pages. The gesture works while the display program is running in Inky mode.

Defaults are BCM GPIO 5 for A and GPIO 24 for D. Override with
`INKY_BUTTON_A_PIN` and `INKY_BUTTON_D_PIN` if your wiring differs. Adjust the
hold duration with `INKY_UPDATE_HOLD_SECONDS` (default `10`, must be positive).
No new Python dependency is required.

The update job preserves tracked local edits and refuses divergent history or
branches other than `main`. It uses Git as the checkout owner. GitHub access
must work without interactive credentials; a public HTTPS clone needs none.
A fetch failure leaves the display running; a failed merge attempts to restore
a previously running display service. This is a request to check for an update,
not an instruction to discard local files or force-reset the checkout.

Inspect the result over SSH:

```bash
sudo journalctl -u campsites-update.service -n 50 --no-pager
```

You can request the same update without pressing the buttons:

```bash
sudo systemctl start campsites-update.service
```

The updater does not install new dependencies or automatically roll back code
that fails at application startup. Changing the trigger does not resolve a
separate startup failure; check `journalctl -u campsites.service` for that error.
Re-run the installer if future changes update the helper itself.

Run the regression suite with the normal project dependencies installed:

```bash
python3 -m unittest discover -v
```


### Status light during button updates

After the ten-second A+D hold, the existing status LED (`USER_LED_PIN`, default
BCM GPIO 13) flashes while the update check runs. It turns off when a check
finishes without restarting the display, including when no update is available
or the request fails. Flashing can pause while the display service stops and
restarts to apply new code; the restarted display retains its normal render
flashes. The light indicates activity, not successful installation. Check the
updater and display logs for the result.

Update feedback takes priority over normal display-refresh flashing, so a
pending display timer cannot switch it off. A missing or faulty optional LED
does not prevent the update check. The update request waits in the button's
worker thread, leaving normal display handling responsive, while the separate
systemd update job remains independent of the display process.

For this version, re-run the installer after pulling, then restart the display:

```bash
sudo python3 scripts/install_button_update.py
sudo systemctl restart campsites.service
```

This refreshes the narrowly scoped sudo rule used to wait for the update job
to finish and turn the light off. No nightly schedule is installed.


## Detailed NWS advisories — button 4 (D)

Press and release **D** to open the fourth display program. It shows the full
NWS headline, affected area, severity, timing, description, and instructions
for the configured park location. Long advisories and multiple alerts continue
onto additional pages; press D again to advance, cycling back after the last
page. The footer shows the page number and the last successful check time.

When NWS reports no active advisories, the view displays **No active NWS
advisories**. Network/API failures are displayed as unavailable, rather than
reported as no advisories. If a later refresh fails, the previous successful
data remains visible with an explicit stale-data banner.

The advisory program fetches on startup and every **two hours**, including when
another view is selected. Its schedule is independent of the three existing
views, whose renderers, footer advisories, and configured refresh timing are
unchanged. The fourth view uses the existing `NWS_LAT`, `NWS_LON`,
`NWS_USER_AGENT`, `DATA_TIMEOUT`, and `TZ_NAME` settings. Defaults cover the
same Mt. Madonna point as the primary campsite view.

A/B/C retain their current views. The ten-second A+D GitHub update gesture
and update-status flashing remain available. Short D presses change pages;
an A+D chord suppresses normal A/D view selection.

You can also run the new advisory program separately to generate PNG pages:

```bash
python3 nws_advisories.py
```

It writes `render_advisories.png`, followed by `render_advisories_2.png`, etc.
Override the output basename with `OUTPUT_ADVISORIES`. The standalone command
renders once; the Inky display process provides the automatic two-hour schedule.

After merging and pulling this update, run the button installer and restart
the display (the installer also includes the pending status-light update):

```bash
cd ~/Local_Madonna_Campsites
git pull --ff-only
sudo python3 scripts/install_button_update.py
sudo systemctl restart campsites.service
```
