"""Check button wiring in the display loop using simulated GPIO/display devices."""
import unittest
from unittest.mock import Mock, patch, call
from PIL import Image
import local_madonna_sites as display


class DisplayButtonTests(unittest.TestCase):
    def test_all_four_buttons_bind_and_update_chord_is_connected(self):
        buttons = {}
        def button(pin, **kwargs):
            buttons[pin] = Mock()
            return buttons[pin]
        chord = Mock()
        chord.release.return_value = False
        inky = Mock(width=800, height=480)
        def during_show():
            buttons[5].when_pressed()
            buttons[24].when_pressed()
            buttons[24].when_released()
            buttons[5].when_released()
            buttons[6].when_pressed()
            buttons[16].when_pressed()
        inky.show.side_effect = during_show
        with patch.multiple(display, _INKY_AVAILABLE=True, _INKY_BUTTONS_AVAILABLE=True,
                            _USER_LED_AVAILABLE=False, INKY_REFRESH_SECONDS=0,
                            BlockingButtons=Mock(return_value=Mock(button=button)), auto_detect_inky=Mock(return_value=inky),
                            ButtonUpdateChord=Mock(return_value=chord),
                            AdvisoryProgram=Mock(return_value=Mock(pages=Mock(return_value=[Image.new('RGB', (800, 480))]))),
                            render_all_pngs=Mock(return_value={'madonna': Image.new('RGB', (800, 480))})):
            display.run_inky_display(loop=False)
        self.assertEqual(set(buttons), {5, 6, 16, 24})
        self.assertEqual(chord.press.call_args_list, [call('A'), call('D')])
        self.assertEqual(chord.release.call_args_list, [call('D'), call('A')])
        chord.close.assert_called_once()
        for button in buttons.values():
            button.close.assert_called_once()

    def test_d_cycles_advisories_and_a_b_preserve_views(self):
        buttons = {}
        def button(pin, **kwargs):
            buttons[pin] = Mock()
            return buttons[pin]
        inky = Mock(width=800, height=480)
        def tap(pin):
            buttons[pin].when_pressed()
            if pin in (5, 6, 16, 24):
                buttons[pin].when_released()
        actions = [lambda: tap(24), lambda: tap(24), lambda: tap(24),
                   lambda: tap(6), lambda: tap(5)]
        def during_show():
            if actions:
                actions.pop(0)()
            else:
                raise KeyboardInterrupt()
        inky.show.side_effect = during_show
        image = lambda shade: Image.new('RGB', (800, 480), (shade, shade, shade))
        program = Mock(pages=Mock(return_value=[image(50), image(100)]))
        with patch.multiple(display, _INKY_AVAILABLE=True, _INKY_BUTTONS_AVAILABLE=True,
                            _USER_LED_AVAILABLE=False, INKY_REFRESH_SECONDS=0,
                            BlockingButtons=Mock(return_value=Mock(button=button)), auto_detect_inky=Mock(return_value=inky),
                            RefreshHold=Mock(return_value=Mock(release=Mock(return_value=True))),
                            AdvisoryProgram=Mock(return_value=program),
                            render_all_pngs=Mock(return_value={'madonna': image(0), 'group': image(150)})):
            with patch('local_madonna_sites.threading.Thread'):
                display.run_inky_display(loop=True)
        shown = [c.args[0].getpixel((0, 0))[0] for c in inky.set_image.call_args_list]
        self.assertEqual(shown, [0, 50, 100, 50, 150, 0])
        program.pages.assert_called_once_with(width=800, height=480)

    def test_advisory_refresh_thread_runs_every_two_hours_independently(self):
        inky = Mock(width=800, height=480)
        image = Image.new('RGB', (800, 480))
        program = Mock(pages=Mock(return_value=[image]))
        created = []
        def thread(**kwargs):
            created.append(kwargs['target'])
            return Mock()
        def during_show():
            # One iteration of the advisory worker, then stop its test execution.
            with patch('local_madonna_sites.time.sleep', side_effect=[None, KeyboardInterrupt()]) as sleep:
                with self.assertRaises(KeyboardInterrupt):
                    created[0]()
            self.assertEqual(sleep.call_args_list, [call(7200), call(7200)])
            raise KeyboardInterrupt()
        inky.show.side_effect = during_show
        with patch.multiple(display, _INKY_AVAILABLE=True, _INKY_BUTTONS_AVAILABLE=False,
                            _USER_LED_AVAILABLE=False, INKY_REFRESH_SECONDS=0,
                            auto_detect_inky=Mock(return_value=inky),
                            RefreshHold=Mock(return_value=Mock(release=Mock(return_value=True))),
                            AdvisoryProgram=Mock(return_value=program),
                            render_all_pngs=Mock(return_value={'madonna': image})):
            with patch('local_madonna_sites.threading.Thread', side_effect=thread):
                display.run_inky_display(loop=True)
        self.assertEqual(program.pages.call_args_list,
                         [call(width=800, height=480), call(force=True, width=800, height=480)])


if __name__ == '__main__':
    unittest.main()



class AllButtonHoldTests(unittest.TestCase):
    def test_every_single_button_requests_refresh_only_after_hold(self):
        from functools import partial
        from button_refresh import RefreshHold
        from test_button_refresh import Timer
        for pin in (5, 6, 16, 24):
            with self.subTest(pin=pin):
                buttons, holds = {}, []
                def button(number, **kwargs):
                    buttons[number] = Mock()
                    return buttons[number]
                def hold(callback):
                    h = RefreshHold(callback, timer_factory=Timer)
                    holds.append(h)
                    return h
                inky = Mock(width=800, height=480)
                def during_show():
                    buttons[pin].when_pressed()
                    active = next(h for h in holds if h.pressed)
                    active.timer.fire()
                    buttons[pin].when_released()
                inky.show.side_effect = during_show
                with patch.multiple(display, _INKY_AVAILABLE=True, _INKY_BUTTONS_AVAILABLE=True,
                                    _USER_LED_AVAILABLE=False, INKY_REFRESH_SECONDS=0,
                                    BlockingButtons=Mock(return_value=Mock(button=button)),
                                    auto_detect_inky=Mock(return_value=inky), RefreshHold=hold,
                                    AdvisoryProgram=Mock(return_value=Mock(pages=Mock(return_value=[Image.new('RGB',(800,480))]))),
                                    render_all_pngs=Mock(return_value={'madonna':Image.new('RGB',(800,480))}), log=Mock()):
                    display.run_inky_display(loop=False)
                    display.log.info.assert_any_call('Single button held for 5 seconds: requesting immediate data refresh')
                    self.assertFalse(any(c.args and c.args[0] == 'NWS advisory page %s/%s selected' for c in display.log.info.call_args_list))
