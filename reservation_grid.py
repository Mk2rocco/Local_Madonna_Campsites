"""Read the public reservation grid, including its legacy table format."""
import re
import requests
from bs4 import BeautifulSoup


def cell_status(classes):
    """Return a known overnight status; never infer availability from blank text."""
    classes = set(classes)
    if classes & {"closedSite", "td_cell_block_closed", "td_cell_closed",
                  "td_cell_startClosure", "td_cell_PubClosure"}:
        return "closed"
    if classes & {"cell_booked", "td_cell_booked", "td_cell_temp_hold",
                  "td_cell_in_cart", "td_cell_block_departOK"}:
        # Departure-only dates cannot be used as an overnight arrival.
        return "reserved"
    if classes & {"cell_block", "td_cell_block_available",
                  "td_cell_block_available_ADA", "td_cell_block_available_walkup"}:
        return "vacant"
    return "unknown"


def parse_grid(html, target_label):
    """Return (site label, status) pairs for a matching weekday/day column.

    Missing dates and unknown cells are omitted rather than silently reading
    the first column or reporting an unrecognized cell as vacant.
    """
    soup = BeautifulSoup(html, "html.parser")
    tables = soup.select("table#grid_table, table#site_grid_table, table.data_table")
    if not tables:
        table = soup.find("table")
        tables = [table] if table else []
    return [site for table in tables for site in _parse_table(table, target_label)]


def _parse_table(table, target_label):
    thead = table.find("thead")
    header_rows = thead.find_all("tr") if thead else table.find_all("tr")[:1]
    if not header_rows:
        return []

    def date_key(text):
        match = re.fullmatch(r"\s*([A-Za-z]{3})\s+(?:\d{1,2}/)?(\d{1,2})\s*", text)
        return (match[1].lower(), int(match[2])) if match else None

    target = date_key(target_label)
    if target is None:
        return []
    headers = header_rows[-1].find_all(["th", "td"], recursive=False)
    column = next((i for i, h in enumerate(headers)
                   if date_key(h.get_text(" ", strip=True)) == target), None)
    if column is None:
        return []
    tbody = table.find("tbody")
    rows = tbody.find_all("tr", recursive=False) if tbody else table.find_all("tr")[1:]
    result = []
    for row in rows:
        cells = row.find_all(["th", "td"], recursive=False)
        if not cells or column >= len(cells):
            continue
        name = cells[0].select_one("[data-site_idno]")
        # New labels append a campground description after two nonbreaking spaces.
        raw_label = name.get_text() if name else cells[0].get_text(" ", strip=True)
        label = " ".join(raw_label.strip().split("\xa0\xa0", 1)[0].split())
        status = cell_status(cells[column].get("class", []))
        if label and status != "unknown":
            result.append((label, status))
    return result


def load_grids(url, params, *, timeout, headers):
    """Load camping and picnic grids, which the new site serves separately."""
    tables = []
    for reservation_type in ("camping", "day_use"):
        query = dict(params, reservation_type=reservation_type)
        response = requests.get(url, params=query, timeout=timeout, headers=headers)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        table = soup.find("table", id="grid_table") or soup.find("table", class_="data_table")
        if table is None:
            raise ValueError("Reservation table missing for " + reservation_type)
        tables.append(str(table))
    return "\n".join(tables)
