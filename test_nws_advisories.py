"""Detailed NWS coverage: text preservation, pagination, error states and cadence."""
from datetime import datetime, timezone
import unittest
from unittest.mock import Mock, patch
from PIL import Image, ImageDraw
from nws_advisories import AdvisoryProgram, REFRESH_SECONDS, advisory_text, font, render_pages, wrap_text

ALERT = {'event': 'Wind Advisory', 'headline': 'Strong winds expected overnight',
         'areaDesc': 'Santa Cruz Mountains', 'severity': 'Moderate', 'urgency': 'Expected',
         'certainty': 'Likely', 'onset': '2026-11-14T22:00:00Z',
         'expires': '2026-11-15T18:00:00Z',
         'description': 'Strong gusts could bring down branches.',
         'instruction': 'Secure loose outdoor objects.'}


def response(features):
    return Mock(json=Mock(return_value={'features': [{'properties': a} for a in features]}))


class AdvisoryTests(unittest.TestCase):
    def test_complete_details_are_preserved_across_pages(self):
        alert = dict(ALERT, description=' '.join(f'word{i}' for i in range(1800)),
                     instruction='FINAL INSTRUCTION: Stay clear of trees.')
        with patch('PIL.ImageDraw.ImageDraw.text', autospec=True) as text:
            pages = render_pages([alert], fetched_at=datetime.now(timezone.utc))
        drawn = ' '.join(c.args[2] for c in text.call_args_list)
        self.assertGreater(len(pages), 1)
        for word in alert['description'].split():
            self.assertIn(word, drawn)
        self.assertIn(alert['instruction'], drawn)
        self.assertIn('Affected area: Santa Cruz Mountains', drawn)
        self.assertEqual({p.size for p in pages}, {(800, 480)})
        self.assertIn(f'Page {len(pages)}/{len(pages)}', drawn)

    def test_no_advisory_and_failure_are_distinct(self):
        with patch('PIL.ImageDraw.ImageDraw.text', autospec=True) as text:
            render_pages([])
        self.assertIn('No active NWS advisories.', ' '.join(c.args[2] for c in text.call_args_list))
        self.assertIn('for Mount Madonna.', ' '.join(c.args[2] for c in text.call_args_list))
        with patch('PIL.ImageDraw.ImageDraw.text', autospec=True) as text:
            render_pages([], error='HTTP error')
        drawn = ' '.join(c.args[2] for c in text.call_args_list)
        self.assertIn('Unable to retrieve NWS advisories.', drawn)
        self.assertNotIn('No active NWS advisories.', drawn)

    def test_every_advisory_is_included(self):
        second = dict(ALERT, event='Flood Warning', instruction='SECOND FINAL INSTRUCTION')
        with patch('PIL.ImageDraw.ImageDraw.text', autospec=True) as text:
            render_pages([ALERT, second])
        drawn = ' '.join(c.args[2] for c in text.call_args_list)
        self.assertIn('Wind Advisory', drawn)
        self.assertIn('Flood Warning', drawn)
        self.assertIn('SECOND FINAL INSTRUCTION', drawn)

    def test_long_unbroken_text_is_split_without_loss(self):
        word = 'https://example.com/' + 'x' * 500
        draw = ImageDraw.Draw(Image.new('RGB', (800, 480)))
        lines = wrap_text(word, draw, font(16), 200)
        self.assertEqual(''.join(lines), word)
        self.assertTrue(all(draw.textlength(line, font=font(16)) <= 200 for line in lines))

    @patch('nws_advisories.requests.get')
    def test_cache_refreshes_at_two_hours(self, get):
        self.assertEqual(REFRESH_SECONDS, 7200)
        get.return_value = response([ALERT])
        program = AdvisoryProgram()
        with patch('nws_advisories.time.monotonic', side_effect=[0, 7199, 7200]):
            program.pages()
            program.pages()
            self.assertEqual(get.call_count, 1)
            program.pages()
        self.assertEqual(get.call_count, 2)
        self.assertEqual(get.call_args.kwargs['params']['point'], '37.01144811108972,-121.70544157229918')

    @patch('nws_advisories.requests.get')
    def test_failed_refresh_keeps_and_labels_last_success(self, get):
        get.return_value = response([ALERT])
        program = AdvisoryProgram()
        program.pages(force=True)
        fetched = program.fetched_at
        get.side_effect = OSError('offline')
        with patch('PIL.ImageDraw.ImageDraw.text', autospec=True) as text:
            program.pages(force=True)
        drawn = ' '.join(c.args[2] for c in text.call_args_list)
        self.assertEqual(program.fetched_at, fetched)
        self.assertIn('Last successful data shown', drawn)
        self.assertIn('Wind Advisory', drawn)

    @patch('nws_advisories.requests.get')
    def test_invalid_response_is_not_no_advisory(self, get):
        get.return_value = Mock(json=Mock(return_value={'error': 'problem'}))
        program = AdvisoryProgram()
        program.pages(force=True)
        self.assertIsNotNone(program.error)
        self.assertIsNone(program.fetched_at)

    @patch('nws_advisories.requests.get')
    def test_test_alerts_and_cancel_messages_are_excluded(self, get):
        get.return_value = response([ALERT, dict(ALERT, status='Test'), dict(ALERT, messageType='Cancel')])
        program = AdvisoryProgram()
        program.pages(force=True)
        self.assertEqual(program.alerts, [ALERT])


if __name__ == '__main__':
    unittest.main()
