"""Regression tests for the redesigned public availability grid."""
import unittest
from datetime import datetime
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlparse
from reservation_grid import parse_grid, cell_status, load_grids
import local_madonna_sites as local
import madonna_group_sites as group
import uvas_canyon_reservations as uvas

GRID = '''<table><tr><td>Layout table</td></tr></table>
<table id="grid_table"><tbody>
<tr><th><span data-site_idno="1">101&nbsp;&nbsp;Valley View 1</span></th>
<td class="td_cell_booked">X</td><td class="td_cell_block_available">$35</td></tr>
<tr><th><span data-site_idno="2">MANZANITA&nbsp;&nbsp;Group Camping</span></th>
<td class="td_cell_block_closed"></td><td class="td_cell_booked">X</td></tr>
<tr><th><span data-site_idno="3">201&nbsp;&nbsp;Valley View 2</span></th>
<td class="td_cell_block_available_ADA">$35</td><td class="td_cell_block_closed"></td></tr>
<tr><th>301</th><td class="future_status"></td><td></td></tr>
</tbody><thead><tr><th></th><th>Sat<span>11/14</span></th>
<th>Sun<span>11/15</span></th></tr></thead></table>'''

class GridTests(unittest.TestCase):
    def test_current_grid(self):
        self.assertEqual(parse_grid(GRID, 'Sat 14'),
            [('101', 'reserved'), ('MANZANITA', 'closed'), ('201', 'vacant')])
        self.assertEqual(parse_grid(GRID, 'Sun 15'),
            [('101', 'vacant'), ('MANZANITA', 'reserved'), ('201', 'closed')])

    def test_missing_date_or_grid(self):
        self.assertEqual(parse_grid(GRID, 'Mon 16'), [])
        self.assertEqual(parse_grid('<html>Maintenance</html>', 'Sat 14'), [])
        self.assertEqual(parse_grid('<table><tbody></tbody></table>', 'Sat 14'), [])

    def test_legacy_grid(self):
        html = '''<table id="site_grid_table"><thead><tr><th>Site</th><th>Sat 14</th>
        </tr></thead><tbody><tr><td>101</td><td class="cell_block"></td></tr>
        <tr><td>102</td><td class="cell_block cell_booked">X</td></tr>
        <tr><td>103</td><td class="cell_block closedSite"></td></tr></tbody></table>'''
        self.assertEqual(parse_grid(html, 'Sat 14'),
            [('101', 'vacant'), ('102', 'reserved'), ('103', 'closed')])

    def test_unavailable_and_unknown_states(self):
        for state in ['td_cell_booked', 'td_cell_temp_hold', 'td_cell_in_cart',
                      'td_cell_block_departOK']:
            self.assertEqual(cell_status([state]), 'reserved')
        self.assertEqual(cell_status(['td_cell_startClosure']), 'closed')
        self.assertEqual(cell_status(['future_status']), 'unknown')
        self.assertEqual(cell_status(['cell_block', 'closedSite', 'cell_booked']), 'closed')

    def test_views(self):
        statuses = local.parse_number_site_status(GRID, 'Sat 14')
        self.assertEqual(statuses['Valley View Campground 1']['reserved'], ['101'])
        self.assertEqual(statuses['Valley View Campground 2']['vacant'], ['201'])
        self.assertEqual(group.parse_group_site_statuses(GRID, 'Sat 14'), {'MANZANITA': 'Closed'})
        self.assertTrue(local.render_image(GRID, []).startswith(b'\x89PNG'))
        self.assertTrue(uvas.render_image(GRID, [], target_dt=datetime(2026, 11, 14),
                                         tomorrow_html=GRID).startswith(b'\x89PNG'))

    def test_separate_camping_and_picnic_grids(self):
        picnic = GRID.replace('101', '401')
        with patch('reservation_grid.requests.get') as get:
            get.side_effect = [Mock(text=GRID), Mock(text=picnic)]
            html = load_grids('https://example.com/grid', {'park_idno': '8'},
                              timeout=8, headers={})
        self.assertEqual([c.kwargs['params']['reservation_type'] for c in get.call_args_list],
                         ['camping', 'day_use'])
        sites = parse_grid(html, 'Sat 14')
        self.assertIn(('101', 'reserved'), sites)
        self.assertIn(('401', 'reserved'), sites)

    def test_request_parameters(self):
        for module in [local, group]:
            query = parse_qs(urlparse(module.build_url(datetime(2026, 11, 14))).query)
            self.assertEqual(query['reservation_type'], ['camping'])
            self.assertNotIn('res_type', query)
        self.assertEqual(uvas.BASE_QUERY['reservation_type'], 'camping')

if __name__ == '__main__':
    unittest.main()
