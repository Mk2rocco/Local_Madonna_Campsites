import unittest
from button_refresh import RefreshHold
from button_update import ButtonUpdateChord
class Timer:
    def __init__(self, delay, callback): self.delay, self.callback = delay, callback
    def start(self): pass
    def cancel(self): pass
    def fire(self): self.callback()
class RefreshTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.hold = RefreshHold(lambda: self.calls.append('refresh'), timer_factory=Timer)
    def test_short_press(self):
        self.hold.press(); timer = self.hold.timer
        self.assertEqual(timer.delay, 5)
        self.assertTrue(self.hold.release()); timer.fire()
        self.assertEqual(self.calls, [])
    def test_hold_once_and_rearm(self):
        self.hold.press(); timer = self.hold.timer; timer.fire(); timer.fire()
        self.assertEqual(self.calls, ['refresh']); self.assertFalse(self.hold.release())
        self.hold.press(); self.hold.timer.fire(); self.assertEqual(len(self.calls), 2)
    def test_chord_cancels_both_orders(self):
        for order in [('A','D'),('D','A')]:
            chord = ButtonUpdateChord(callback=lambda: self.calls.append('software'), timer_factory=Timer)
            stale = None
            for name in order:
                chord.press(name)
                if name == 'A' and not chord.suppress_selection:
                    self.hold.press(); stale = self.hold.timer
                else: self.hold.close()
            if stale: stale.fire()
            chord.timer.fire()
            self.assertEqual(self.calls[-1], 'software'); self.assertNotIn('refresh', self.calls)
            self.assertFalse(self.hold.release()); self.assertFalse(chord.release('A')); self.assertFalse(chord.release('D'))
    def test_stale_timer(self):
        self.hold.press(); old = self.hold.timer; self.hold.release(); self.hold.press(); old.fire()
        self.assertEqual(self.calls, []); self.hold.timer.fire(); self.assertEqual(self.calls, ['refresh'])

class RefreshWorkerTests(unittest.TestCase):
    def test_manual_refresh_forces_all_views_and_redraws(self):
        import ast
        import threading
        from pathlib import Path
        from unittest.mock import Mock
        tree = ast.parse(Path('local_madonna_sites.py').read_text())
        worker = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == '_render_thread')
        namespace = dict(manual_refresh=Mock(), refresh_busy=threading.Event(),
                         render_lock=threading.Lock(), cache_lock=threading.Lock(),
                         refresh=7200, cross_refresh=7200, cached_images={},
                         render_all_pngs=Mock(return_value={'madonna':'fresh'}),
                         _refresh_advisories=Mock(), redraw_needed=threading.Event(), log=Mock())
        namespace['manual_refresh'].wait.side_effect = [True, SystemExit]
        exec(compile(ast.fix_missing_locations(ast.Module(body=[worker], type_ignores=[])), '<worker>', 'exec'), namespace)
        with self.assertRaises(SystemExit): namespace['_render_thread']()
        namespace['manual_refresh'].wait.assert_called_with(timeout=7200)
        namespace['render_all_pngs'].assert_called_once_with(force=True, refresh_window=7200)
        namespace['_refresh_advisories'].assert_called_once_with()
        self.assertEqual(namespace['cached_images']['madonna'], 'fresh')
        self.assertTrue(namespace['redraw_needed'].is_set())
        self.assertFalse(namespace['refresh_busy'].is_set())
