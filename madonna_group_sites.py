#!/usr/bin/env python3
"""
Madonna Group Sites renderer (library-only)
Adapted from TRMNL group sites script for Mt. Madonna.
Exposes helpers to render and save the group sites PNG.
"""
from __future__ import annotations
import io
import os
import time
import hashlib
import logging
import urllib.parse
from typing import Dict, Iterable, List, Optional, Tuple
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache

import requests
from PIL import Image, ImageDraw, ImageFont
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')
log = logging.getLogger("group-sites")

RES_W = 800
RES_H = 480

SAFE_LEFT   = int(os.getenv("SAFE_LEFT", "32"))
SAFE_RIGHT  = int(os.getenv("SAFE_RIGHT", "32"))
SAFE_TOP    = int(os.getenv("SAFE_TOP", "10"))
SAFE_BOTTOM = int(os.getenv("SAFE_BOTTOM", "5"))
FOOTER_H    = int(os.getenv("FOOTER_H", "30"))
FOOTER_PREFIX = os.getenv("FOOTER_PREFIX", "Pulled:").strip()
FOOTER_TIME_FORMAT = os.getenv("FOOTER_TIME_FORMAT", "%Y-%m-%d %H:%M:%S %Z")

DATA_TIMEOUT  = float(os.getenv("DATA_TIMEOUT", "8"))
CACHE_SECONDS = int(os.getenv("CACHE_SECONDS", "300"))

TITLE       = os.getenv("TITLE", "Mt. Madonna Group Sites")
SUBTITLE    = os.getenv("SUBTITLE", "")
FONT_SCALE  = float(os.getenv("FONT_SCALE", "1.0"))
TITLE_SCALE = float(os.getenv("TITLE_SCALE", "1.10"))
LINE_SPACING  = float(os.getenv("LINE_SPACING", "1.35"))
STATUS_GAP    = int(os.getenv("STATUS_GAP", "12"))
NUM_INDENT    = int(os.getenv("NUM_INDENT", "12"))
ALL_GROUP_SITES_RAW = [s.strip() for s in os.getenv("ALL_GROUP_SITES", "").split(",") if s.strip()]

PARK_ID    = os.getenv("PARK_ID", "8")
TZ_NAME    = os.getenv("TZ_NAME", "America/Los_Angeles")
DITHER     = int(os.getenv("DITHER", "0"))

OUTPUT = os.getenv("OUTPUT_GROUP", os.path.join(os.getcwd(), "render_groups.png"))

NWS_POINT_LAT = float(os.getenv("NWS_POINT_LAT", "37.01213"))
NWS_POINT_LON = float(os.getenv("NWS_POINT_LON", "-121.70494"))
NWS_TIMEOUT   = float(os.getenv("NWS_TIMEOUT", "10"))
NWS_USER_AGENT = os.getenv(
    "NWS_USER_AGENT",
    "trmnl-group-sites/1.0 (madonna-groupsites@example.com)",
)

SPACER_LABEL = "__SPACER__"

LABEL_ALIASES = {
    "arrowhead": "ARROWHEAD",
    "arrowhead group camp": "ARROWHEAD",
    "arrowhead group camp site": "ARROWHEAD",
    "arrowhead group campsite": "ARROWHEAD",
    "azalea knoll": "AZALEA KNOLL",
    "azalea knoll group camp": "AZALEA KNOLL",
    "azalea knoll group camp site": "AZALEA KNOLL",
    "azalea knoll group campsite": "AZALEA KNOLL",
    "amphitheater": "AMPHITHEATER",
    "amphitheater group camp": "AMPHITHEATER",
    "amphitheater group camp site": "AMPHITHEATER",
    "amphitheater group campsite": "AMPHITHEATER",
    "amphitheatre": "AMPHITHEATER",
    "amphitheatre group camp": "AMPHITHEATER",
    "amphitheatre group camp site": "AMPHITHEATER",
    "amphitheatre group campsite": "AMPHITHEATER",
    "hilltop": "HILLTOP",
    "hilltop group camp": "HILLTOP",
    "hilltop group camp site": "HILLTOP",
    "hilltop group campsite": "HILLTOP",
    "huckleberry": "HUCKLEBERRY",
    "huckleberry group": "HUCKLEBERRY",
    "huckleberry group camp": "HUCKLEBERRY",
    "huckleberry group camp site": "HUCKLEBERRY",
    "huckleberry group campsite": "HUCKLEBERRY",
    "huckleberry group site": "HUCKLEBERRY",
    "indian rock": "INDIAN ROCK",
    "indian rock group": "INDIAN ROCK",
    "indian rock group camp": "INDIAN ROCK",
    "indian rock group camp site": "INDIAN ROCK",
    "indian rock group campsite": "INDIAN ROCK",
    "manzanita": "MANZANITA",
    "manzanita group": "MANZANITA",
    "manzanita group camp": "MANZANITA",
    "manzanita group camp site": "MANZANITA",
    "manzanita group campsite": "MANZANITA",
    "redwood grove": "REDWOOD GROVE",
    "redwood grove group": "REDWOOD GROVE",
    "redwood grove group camp": "REDWOOD GROVE",
    "redwood grove group camp site": "REDWOOD GROVE",
    "redwood grove group campsite": "REDWOOD GROVE",
    "west deer pen": "WEST DEER PEN",
    "west deer pen group": "WEST DEER PEN",
    "west deer pen group camp": "WEST DEER PEN",
    "west deer pen group camp site": "WEST DEER PEN",
    "west deer pen group campsite": "WEST DEER PEN",
    SPACER_LABEL.lower(): SPACER_LABEL,
}

LABEL_DISPLAY_OVERRIDES: Dict[str, str] = {}

DEFAULT_GROUP_SITES = [
    "HUCKLEBERRY",
    "MANZANITA",
    "WEST DEER PEN",
    "INDIAN ROCK",
    "ARROWHEAD",
    SPACER_LABEL,
    "AZALEA KNOLL",
    "AMPHITHEATER",
    "HILLTOP",
    "REDWOOD GROVE",
]


def canonical_label(label: str) -> str:
    if label == SPACER_LABEL:
        return SPACER_LABEL
    cleaned = " ".join(label.split())
    if not cleaned:
        return ""
    return LABEL_ALIASES.get(cleaned.lower(), cleaned)


def display_label(label: str) -> str:
    if label == SPACER_LABEL:
        return ""
    canonical = canonical_label(label)
    return LABEL_DISPLAY_OVERRIDES.get(canonical.lower(), canonical)


_all_sites_temp: List[str] = []
for entry in DEFAULT_GROUP_SITES:
    canonical = canonical_label(entry)
    if canonical:
        _all_sites_temp.append(canonical)
for entry in ALL_GROUP_SITES_RAW:
    canonical = canonical_label(entry)
    if canonical:
        _all_sites_temp.append(canonical)
ALL_GROUP_SITES = list(dict.fromkeys(_all_sites_temp))

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


BASE_TITLE = int(28 * FONT_SCALE)
BASE_H2    = int(18 * FONT_SCALE)
BASE_BODY  = int(18 * FONT_SCALE)

FONT_PATHS: Tuple[str, ...] = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/System/Library/Fonts/SFNS.ttf",
    "/Library/Fonts/Arial.ttf",
)

FONT_PATHS_BOLD: Tuple[str, ...] = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/System/Library/Fonts/SFNSText.ttf",
    "/System/Library/Fonts/SFNS.ttf",
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


def BODY_BOLD(size: Optional[int] = None):
    target = size if size is not None else BASE_BODY
    return load_font_bold(target)


def build_url(for_dt: datetime) -> str:
    day = _mmddyyyy(for_dt)
    params = {
        "res_type": "QQQ",
        "park_idno": PARK_ID,
        "StartDate": day,
    }
    query = urllib.parse.urlencode(params)
    return "https://gooutsideandplay.org/reservations/sites_grid_pub.asp" + "?" + query


_last_payload: Optional[str] = None
_last_fetched_utc: Optional[datetime] = None
_last_error: Optional[str] = None

_known_group_sites: List[str] = list(ALL_GROUP_SITES)

_last_advisories: List[str] = []
_last_advisories_checked: Optional[datetime] = None
_last_advisories_error: Optional[str] = None


def _remember_group_sites(labels: Iterable[str]) -> None:
    for label in labels:
        canonical = canonical_label(label)
        if canonical and canonical not in _known_group_sites:
            _known_group_sites.append(canonical)


def fetch_html(for_dt: datetime) -> Optional[str]:
    global _last_payload, _last_fetched_utc, _last_error
    url = build_url(for_dt)
    try:
        r = requests.get(url, timeout=DATA_TIMEOUT, headers={"User-Agent":"trmnl-group-sites/1.0"})
        r.raise_for_status()
        _last_payload = r.text
        _last_fetched_utc = datetime.now(timezone.utc)
        _last_error = None
        return _last_payload
    except Exception as e:
        _last_error = str(e)
        log.error("Fetch failed: %s", e)
        return _last_payload


def fetch_weather_advisories() -> List[str]:
    global _last_advisories, _last_advisories_checked, _last_advisories_error
    url = f"https://api.weather.gov/alerts/active?point={NWS_POINT_LAT},{NWS_POINT_LON}"
    headers = {
        "User-Agent": NWS_USER_AGENT,
        "Accept": "application/geo+json",
    }
    try:
        resp = requests.get(url, timeout=NWS_TIMEOUT, headers=headers)
        resp.raise_for_status()
        payload = resp.json()
    except Exception as exc:
        log.error("Weather fetch failed: %s", exc)
        _last_advisories_error = str(exc)
        _last_advisories_checked = datetime.now(timezone.utc)
        return _last_advisories

    features = payload.get("features") or []
    advisories: List[str] = []
    for feature in features:
        props = feature.get("properties") or {}
        headline = props.get("headline") or props.get("event")
        if headline:
            advisories.append(" ".join(str(headline).split()))

    _last_advisories = advisories
    _last_advisories_error = None
    _last_advisories_checked = datetime.now(timezone.utc)
    return _last_advisories


STATUS_CLASS_PRIORITIES = {"cell_block", "cell_booked", "closedSite"}


def _normalize_status_from_classes(class_list: Iterable[str]) -> str:
    classes = tuple(sorted(c for c in class_list if c in STATUS_CLASS_PRIORITIES))
    if not classes:
        return "Unknown"

    class_map = {
        ("cell_block",): "Vacant",
        ("cell_block", "cell_booked"): "Reserved",
        ("cell_block", "closedSite"): "Closed",
    }

    if classes in class_map:
        return class_map[classes]

    if "cell_booked" in classes:
        return "Reserved"
    if "closedSite" in classes:
        return "Closed"
    if "cell_block" in classes:
        return "Vacant"
    return "Unknown"


def _normalize_status(cell_text: str) -> str:
    text = cell_text.strip().upper()
    if not text:
        return "Vacant"

    open_tokens = {"O", "OPEN", "AVAILABLE", "VACANT", "V"}
    if text in open_tokens or text.startswith("OPEN"):
        return "Vacant"
    if "AVAILABLE" in text and "UNAVAILABLE" not in text:
        return "Vacant"

    if "CLOSED" in text or "CLOSE" in text or "CLSD" in text:
        return "Closed"

    if text in {"X", "R", "H"}:
        return "Reserved"

    reserved_keywords = ("RES", "HOLD", "FULL", "UNAVAIL", "CLOSE")
    if any(keyword in text for keyword in reserved_keywords):
        return "Reserved"

    return "Reserved"


def parse_group_site_statuses(html: str, target_label: str) -> Dict[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", id="site_grid_table") or soup.find("table")
    if not table:
        return {}
    thead = table.find("thead")
    header_cells: List = []
    if thead:
        header_row = thead.find("tr")
        if header_row:
            header_cells = header_row.find_all(["th", "td"])
    if not header_cells:
        first_row = table.find("tr")
        if first_row:
            header_cells = first_row.find_all(["th", "td"])

    header_labels: List[str] = []
    for cell in header_cells:
        pieces = [part.strip() for part in cell.stripped_strings if part.strip()]
        header_labels.append(" ".join(pieces))

    normalized_target = " ".join(target_label.split()).strip()
    target_compact = normalized_target.replace(" ", "").casefold()
    target_tokens = normalized_target.split()
    target_day_name = target_tokens[0][:3].casefold() if target_tokens else ""
    target_day_number = next((tok for tok in target_tokens if tok.isdigit()), "")

    col_index = None
    for idx, label in enumerate(header_labels):
        normalized_label = " ".join(label.split()).strip()
        label_compact = normalized_label.replace(" ", "").casefold()
        label_tokens = normalized_label.split()
        label_day_name = label_tokens[0][:3].casefold() if label_tokens else ""
        label_day_number = next((tok for tok in label_tokens if tok.isdigit()), "")

        if normalized_label.casefold() == normalized_target.casefold():
            col_index = idx
            break
        if label_compact == target_compact:
            col_index = idx
            break
        if target_day_number and label_day_number == target_day_number and label_day_name == target_day_name:
            col_index = idx
            break

    if col_index is None:
        col_index = 1 if header_labels and header_labels[0].lower().startswith("site") else 0

    if thead and header_cells and table.find("tbody"):
        body_rows = table.find("tbody").find_all("tr")
    else:
        all_rows = table.find_all("tr")
        body_rows = all_rows[1:] if len(all_rows) > 1 else []

    statuses: Dict[str, str] = {}
    for tr in body_rows:
        tds = tr.find_all(["td", "th"])
        if not tds:
            continue
        label_raw = " ".join(tds[0].get_text(strip=True).split())
        label = canonical_label(label_raw)
        if not label or not label[0].isalpha():
            continue
        if col_index >= len(tds):
            continue
        cell = tds[col_index]
        status = _normalize_status_from_classes(cell.get("class", []))
        if status == "Unknown":
            status = _normalize_status(cell.get_text(strip=True))
        statuses[label] = status

    if statuses:
        _remember_group_sites(statuses.keys())
    return statuses


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


def draw_footer(
    draw: ImageDraw.ImageDraw,
    pulled_utc: Optional[datetime],
    advisories: Iterable[str],
    advisory_error: Optional[str] = None,
):
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
    elif FOOTER_PREFIX:
        timestamp_text = f"{FOOTER_PREFIX} pending".strip()

    if advisory_error:
        advisory_body = "Error"
    else:
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


def _draw_status_column(
    draw: ImageDraw.ImageDraw,
    rows: Iterable[Tuple[str, str, str]],
    *,
    status_index: int,
    x_start: int,
    y_start: int,
    max_bottom: int,
    line_height: int,
    font: ImageFont.ImageFont,
    align_status: bool,
    status_x: Optional[int],
) -> int:
    y = y_start
    label_x = x_start + NUM_INDENT
    for row in rows:
        label = row[0]
        if y + line_height > max_bottom:
            break
        if label == SPACER_LABEL:
            y += line_height
            continue
        status = row[status_index]
        label_display = display_label(label)
        if align_status and status_x is not None:
            draw.text((label_x, y), f"{label_display}:", font=font, fill=0)
            draw.text((status_x, y), status, font=font, fill=0)
        else:
            draw.text((label_x, y), f"{label_display}: {status}", font=font, fill=0)
        y += line_height
    return y


def render_image(today_html: Optional[str], advisories: Iterable[str]) -> bytes:
    img = Image.new("L", (RES_W, RES_H), 255)
    d = ImageDraw.Draw(img)

    x0, y = SAFE_LEFT, SAFE_TOP
    x1 = RES_W - SAFE_RIGHT
    safe_w = x1 - x0

    tfont = H1()
    tw = d.textlength(TITLE, font=tfont)
    d.text((x0 + (safe_w - tw)//2, y), TITLE, font=tfont, fill=0)
    y += int(tfont.size * 1.15)

    if SUBTITLE:
        d.text((x0, y), SUBTITLE, font=H2(), fill=0)
        y += int(H2().size * 1.2)

    d.line([(x0, y), (x1, y)], fill=0, width=1)
    body_start_y = y + 8

    footer_top = RES_H - SAFE_BOTTOM - FOOTER_H
    center_line_end = max(body_start_y, footer_top - 15)

    mid_x = x0 + safe_w // 2
    gutter = 6
    left_x0, left_x1   = x0,         mid_x - gutter
    right_x0, right_x1 = mid_x + gutter, x1

    d.line([(mid_x, body_start_y), (mid_x, center_line_end)], fill=0, width=1)

    now = datetime.now(LOCAL_TZ)
    today_label = _day_label(now)
    tomorrow = now + timedelta(days=1)
    tomorrow_label = _day_label(tomorrow)

    html_today = today_html or fetch_html(now)
    statuses_today = parse_group_site_statuses(html_today or "", today_label)

    html_tom = fetch_html(tomorrow) or ""
    statuses_tom = parse_group_site_statuses(html_tom, tomorrow_label)

    rows: List[Tuple[str, str, str]]
    if statuses_today or statuses_tom or _known_group_sites:
        seen: set[str] = set()
        ordered_labels: List[str] = []

        def add_labels(candidates: Iterable[str]) -> None:
            for label in candidates:
                canonical = canonical_label(label)
                if canonical and canonical not in seen:
                    seen.add(canonical)
                    ordered_labels.append(canonical)

        add_labels(ALL_GROUP_SITES)
        add_labels(statuses_today.keys())
        add_labels(statuses_tom.keys())
        add_labels(_known_group_sites)

        rows = []
        for label in ordered_labels:
            if label == SPACER_LABEL:
                rows.append((label, "", ""))
                continue
            rows.append(
                (
                    label,
                    statuses_today.get(label, "Vacant"),
                    statuses_tom.get(label, "Vacant"),
                )
            )
    else:
        rows = []

    no_data_message = "No group sites found"
    line_count = len(rows) if rows else 1

    body_font = BODY()

    def compute_metrics(font: ImageFont.ImageFont):
        size = getattr(font, "size", BASE_BODY)
        line_height = max(1, int(size * LINE_SPACING))
        header_bottom = body_start_y + line_height
        lines_avail = max(0, (footer_top - 4 - header_bottom) // line_height)
        return line_height, header_bottom, lines_avail

    line_h, _, lines_avail = compute_metrics(body_font)
    min_font_size = 10
    while line_count > lines_avail and getattr(body_font, "size", BASE_BODY) > min_font_size:
        new_size = max(min_font_size, getattr(body_font, "size", BASE_BODY) - 1)
        if new_size == getattr(body_font, "size", BASE_BODY):
            break
        body_font = load_font(new_size)
        line_h, _, lines_avail = compute_metrics(body_font)

    if line_count > lines_avail:
        log.warning("Only room for %d of %d lines; output may be truncated.", lines_avail, line_count)

    body_font_size = getattr(body_font, "size", BASE_BODY)
    heading_size = max(body_font_size, int(body_font_size * 1.2))
    heading_font = BODY_BOLD(heading_size)
    heading_line_h = max(line_h, int(heading_size * LINE_SPACING))

    max_bottom = footer_top - 4
    y_left = body_start_y
    y_right = body_start_y

    d.text((left_x0, y_left),  f"Today ({today_label})",    font=heading_font, fill=0); y_left  += heading_line_h
    y_left += line_h
    d.text((right_x0, y_right), f"Tomorrow ({tomorrow_label})", font=heading_font, fill=0); y_right += heading_line_h
    y_right += line_h

    if rows:
        label_texts = [
            f"{display_label(label)}:"
            for label, _, _ in rows
            if label != SPACER_LABEL
        ]
        max_label_w = max((d.textlength(txt, font=body_font) for txt in label_texts), default=0)

        max_status_w_left = max(
            (
                d.textlength(status, font=body_font)
                for label, status, _ in rows
                if label != SPACER_LABEL
            ),
            default=0,
        )
        max_status_w_right = max(
            (
                d.textlength(status, font=body_font)
                for label, _, status in rows
                if label != SPACER_LABEL
            ),
            default=0,
        )

        left_available = max(0, left_x1 - (left_x0 + NUM_INDENT))
        right_available = max(0, right_x1 - (right_x0 + NUM_INDENT))

        align_left = max_label_w + STATUS_GAP + max_status_w_left <= left_available
        align_right = max_label_w + STATUS_GAP + max_status_w_right <= right_available

        status_x_left: Optional[int] = None
        status_x_right: Optional[int] = None
        if align_left:
            status_x_left = left_x0 + NUM_INDENT + max_label_w + STATUS_GAP
        if align_right:
            status_x_right = right_x0 + NUM_INDENT + max_label_w + STATUS_GAP

        y_left = _draw_status_column(
            d,
            rows,
            status_index=1,
            x_start=left_x0,
            y_start=y_left,
            max_bottom=max_bottom,
            line_height=line_h,
            font=body_font,
            align_status=align_left,
            status_x=status_x_left,
        )
        y_right = _draw_status_column(
            d,
            rows,
            status_index=2,
            x_start=right_x0,
            y_start=y_right,
            max_bottom=max_bottom,
            line_height=line_h,
            font=body_font,
            align_status=align_right,
            status_x=status_x_right,
        )
    else:
        if y_left + line_h <= max_bottom:
            d.text((left_x0 + NUM_INDENT, y_left), no_data_message, font=body_font, fill=0)
            y_left += line_h
        if y_right + line_h <= max_bottom:
            d.text((right_x0 + NUM_INDENT, y_right), no_data_message, font=body_font, fill=0)
            y_right += line_h

    draw_footer(d, _last_fetched_utc, advisories, _last_advisories_error)

    out = io.BytesIO()
    finalize_1bit(img).save(out, format="PNG", optimize=True)
    return out.getvalue()


_last_img: Optional[bytes] = None
_last_hash: Optional[str] = None
_last_render_ts: float = 0.0


def render_group_sites_cached(force: bool = False) -> bytes:
    global _last_img, _last_hash, _last_render_ts
    now_ts = time.time()
    if not force and _last_img is not None and (now_ts - _last_render_ts) < CACHE_SECONDS:
        return _last_img
    target_dt = datetime.now(LOCAL_TZ)
    with ThreadPoolExecutor(max_workers=3) as executor:
        future_html = executor.submit(fetch_html, target_dt)
        future_advisories = executor.submit(fetch_weather_advisories)

        html = future_html.result()
        advisories = future_advisories.result()

    content = render_image(html, advisories)
    h = hashlib.sha256(content).hexdigest()
    if h != _last_hash:
        _last_hash = h
        _last_img = content
    _last_render_ts = now_ts
    return _last_img


def write_group_sites_png(force: bool = False, output_path: Optional[str] = None) -> str:
    target = output_path or OUTPUT
    content = render_group_sites_cached(force=force)
    with open(target, "wb") as f:
        f.write(content)
    return target


if __name__ == "__main__":
    path = write_group_sites_png(force=True)
    print(f"Saved {path}")
