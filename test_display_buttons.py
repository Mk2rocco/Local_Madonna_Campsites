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
                            Button=button, auto_detect_inky=Mock(return_value=inky),
                            ButtonUpdateChord=Mock(return_value=chord),
                            render_all_pngs=Mock(return_value={'madonna': Image.new('RGB', (800, 480))})):
            display.run_inky_display(loop=False)
        self.assertEqual(set(buttons), {5, 6, 16, 24})
        self.assertEqual(chord.press.call_args_list, [call('A'), call('D')])
        self.assertEqual(chord.release.call_args_list, [call('D'), call('A')])
        chord.close.assert_called_once()
        for button in buttons.values():
            button.close.assert_called_once()


if __name__ == '__main__':
    unittest.main()
