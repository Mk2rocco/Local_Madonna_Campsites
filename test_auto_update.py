"""Exercise the updater against real temporary Git repositories."""
import getpass
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from scripts import update_campsites as updater
from scripts.install_auto_update import quote


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.remote, self.seed, self.repo = [root / name for name in ('remote', 'seed', 'pi')]
        self.real_run = subprocess.run
        self.git('init', '--bare', '--initial-branch=main', str(self.remote))
        self.git('clone', str(self.remote), str(self.seed))
        for key, value in [('user.name', 'Test'), ('user.email', 'test@example.com')]:
            self.git('-C', str(self.seed), 'config', key, value)
        (self.seed / 'app.py').write_text('version = 1\n')
        self.git('-C', str(self.seed), 'add', '.')
        self.git('-C', str(self.seed), 'commit', '-m', 'initial')
        self.git('-C', str(self.seed), 'push', 'origin', 'main')
        self.git('clone', str(self.remote), str(self.repo))
        self.calls = []
        self.active = True

    def git(self, *args):
        return self.real_run(['git', *args], check=True, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True).stdout.strip()

    def publish(self):
        (self.seed / 'app.py').write_text('version = 2\n')
        self.git('-C', str(self.seed), 'commit', '-am', 'update')
        self.git('-C', str(self.seed), 'push', 'origin', 'main')

    def run_update(self):
        def run(args, **kwargs):
            if args[0] == 'systemctl':
                self.calls.append(args[1])
                return subprocess.CompletedProcess(args, 0 if self.active else 3)
            return self.real_run(args, **kwargs)
        with patch.object(updater.subprocess, 'run', side_effect=run):
            return updater.update(str(self.repo), getpass.getuser())

    def test_no_update_does_not_restart(self):
        self.assertFalse(self.run_update())
        self.assertEqual(self.calls, [])

    def test_fast_forward_stops_and_restarts_active_service(self):
        self.publish()
        self.assertTrue(self.run_update())
        self.assertEqual((self.repo / 'app.py').read_text(), 'version = 2\n')
        self.assertEqual(self.calls, ['is-active', 'stop', 'start'])

    def test_inactive_service_stays_inactive(self):
        self.publish()
        self.active = False
        self.assertTrue(self.run_update())
        self.assertEqual(self.calls, ['is-active'])

    def test_dirty_checkout_is_preserved(self):
        self.publish()
        (self.repo / 'app.py').write_text('local edits\n')
        with self.assertRaises(ValueError):
            self.run_update()
        self.assertEqual((self.repo / 'app.py').read_text(), 'local edits\n')
        self.assertEqual(self.calls, [])

    def test_other_branch_is_preserved(self):
        self.git('-C', str(self.repo), 'switch', '-c', 'work')
        with self.assertRaises(ValueError):
            self.run_update()
        self.assertEqual(self.calls, [])

    def test_divergent_history_is_preserved(self):
        self.publish()
        self.git('-C', str(self.repo), '-c', 'user.name=Test', '-c',
                 'user.email=test@example.com', 'commit', '--allow-empty', '-m', 'local')
        before = self.git('-C', str(self.repo), 'rev-parse', 'HEAD')
        with self.assertRaises(subprocess.CalledProcessError):
            self.run_update()
        self.assertEqual(self.git('-C', str(self.repo), 'rev-parse', 'HEAD'), before)
        self.assertEqual(self.calls, [])

    def test_fetch_failure_leaves_display_running(self):
        self.git('-C', str(self.repo), 'remote', 'set-url', 'origin', '/missing-repo')
        with self.assertRaises(subprocess.CalledProcessError):
            self.run_update()
        self.assertEqual(self.calls, [])

    def test_merge_conflict_restores_service(self):
        (self.seed / 'new.py').write_text('upstream\n')
        self.git('-C', str(self.seed), 'add', '.')
        self.git('-C', str(self.seed), 'commit', '-m', 'new file')
        self.git('-C', str(self.seed), 'push', 'origin', 'main')
        (self.repo / 'new.py').write_text('untracked local file\n')
        with self.assertRaises(subprocess.CalledProcessError):
            self.run_update()
        self.assertEqual(self.calls, ['is-active', 'stop', 'start'])
        self.assertEqual((self.repo / 'new.py').read_text(), 'untracked local file\n')

    def test_systemd_quoting(self):
        self.assertEqual(quote('/a path/100%'), '"/a path/100%%"')


if __name__ == '__main__':
    unittest.main()
