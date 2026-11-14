#!/usr/bin/env python3
"""Install a systemd timer for this checkout. Run with sudo python3."""
import os
from pathlib import Path
import pwd
import shutil
import subprocess


def quote(value):
    # systemd performs percent expansion even inside quotes.
    return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%') + '"'


def build_units(repo, username, script):
    service = f'''[Unit]
Description=Update campsite display from GitHub main
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/bin/python3 {quote(script)} --repo {quote(repo)} --user {quote(username)}
TimeoutStartSec=10min
'''
    timer = '''[Unit]
Description=Check for campsite display updates every night

[Timer]
OnCalendar=*-*-* 03:00:00 America/Los_Angeles
RandomizedDelaySec=10min
Persistent=true
Unit=campsites-auto-update.service

[Install]
WantedBy=timers.target
'''
    return service, timer


def main():
    if os.geteuid() != 0 or not os.environ.get('SUDO_USER'):
        raise SystemExit('Run: sudo python3 scripts/install_auto_update.py')
    username = os.environ['SUDO_USER']
    account = pwd.getpwnam(username)
    if account.pw_uid == 0:
        raise SystemExit('Run sudo from the non-root account that owns the checkout')
    repo = Path(__file__).resolve().parent.parent
    top = subprocess.check_output(['runuser', '-u', username, '--', 'git', '-C',
                                   str(repo), 'rev-parse', '--show-toplevel'], text=True).strip()
    if Path(top).resolve() != repo:
        raise SystemExit('Installer must be run from the repository checkout')
    destination = Path('/usr/local/lib/campsites')
    destination.mkdir(parents=True, exist_ok=True)
    script = destination / 'update_campsites.py'
    shutil.copyfile(repo / 'scripts/update_campsites.py', script)
    script.chmod(0o644)
    os.chown(script, 0, 0)
    units = Path('/etc/systemd/system')
    service, timer = build_units(repo, username, script)
    (units / 'campsites-auto-update.service').write_text(service)
    (units / 'campsites-auto-update.timer').write_text(timer)
    subprocess.run(['systemctl', 'daemon-reload'], check=True)
    subprocess.run(['systemctl', 'enable', '--now', 'campsites-auto-update.timer'], check=True)
    print('Installed: checks main nightly at 3:00–3:10 AM Pacific.')
    print('Status: systemctl list-timers campsites-auto-update.timer')


if __name__ == '__main__':
    main()
