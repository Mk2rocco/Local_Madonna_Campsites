#!/usr/bin/env python3
"""
Uvas Canyon Reservations renderer (library-only)
Adapted from TRMNL Uvas Canyon script for generating PNG output.
Exposes helpers to render and save the reservations PNG.
"""
from __future__ import annotations
import io
import os
import re
import time
import socket
import hashlib
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple

from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache

import requests
from PIL import Image, ImageDraw, ImageFont
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')
log = logging.getLogger("uvas-canyon")

RES_W = 800
RES_H = 480

SAFE_LEFT   = int(os.getenv("SAFE_LEFT", "32"))
SAFE_RIGHT  = int(os.getenv("SAFE_RIGHT", "32"))
SAFE_TOP    = int(os.getenv("SAFE_TOP", "10"))
SAFE_BOTTOM = int(os.getenv("SAFE_BOTTOM", "5"))
FOOTER_H    = int(os.getenv("FOOTER_H", "30"))

DATA_TIMEOUT  = float(os.getenv("DATA_TIMEOUT", "8"))
CACHE_SECONDS = int(os.getenv("CACHE_SECONDS", "300"))

OUTPUT = os.getenv("OUTPUT_UVAS", os.path.join(os.getcwd(), "render_uvas.png"))


def _slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")


PARK_PRESETS = {
    "uvas_canyon": {
        "park_id": "12",
        "titles": {
            "available": "Uvas Canyon Reservations",
            "reserved": "Uvas Canyon Reservations",
            "closed": "Uvas Canyon Reservations",
        },
    },
}

PARK_SLUG = _slugify(os.getenv("PARK", "uvas_canyon") or "uvas_canyon")
_PARK_CONFIG = PARK_PRESETS.get(PARK_SLUG, PARK_PRESETS["uvas_canyon"])
_PRESET_TITLES = _PARK_CONFIG["titles"]

TITLE_AVAILABLE = os.getenv(
    "TITLE_AVAILABLE",
    os.getenv("TITLE", _PRESET_TITLES["available"]),
)
TITLE_RESERVED = os.getenv("TITLE_RESERVED", _PRESET_TITLES["reserved"])
TITLE_CLOSED = os.getenv("TITLE_CLOSED", _PRESET_TITLES["closed"])
SUBTITLE    = os.getenv("SUBTITLE", "")
FONT_SCALE  = float(os.getenv("FONT_SCALE", "1.0"))
TITLE_SCALE = float(os.getenv("TITLE_SCALE", "1.10"))
LINE_SPACING  = float(os.getenv("LINE_SPACING", "1.35"))
GROUP_SPACING = int(os.getenv("GROUP_SPACING", "14"))
NUM_INDENT    = int(os.getenv("NUM_INDENT", "12"))
TITLE_ALIGN   = os.getenv("TITLE_ALIGN", "center")

FOOTER_PREFIX = os.getenv("FOOTER_PREFIX", "Pulled:").strip()
FOOTER_TIME_FORMAT = os.getenv("FOOTER_TIME_FORMAT", "%Y-%m-%d %H:%M:%S %Z")
NWS_LAT = float(os.getenv("NWS_LAT", "37.084716794532795"))
NWS_LON = float(os.getenv("NWS_LON", "-121.79253369564738"))
NWS_USER_AGENT = os.getenv(
    "NWS_USER_AGENT",
    "uvas-canyon-reservations/1.0 (admin@example.com)",
)

PARK_ID    = os.getenv("PARK_ID", _PARK_CONFIG["park_id"])
TZ_NAME    = os.getenv("TZ_NAME", "America/Los_Angeles")
DITHER     = int(os.getenv("DITHER", "0"))


try:
    from zoneinfo import ZoneInfo
except Exception:
    ZoneInfo = None


def _resolve_tz(name: str):
    if ZoneInfo is not None:
        try:
            return ZoneInfo(name)
        except Exception:
            pass
    try:
        from dateutil.tz import gettz
        tz = gettz(name)
        if tz:
            return tz
    except Exception:
        pass
    log.warning("TZ %s unavailable; using UTC.", name)
    return timezone.utc


LOCAL_TZ = _resolve_tz(TZ_NAME)


def _day_label(dt: datetime) -> str:
    return dt.strftime("%a %d").replace(" 0", " ")


def _mmddyyyy(dt: datetime) -> str:
    return dt.strftime("%m/%d/%Y")


def _ymd_to_mmddyyyy(ymd_str: str) -> str:
    y, m, d = map(int, ymd_str.split(","))
    return f"{m:02d}/{d:02d}/{y:04d}"


BASE_TITLE         = int(28 * FONT_SCALE)
BASE_H2            = int(18 * FONT_SCALE)
BASE_COLUMN_HEADER = int(21 * FONT_SCALE)
BASE_BODY          = int(19 * FONT_SCALE)

FONT_PATHS = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/System/Library/Fonts/SFNS.ttf",
    "/Library/Fonts/Arial.ttf",
)

FONT_PATHS_BOLD = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/System/Library/Fonts/SFNSDisplay-Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
)


def _load_font_from_paths(paths: Tuple[str, ...], size: int) -> Optional[ImageFont.ImageFont]:
    for path in paths:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return None


@lru_cache(maxsize=None)
def load_font(size: int) -> ImageFont.ImageFont:
    return _load_font_from_paths(FONT_PATHS, size) or ImageFont.load_default()


@lru_cache(maxsize=None)
def load_font_bold(size: int) -> ImageFont.ImageFont:
    return _load_font_from_paths(FONT_PATHS_BOLD, size) or load_font(size)


H1_SIZE = int(BASE_TITLE * TITLE_SCALE)


def H1():
    return load_font(H1_SIZE)


def H2():
    return load_font(BASE_H2)


def BODY():
    return load_font(BASE_BODY)


def COLUMN_HEADER_FONT():
    return load_font_bold(BASE_COLUMN_HEADER)


BASE_URL = "https://gooutsideandplay.org"
GRID_PATH = "/reservations/sites_grid_pub.asp"
BASE_QUERY = {
    "res_type": "QQQ",
    "park_idno": PARK_ID,
}
DAY_USE_CATEGORY_ID = os.getenv("DAY_USE_CATEGORY_ID", "1081134")


def load_table_for_date(for_dt: datetime) -> Optional[str]:
    params = dict(BASE_QUERY)
    params["StartDate"] = _mmddyyyy(for_dt)
    url = f"{BASE_URL}{GRID_PATH}"
    headers = {"User-Agent": "trmnl-avail/1.0"}
    response = requests.get(url, params=params, timeout=DATA_TIMEOUT, headers=headers)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    table = soup.find("table", {"class": "data_table"})
    if table is None:
        log.warning("No reservation table found for %s", params["StartDate"])
        return None
    return str(table)


_last_payload: Optional[str] = None
_last_fetched_utc: Optional[datetime] = None
_last_error: Optional[str] = None
_last_advisories: List[str] = []


def fetch_html(for_dt: datetime) -> Optional[str]:
    global _last_payload, _last_fetched_utc, _last_error
    try:
        payload = load_table_for_date(for_dt)
        if payload is None:
            raise RuntimeError("Reservation table missing")
        _last_payload = payload
        _last_fetched_utc = datetime.now(timezone.utc)
        _last_error = None
        return _last_payload
    except Exception as e:
        _last_error = str(e)
        log.error("Fetch failed: %s", e)
        return _last_payload


def fetch_day_use_remaining(for_dates: List[datetime]) -> Dict[datetime.date, Optional[int]]:
    if not for_dates:
        return {}

    category_url = f"{BASE_URL}/reservations/product.asp"
    params = {"CategoryID": DAY_USE_CATEGORY_ID}
    session = requests.Session()
    session.headers.update({"User-Agent": "trmnl-dayuse/1.0"})

    deadline = time.time() + max(DATA_TIMEOUT, 1.0)
    deadline_hit = False

    def remaining_timeout() -> float:
        remaining = deadline - time.time()
        if remaining <= 0:
            return 1.0
        return min(DATA_TIMEOUT, max(1.0, remaining))

    def deadline_reached() -> bool:
        nonlocal deadline_hit
        if time.time() > deadline:
            deadline_hit = True
            return True
        return False

    try:
        if deadline_reached():
            raise TimeoutError("Day use fetch deadline exceeded before category request")
        resp = session.get(category_url, params=params, timeout=remaining_timeout())
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
    except TimeoutError:
        log.warning(
            "Day use availability fetch exceeded %.1fs deadline before category load",
            DATA_TIMEOUT,
        )
        return {dt.date(): None for dt in for_dates}
    except Exception as exc:
        log.error("Day use category fetch failed: %s", exc)
        return {dt.date(): None for dt in for_dates}

    forms = soup.select("form[action='Product_Cart_AddItems.asp']")
    if not forms:
        return {dt.date(): None for dt in for_dates}

    target_map: Dict[str, datetime] = {}
    totals: Dict[str, int] = {}
    found: Dict[str, bool] = {}
    for dt in for_dates:
        key = _mmddyyyy(dt)
        target_map[key] = dt
        totals[key] = 0
        found[key] = False

    for form in forms:
        if deadline_reached():
            break
        pid_input = form.select_one("input[name='product_idno']")
        if not pid_input:
            continue
        product_id = (pid_input.get("value") or "").strip()
        if not product_id:
            continue

        dates_url = f"{BASE_URL}/reservations/get_ticket_dates_ajax.asp"
        query = {"prod_idno": product_id, "Qty": 1, "location_code_idno": 0}
        try:
            if deadline_reached():
                break
            date_payload = session.get(dates_url, params=query, timeout=remaining_timeout())
            date_payload.raise_for_status()
            dates = date_payload.json()
        except Exception as exc:
            log.error("Day use dates fetch failed for %s: %s", product_id, exc)
            continue

        for item in dates or []:
            if deadline_reached():
                break
            event_date = item.get("event_date")
            if not event_date:
                continue
            try:
                mmddyyyy = _ymd_to_mmddyyyy(event_date)
            except Exception:
                continue
            if mmddyyyy not in target_map:
                continue

            rem_url = f"{BASE_URL}/reservations/get_remaining_tix_ajax.asp"
            try:
                if deadline_reached():
                    break
                remaining_resp = session.post(
                    rem_url,
                    data={"prod_idno": product_id, "date_time": mmddyyyy},
                    timeout=remaining_timeout(),
                )
                remaining_resp.raise_for_status()
            except Exception as exc:
                log.error("Day use remaining fetch failed for %s: %s", product_id, exc)
                continue

            remaining_str = remaining_resp.text.strip()
            digits = re.sub(r"[^\d-]", "", remaining_str)
            if not digits:
                continue
            try:
                remaining = int(digits)
            except Exception:
                continue

            totals[mmddyyyy] += max(0, remaining)
            found[mmddyyyy] = True

        if deadline_hit:
            break

    if deadline_hit:
        log.warning(
            "Day use availability fetch exceeded %.1fs deadline; returning partial data",
            DATA_TIMEOUT,
        )
    results: Dict[datetime.date, Optional[int]] = {}
    for key, dt in target_map.items():
        results[dt.date()] = totals[key] if found[key] else None
    return results


def fetch_weather_advisories() -> List[str]:
    global _last_advisories
    url = f"https://api.weather.gov/alerts/active?point={NWS_LAT},{NWS_LON}"
    headers = {
        "User-Agent": NWS_USER_AGENT,
        "Accept": "application/geo+json",
    }
    try:
        resp = requests.get(url, timeout=DATA_TIMEOUT, headers=headers)
        resp.raise_for_status()
        payload = resp.json()
    except Exception as exc:
        log.error("Weather fetch failed: %s", exc)
        _last_advisories = ["Error"]
        return _last_advisories

    features = payload.get("features") or []
    advisories: List[str] = []
    for feature in features:
        props = feature.get("properties") or {}
        headline = props.get("headline") or props.get("event")
        if headline:
            advisories.append(" ".join(headline.split()))

    _last_advisories = advisories
    return _last_advisories


@dataclass(frozen=True)
class SiteStatus:
    label: str
    status: str

    @property
    def is_group_site(self) -> bool:
        stripped = self.label.strip()
        return bool(stripped and not stripped[0].isdigit())

    @property
    def is_all_letters(self) -> bool:
        stripped = self.label.strip()
        return bool(stripped) and stripped.isalpha()

    @property
    def has_number(self) -> bool:
        return any(ch.isdigit() for ch in self.label)


STATUS_CLASS_WHITELIST = {"cell_block", "cell_booked", "closedSite"}
STATUS_MAP = {
    ("cell_block",): "vacant",
    ("cell_block", "cell_booked"): "reserved",
    ("cell_block", "closedSite"): "closed",
}


def _normalize_status(class_list: List[str]) -> str:
    classes = tuple(sorted(c for c in class_list if c in STATUS_CLASS_WHITELIST))
    if not classes:
        return "unknown"
    for key, val in STATUS_MAP.items():
        if tuple(sorted(key)) == classes:
            return val
    if "cell_booked" in classes:
        return "reserved"
    if "closedSite" in classes:
        return "closed"
    if "cell_block" in classes:
        return "vacant"
    return "unknown"


def _site_sort_key(label: str) -> Tuple[int, str, str]:
    label = label.strip()
    num_match = re.match(r"(\d+)", label)
    if num_match:
        return (0, f"{int(num_match.group(1)):03d}", label)
    return (1, label.lower(), label)


def wrap_list(draw: ImageDraw.ImageDraw, font: ImageFont.ImageFont,
              items: List[str], max_w: int, max_lines: int = 3) -> List[str]:
    tokens = items[:]
    lines, cur = [], ""
    i = 0
    while i < len(tokens) and len(lines) < max_lines:
        t = tokens[i]
        cand = t if not cur else f"{cur}, {t}"
        if draw.textlength(cand, font=font) <= max_w:
            cur = cand; i += 1
        else:
            if cur:
                lines.append(cur); cur = ""
            else:
                s = t
                while s and draw.textlength(s + "...", font=font) > max_w:
                    s = s[:-1]
                lines.append(s + "..."); return lines
    if cur and len(lines) < max_lines:
        lines.append(cur)
    if i < len(tokens) and lines:
        last = lines[-1]
        while last and draw.textlength(last + "...", font=font) > max_w:
            last = last[:-1]
        lines[-1] = (last + "...") if last else "..."
    return lines


def finalize_1bit(img: Image.Image) -> Image.Image:
    if int(DITHER):
        bw = img.convert("1")
    else:
        bw = img.convert("1", dither=Image.NONE)
    if bw.size != (800,480):
        bw = bw.resize((800,480))
    return bw


def _fit_text(draw: ImageDraw.ImageDraw, font: ImageFont.ImageFont, text: str, max_w: int) -> str:
    if max_w <= 0:
        return ""
    text = text.strip()
    if not text:
        return ""
    if draw.textlength(text, font=font) <= max_w:
        return text
    ellipsis = "…"
    while text and draw.textlength(text + ellipsis, font=font) > max_w:
        text = text[:-1].rstrip()
    return (text + ellipsis) if text else ""


def draw_footer(draw: ImageDraw.ImageDraw, pulled_utc: Optional[datetime], advisories: List[str]):
    y0 = RES_H - SAFE_BOTTOM - FOOTER_H
    y1 = RES_H - SAFE_BOTTOM
    draw.rectangle([SAFE_LEFT, y0, RES_W - SAFE_RIGHT, y1], fill=255)

    draw.line((SAFE_LEFT, y0, RES_W - SAFE_RIGHT, y0), fill=0, width=1)

    font = H2()
    baseline = y0 + max(2, (FOOTER_H - font.size)//2)
    safe_w = (RES_W - SAFE_RIGHT) - SAFE_LEFT

    timestamp_text = ""
    if pulled_utc:
        timestamp = pulled_utc.astimezone(LOCAL_TZ).strftime(FOOTER_TIME_FORMAT)
        timestamp_text = f"{FOOTER_PREFIX} {timestamp}".strip() if FOOTER_PREFIX else timestamp

    advisory_body = " | ".join(advisories) if advisories else "None"
    advisory_text = f"NWS Advisories: {advisory_body}".strip()

    timestamp_text = _fit_text(draw, font, timestamp_text, safe_w)
    remaining = max(0, safe_w - draw.textlength(timestamp_text, font=font) - 12)
    advisory_text = _fit_text(draw, font, advisory_text, remaining)

    if timestamp_text:
        draw.text((SAFE_LEFT, baseline), timestamp_text, font=font, fill=0)

    if advisory_text:
        text_w = draw.textlength(advisory_text, font=font)
        right_x = RES_W - SAFE_RIGHT - text_w
        draw.text((right_x, baseline), advisory_text, font=font, fill=0)


def render_image(
    today_html: Optional[str],
    advisories: List[str],
    *,
    target_dt: Optional[datetime] = None,
    day_use_remaining_today: Optional[int] = None,
    tomorrow_html: Optional[str] = None,
    day_use_remaining_tomorrow: Optional[int] = None,
) -> bytes:
    img = Image.new("L", (RES_W, RES_H), 255)
    d = ImageDraw.Draw(img)

    x0, y = SAFE_LEFT, SAFE_TOP
    x1 = RES_W - SAFE_RIGHT
    safe_w = x1 - x0

    target_dt = target_dt or datetime.now(LOCAL_TZ)
    label_today = _day_label(target_dt)
    tomorrow_dt = target_dt + timedelta(days=1)
    label_tomorrow = _day_label(tomorrow_dt)

    today_table = today_html or fetch_html(target_dt)
    tomorrow_table = tomorrow_html or ""

    def collect_site_statuses(table_html: str, column_label: str) -> List[SiteStatus]:
        if not table_html:
            return []

        soup = BeautifulSoup(table_html, "html.parser")
        table = soup.find("table")
        if not table:
            return []

        thead = table.find("thead")
        header_row = None
        if thead:
            header_rows = thead.find_all("tr")
            if header_rows:
                header_row = header_rows[-1]
        if header_row is None:
            header_row = table.find("tr")
        if header_row is None:
            return []

        raw_headers = header_row.find_all(["th", "td"])
        headers = [" ".join(h.get_text(separator=" ", strip=True).split()) for h in raw_headers]
        normalized_target = re.sub(r"\s+", "", column_label.lower()) if column_label else ""
        numeric_target = re.sub(r"\D", "", column_label) if column_label else ""
        col_index: Optional[int] = None
        for idx, header in enumerate(headers):
            normalized_header = re.sub(r"\s+", "", header.lower())
            if normalized_header == normalized_target:
                col_index = idx
                break
            if numeric_target:
                header_numeric = re.sub(r"\D", "", header)
                if header_numeric and header_numeric == numeric_target:
                    col_index = idx
                    break
        if col_index is None:
            col_index = 1 if headers and headers[0].lower().startswith("site") else 0

        tbody = table.find("tbody")
        if tbody:
            data_rows = tbody.find_all("tr")
        else:
            all_rows = table.find_all("tr")
            data_rows = all_rows[1:] if len(all_rows) > 1 else []

        result: List[SiteStatus] = []
        for tr in data_rows:
            tds = tr.find_all(["td", "th"])
            if not tds:
                continue
            label = " ".join(tds[0].get_text(strip=True).split())
            if not label:
                continue
            if col_index >= len(tds):
                continue
            status = _normalize_status(tds[col_index].get("class", []))
            if status == "unknown":
                continue
            result.append(SiteStatus(label=label, status=status))

        result.sort(key=lambda s: _site_sort_key(s.label))
        return result

    sites_today = collect_site_statuses(today_table or "", label_today)
    sites_tomorrow = collect_site_statuses(tomorrow_table or "", label_tomorrow)

    reserved_sites = [s for s in sites_today if s.status == "reserved"]
    excluded_vacant_labels = {"black oak", "upper bench"}
    vacant_sites = [
        s
        for s in sites_today
        if (
            s.status == "vacant"
            and s.has_number
            and s.label.strip().lower() not in excluded_vacant_labels
        )
    ]
    closed_sites = [s for s in sites_today if s.status == "closed"]
    numbered_reserved_sites = [s for s in reserved_sites if s.has_number]
    total_vacant = len(vacant_sites)
    total_reserved = len(numbered_reserved_sites)
    total_closed = len(closed_sites)
    total_sites = len(sites_today)
    total_reservable = total_vacant + total_reserved

    if total_vacant == 0 and total_reserved == 0:
        if total_closed > 0:
            title_text = TITLE_CLOSED
        else:
            title_text = TITLE_AVAILABLE
    else:
        if total_vacant == 0:
            title_text = TITLE_RESERVED
        elif total_reserved == 0:
            title_text = TITLE_AVAILABLE
        elif total_vacant <= total_reserved:
            title_text = TITLE_AVAILABLE
        else:
            title_text = TITLE_RESERVED

    title_counts = ""
    if total_reservable > 0:
        title_counts = f" - {total_reserved}/{total_reservable}"

    tfont = H1()
    title_render = title_text + title_counts
    if TITLE_ALIGN == "left":
        d.text((x0, y), title_render, font=tfont, fill=0)
    else:
        tw = d.textlength(title_render, font=tfont)
        d.text((x0 + (safe_w - tw)//2, y), title_render, font=tfont, fill=0)
    y += int(tfont.size * 1.15)

    if SUBTITLE:
        subtitle_font = H2()
        d.text((x0, y), SUBTITLE, font=subtitle_font, fill=0)
        y += int(subtitle_font.size * 1.2)

    d.line([(x0, y), (x1, y)], fill=0, width=1)
    y += 8

    body = BODY()
    line_h = int(body.size * LINE_SPACING)
    header_font = COLUMN_HEADER_FONT()
    header_line_h = int(header_font.size * LINE_SPACING)
    max_bottom = RES_H - SAFE_BOTTOM - FOOTER_H - 4

    group_sites_today = [s for s in sites_today if s.is_group_site]
    group_sites_tomorrow = [s for s in sites_tomorrow if s.is_group_site]

    sections: List[Tuple[str, List[object], str]] = [
        ("Reserved Sites", numbered_reserved_sites, "wrap"),
        ("Vacant Sites", vacant_sites, "wrap"),
    ]
    closed_regular_sites = [s for s in closed_sites if not s.is_group_site]
    if closed_regular_sites:
        sections.append(("Closed Sites", closed_regular_sites, "wrap"))

    if total_sites == 0:
        txt = "No campsites found"
        tw = d.textlength(txt, font=H1())
        d.text((x0 + (safe_w - tw)//2, y + 20), txt, font=H1(), fill=0)
        y += line_h * 2
    else:
        for title, items, mode in sections:
            if y + header_line_h > max_bottom:
                d.text((x0, max_bottom - header_line_h), "...", font=header_font, fill=0)
                break

            header = title if mode == "value" else f"{title} ({len(items)})"
            d.text((x0, y), header, font=header_font, fill=0)
            y += header_line_h

            if not items:
                if y + line_h > max_bottom:
                    break
                d.text((x0 + NUM_INDENT, y), "—", font=body, fill=0)
                y += line_h
            elif mode == "wrap":
                str_items = [s.label for s in items]
                max_w = max(10, safe_w - NUM_INDENT)
                for line in wrap_list(d, body, str_items, max_w=max_w, max_lines=6):
                    if y + line_h > max_bottom:
                        d.text((x0 + NUM_INDENT, max_bottom - line_h), "...", font=body, fill=0)
                        break
                    d.text((x0 + NUM_INDENT, y), line, font=body, fill=0)
                    y += line_h

            y += GROUP_SPACING
            if y > max_bottom:
                break

    y_primary_end = y

    day_use_today_text = "—" if day_use_remaining_today is None else f"{day_use_remaining_today}"
    day_use_tomorrow_text = "—" if day_use_remaining_tomorrow is None else f"{day_use_remaining_tomorrow}"

    column_gap = max(24, safe_w // 16)
    if column_gap >= safe_w:
        column_gap = max(4, safe_w // 4) if safe_w else 4
    column_width = max(10, (safe_w - column_gap) // 2)
    x_today_col = x0
    x_tomorrow_col = min(x1 - column_width, x_today_col + column_width + column_gap)

    group_labels_set = {s.label for s in group_sites_today}
    group_labels_set.update(s.label for s in group_sites_tomorrow)
    group_labels = sorted(group_labels_set, key=_site_sort_key)

    today_group_status = {s.label: s.status for s in group_sites_today}
    tomorrow_group_status = {s.label: s.status for s in group_sites_tomorrow}

    def build_column_rows(status_map: dict, day_use_value: str) -> List[str]:
        rows: List[str] = [""]
        if group_labels:
            for label in group_labels:
                status = status_map.get(label)
                status_text = status.replace("_", " ").title() if status else "—"
                rows.append(f"{label.upper()}: {status_text}")
        else:
            rows.append("Group Sites: —")
        rows.append("")
        rows.append(f"Day Use Remaining: {day_use_value}")
        return rows

    y = y_primary_end
    if y + 4 < max_bottom:
        y += 4
        d.line([(x0, y), (x1, y)], fill=0, width=1)
        y += 8

    column_top = y
    column_header_font = header_font
    column_header_line_h = header_line_h

    columns: List[Tuple[int, str, List[str]]] = [
        (x_today_col, f"Today ({label_today})", build_column_rows(today_group_status, day_use_today_text)),
        (x_tomorrow_col, f"Tomorrow ({label_tomorrow})", build_column_rows(tomorrow_group_status, day_use_tomorrow_text)),
    ]

    column_bottoms: List[int] = []
    for x_col, header_text, rows in columns:
        y_col = column_top
        header_render = _fit_text(d, column_header_font, header_text, column_width)
        header_width = d.textlength(header_render, font=column_header_font)
        header_x = x_col + max(0, (column_width - header_width) // 2)
        if header_render:
            d.text((header_x, y_col), header_render, font=column_header_font, fill=0)
        y_col += max(line_h, column_header_line_h)

        if not rows:
            rows = ["—"]

        for row in rows:
            if y_col > max_bottom:
                ellipsis_w = d.textlength("...", font=body)
                ellipsis_x = x_col + max(0, (column_width - ellipsis_w) // 2)
                d.text((ellipsis_x, max_bottom - line_h), "...", font=body, fill=0)
                y_col = max_bottom
                break
            row_render = _fit_text(d, body, row, column_width)
            row_width = d.textlength(row_render, font=body) if row_render else 0
            row_x = x_col + max(0, (column_width - row_width) // 2)
            if row_render:
                d.text((row_x, y_col), row_render, font=body, fill=0)
            y_col += line_h

        column_bottoms.append(y_col)

    divider_x = x_today_col + column_width + max(1, column_gap // 2)
    divider_y0 = max(SAFE_TOP, column_top - 2)
    divider_y1 = min(max_bottom, max(column_bottoms, default=column_top))
    if divider_y1 > divider_y0:
        d.line([(divider_x, divider_y0), (divider_x, divider_y1)], fill=0, width=1)

    y = max(column_bottoms, default=y) + GROUP_SPACING

    draw_footer(d, _last_fetched_utc, advisories)

    out = io.BytesIO()
    finalize_1bit(img).save(out, format="PNG", optimize=True)
    return out.getvalue()


_last_img: Optional[bytes] = None
_last_hash: Optional[str] = None
_last_render_ts: float = 0.0


def render_uvas_cached(force: bool = False) -> bytes:
    global _last_img, _last_hash, _last_render_ts
    now_ts = time.time()
    if not force and _last_img is not None and (now_ts - _last_render_ts) < CACHE_SECONDS:
        return _last_img
    target_dt = datetime.now(LOCAL_TZ)
    tomorrow_dt = target_dt + timedelta(days=1)

    with ThreadPoolExecutor(max_workers=4) as executor:
        future_html = executor.submit(fetch_html, target_dt)
        future_advisories = executor.submit(fetch_weather_advisories)
        future_tomorrow = executor.submit(load_table_for_date, tomorrow_dt)
        future_day_use = executor.submit(fetch_day_use_remaining, [target_dt, tomorrow_dt])

        html = future_html.result()
        advisories = future_advisories.result()

        try:
            tomorrow_html = future_tomorrow.result()
        except Exception as exc:
            log.error("Tomorrow table fetch failed: %s", exc)
            tomorrow_html = None

        try:
            day_use_map = future_day_use.result()
        except Exception as exc:
            log.error("Day use fetch failed: %s", exc)
            day_use_map = {target_dt.date(): None, tomorrow_dt.date(): None}
    day_use_remaining_today = day_use_map.get(target_dt.date())
    day_use_remaining_tomorrow = day_use_map.get(tomorrow_dt.date())
    content = render_image(
        html,
        advisories,
        target_dt=target_dt,
        day_use_remaining_today=day_use_remaining_today,
        tomorrow_html=tomorrow_html,
        day_use_remaining_tomorrow=day_use_remaining_tomorrow,
    )
    h = hashlib.sha256(content).hexdigest()
    if h != _last_hash:
        _last_hash = h
        _last_img = content
    _last_render_ts = now_ts
    return _last_img


def write_uvas_png(force: bool = False, output_path: Optional[str] = None) -> str:
    target = output_path or OUTPUT
    content = render_uvas_cached(force=force)
    with open(target, "wb") as f:
        f.write(content)
    return target


if __name__ == "__main__":
    path = write_uvas_png(force=True)
    print(f"Saved {path}")
