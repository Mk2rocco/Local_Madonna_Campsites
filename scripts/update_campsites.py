#!/usr/bin/env python3
"""Fast-forward a Pi checkout as its owner, restarting only for new commits."""
import argparse
import fcntl
import os
import pwd
import subprocess


def update(repo, username, service='campsites.service'):
    account = pwd.getpwnam(username)
    if account.pw_uid == 0:
        raise ValueError('The checkout must belong to a non-root user')
    if os.geteuid() not in (0, account.pw_uid):
        raise PermissionError('Run as root or the checkout owner')
    prefix = ['runuser', '-u', username, '--'] if os.geteuid() == 0 else []
    env = dict(os.environ, GIT_TERMINAL_PROMPT='0',
               GIT_SSH_COMMAND='ssh -oBatchMode=yes -oConnectTimeout=20')

    def git(*args):
        return subprocess.run(prefix + ['git', '-C', repo, *args],
                              check=True, text=True, stdout=subprocess.PIPE,
                              timeout=120, env=env).stdout.strip()

    def systemctl(*args, check=True):
        return subprocess.run(['systemctl', *args, service], check=check, timeout=60)

    if git('symbolic-ref', '--short', 'HEAD') != 'main':
        raise ValueError('Checkout is not on main; leaving it unchanged')
    if git('status', '--porcelain', '--untracked-files=no'):
        raise ValueError('Tracked files have local changes; leaving them unchanged')
    git('fetch', '--no-tags', 'origin', 'refs/heads/main:refs/remotes/origin/main')
    before = git('rev-parse', 'HEAD')
    target = git('rev-parse', 'refs/remotes/origin/main')
    if before == target:
        print('Already up to date; no restart needed', flush=True)
        return False
    # Refuse divergent history and local commits instead of overwriting them.
    git('merge-base', '--is-ancestor', before, target)
    was_active = systemctl('is-active', '--quiet', check=False).returncode == 0
    try:
        if was_active:
            systemctl('stop')
        git('merge', '--ff-only', target)
    finally:
        # Restore a running display even if merging fails (e.g. untracked conflicts).
        if was_active:
            systemctl('start')
    print(f'Updated {before[:12]} -> {target[:12]}', flush=True)
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', required=True)
    parser.add_argument('--user', required=True)
    parser.add_argument('--service', default='campsites.service')
    args = parser.parse_args()
    with open('/run/lock/campsites-auto-update.lock', 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        update(args.repo, args.user, args.service)


if __name__ == '__main__':
    main()
