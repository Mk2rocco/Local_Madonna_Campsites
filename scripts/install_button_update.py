#!/usr/bin/env python3
"""Install the manually triggered updater and its narrowly scoped sudo rule."""
import os
from pathlib import Path
import pwd
import re
import shutil
import subprocess
import tempfile


def quote(value):
    return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%').replace('$', '$$') + '"'


def build_unit(repo, username, script):
    return f'''[Unit]
Description=Update campsite display when A+D are held
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/bin/python3 {quote(script)} --repo {quote(repo)} --user {quote(username)}
TimeoutStartSec=10min
'''


def main():
    if os.geteuid() != 0 or not os.environ.get('SUDO_USER'):
        raise SystemExit('Run: sudo python3 scripts/install_button_update.py')
    username = os.environ['SUDO_USER']
    account = pwd.getpwnam(username)
    if account.pw_uid == 0 or not re.fullmatch(r'[a-z_][a-z0-9_-]*[$]?', username):
        raise SystemExit('Run sudo from the non-root account that runs campsites.service')
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
    unit = Path('/etc/systemd/system/campsites-update.service')
    unit.write_text(build_unit(repo, username, script))
    # Grant only this exact nonblocking start command, not arbitrary root access.
    rule = f'{username} ALL=(root) NOPASSWD: /usr/bin/systemctl start --no-block campsites-update.service\n'
    with tempfile.NamedTemporaryFile(mode='w', dir='/etc/sudoers.d', prefix='.campsites-',
                                     delete=False) as temporary:
        temporary.write(rule)
        name = Path(temporary.name)
    try:
        name.chmod(0o440)
        subprocess.run(['visudo', '-cf', str(name)], check=True)
        name.replace('/etc/sudoers.d/campsites-update')
    finally:
        name.unlink(missing_ok=True)
    subprocess.run(['systemctl', 'daemon-reload'], check=True)
    # Migrate anyone who previously installed the optional nightly updater.
    if Path('/etc/systemd/system/campsites-auto-update.timer').exists():
        subprocess.run(['systemctl', 'disable', '--now', 'campsites-auto-update.timer'], check=True)
    print('Installed manual updates. Restart campsites.service to load the button handler.')
    print('Hold A and D (buttons 1 and 4) together for three seconds to check GitHub.')


if __name__ == '__main__':
    main()
