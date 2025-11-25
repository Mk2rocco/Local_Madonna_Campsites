#!/usr/bin/env python3
"""
TRMNL — Available Numbered Campsites (Today)
- Scrapes gooutsideandplay.org for TODAY.
- Only includes sites whose labels start with digits 1–4:
    1xxx → Valley View Campground 1
    2xxx → Valley View Campground 2
    3xxx → Valley View Campground 3
    4xxx → Tan Oak
- Displays ONLY AVAILABLE sites (cell not "X"). If none across all groups → "No Vacancy".
- Layout: campground header, then up to 3 rows of comma-joined site labels beneath it.
  Truncates with "..." if overflow.
- Footer: shows the fetch timestamp at the left and any active NWS advisories on the right.
- Output: 1-bit PNG 800×480 for TRMNL, or direct rendering to an attached Inky Impression.
- Optional Flask server at /render.png (default port 8080).

Quick start (server):
  cd ~/trmnl && source .venv/bin/activate
  PORT=8080 TZ_NAME=America/Los_Angeles python app_numbers.py

One-shot render:
  RUN_MODE=once OUTPUT=render_numbers.png TZ_NAME=America/Los_Angeles python app_numbers.py

Inky Impression loop (updates every 15 minutes by default):
  RUN_MODE=inky TZ_NAME=America/Los_Angeles python app_numbers.py
"""

from __future__ import annotations
import io, os, re, time, socket, hashlib, logging, importlib, threading
from datetime import datetime, timezone
from typing import Dict, List, Optional

import requests
from PIL import Image, ImageDraw, ImageFont
from bs4 import BeautifulSoup
# These renderers are also available as stand-alone modules, but we keep
# light-weight wrappers here so a single process can generate and cache all
# three PNGs without bouncing between multiple entry points.
import madonna_group_sites
import uvas_canyon_reservations

try:
    from inky.auto import auto as auto_detect_inky
    _INKY_AVAILABLE = True
    _INKY_IMPORT_ERROR = None
except Exception as exc:  # pragma: no cover - hardware optional
    auto_detect_inky = None
    _INKY_AVAILABLE = False
    _INKY_IMPORT_ERROR = str(exc)

try:
    from gpiozero import Button
    _INKY_BUTTONS_AVAILABLE = True
except Exception:
    Button = None
    _INKY_BUTTONS_AVAILABLE = False

# Flask is optional—only needed for server mode.
_flask_spec = importlib.util.find_spec("flask")
if _flask_spec is not None:
    flask_module = importlib.import_module("flask")
    Flask = flask_module.Flask
    send_file = flask_module.send_file
    request = flask_module.request
    make_response = flask_module.make_response
else:  # pragma: no cover - depends on environment
    Flask = None
    send_file = None
    request = None
    make_response = None

# ---------- Config ----------
logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')
log = logging.getLogger("avail-numbers")

RES_W = int(os.getenv("RES_W", os.getenv("DISPLAY_WIDTH", "800")))
RES_H = int(os.getenv("RES_H", os.getenv("DISPLAY_HEIGHT", "480")))

SAFE_LEFT   = int(os.getenv("SAFE_LEFT", "32"))
SAFE_RIGHT  = int(os.getenv("SAFE_RIGHT", "32"))
SAFE_TOP    = int(os.getenv("SAFE_TOP", "10"))
SAFE_BOTTOM = int(os.getenv("SAFE_BOTTOM", "5"))
FOOTER_H    = int(os.getenv("FOOTER_H", "30"))

DATA_TIMEOUT  = float(os.getenv("DATA_TIMEOUT", "8"))
CACHE_SECONDS = int(os.getenv("CACHE_SECONDS", "300"))

TITLE_AVAILABLE = os.getenv("TITLE_AVAILABLE",
                            os.getenv("TITLE", "Mt. Madonna Available Campsites"))
TITLE_RESERVED  = os.getenv("TITLE_RESERVED", "Mt. Madonna Reserved Campsites")
TITLE_CLOSED    = os.getenv("TITLE_CLOSED", "Mt. Madonna Closed Campsites")
SUBTITLE    = os.getenv("SUBTITLE", "")
FONT_SCALE  = float(os.getenv("FONT_SCALE", "1.0"))
TITLE_SCALE = float(os.getenv("TITLE_SCALE", "1.10"))
LINE_SPACING  = float(os.getenv("LINE_SPACING", "1.35"))
GROUP_SPACING = int(os.getenv("GROUP_SPACING", "14"))
NUM_INDENT    = int(os.getenv("NUM_INDENT", "12"))
TITLE_ALIGN   = os.getenv("TITLE_ALIGN", "center")  # "left" or "center"

FOOTER_PREFIX = os.getenv("FOOTER_PREFIX", "Pulled:").strip()
FOOTER_TIME_FORMAT = os.getenv("FOOTER_TIME_FORMAT", "%Y-%m-%d %H:%M:%S %Z")
NWS_LAT = float(os.getenv("NWS_LAT", "37.01213"))
NWS_LON = float(os.getenv("NWS_LON", "-121.70494"))
NWS_USER_AGENT = os.getenv(
    "NWS_USER_AGENT",
    "madonna-campsites/1.0 (admin@example.com)",
)

PARK_ID    = os.getenv("PARK_ID", "8")
TZ_NAME    = os.getenv("TZ_NAME", "America/Los_Angeles")
DITHER     = int(os.getenv("DITHER", "0"))

GROUP_OUTPUT = os.getenv("OUTPUT_GROUP", os.path.join(os.getcwd(), "render_groups.png"))
UVAS_OUTPUT = os.getenv("OUTPUT_UVAS", os.path.join(os.getcwd(), "render_uvas.png"))

INKY_REFRESH_SECONDS = int(os.getenv("INKY_REFRESH_SECONDS", "900"))
INKY_SATURATION = float(os.getenv("INKY_SATURATION", "0.7"))
INKY_ROTATE = int(os.getenv("INKY_ROTATE", "0"))  # degrees clockwise
INKY_BORDER = os.getenv("INKY_BORDER", "white").lower()
INKY_BUTTON_PINS = {
    "A": int(os.getenv("INKY_BUTTON_A_PIN", "5")),
    "B": int(os.getenv("INKY_BUTTON_B_PIN", "6")),
    "C": int(os.getenv("INKY_BUTTON_C_PIN", "16")),
}
INKY_BUTTON_HOLD_TIME = float(os.getenv("INKY_BUTTON_HOLD", "0.05"))
INKY_BUTTON_BOUNCE = float(os.getenv("INKY_BUTTON_BOUNCE", "0.05"))
INKY_BUTTON_PULL_UP = bool(int(os.getenv("INKY_BUTTON_PULL_UP", "0")))

# Use the display refresh interval as the cadence for cross-renderer updates so
# the button toggles only swap between cached PNGs. Each button maps to a
# renderer key to keep the bindings explicit.
INKY_BUTTON_IMAGE_KEYS = {
    "A": "madonna",          # Local_Madonna_Sites
    "B": "group",            # Madonna Group sites
    "C": "uvas",             # Uvas Canyon reservations
}
INKY_CROSS_RENDER_SECONDS = int(os.getenv("INKY_CROSS_RENDER_SECONDS", str(INKY_REFRESH_SECONDS)))

HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8080"))
PORT_AUTO = int(os.getenv("PORT_AUTO", "1"))
PORT_SCAN_MAX = int(os.getenv("PORT_SCAN_MAX", "20"))
RUN_MODE = os.getenv("RUN_MODE", "server").lower()
OUTPUT = os.getenv("OUTPUT", os.path.join(os.getcwd(), "render.png"))

# ---------- Time zone ----------
try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover - Py<3.9 fallback
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

# ---------- Fonts ----------
BASE_TITLE = int(28 * FONT_SCALE)
BASE_H2    = int(18 * FONT_SCALE)
BASE_BODY  = int(19 * FONT_SCALE)

FONT_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/System/Library/Fonts/SFNS.ttf",
    "/Library/Fonts/Arial.ttf",
]

def load_font(size: int):
    for p in FONT_PATHS:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    return ImageFont.load_default()

def H1():
    return load_font(int(BASE_TITLE * TITLE_SCALE))

def H2():
    return load_font(BASE_H2)

def BODY():
    return load_font(BASE_BODY)

# ---------- HTTP fetch ----------
BASE_URL = "https://gooutsideandplay.org"
GRID_PATH = "/reservations/sites_grid_pub.asp"
BASE_QUERY = {
    "res_type": "QQQ",
    "park_idno": PARK_ID,
}

def build_url(for_dt: datetime) -> str:
    """Construct the daily reservation grid URL using the provided date."""
    params = dict(BASE_QUERY)
    params["StartDate"] = _mmddyyyy(for_dt)
    req = requests.Request("GET", f"{BASE_URL}{GRID_PATH}", params=params)
    return req.prepare().url

_last_payload: Optional[str] = None
_last_fetched_utc: Optional[datetime] = None
_last_error: Optional[str] = None
_last_advisories: List[str] = []

def fetch_html(for_dt: datetime) -> Optional[str]:
    global _last_payload, _last_fetched_utc, _last_error
    url = build_url(for_dt)
    try:
        r = requests.get(url, timeout=DATA_TIMEOUT, headers={"User-Agent": "trmnl-avail/1.0"})
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
    """Return active National Weather Service advisories for the configured point."""
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

# ---------- Parse ----------
GROUP_NAMES = {
    '1': "Valley View Campground 1",
    '2': "Valley View Campground 2",
    '3': "Valley View Campground 3",
    '4': "Tan Oak",
}

STATUS_CLASS_WHITELIST = {"cell_block", "cell_booked", "closedSite"}
STATUS_KEYS = ("vacant", "reserved", "closed")
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

def _status_sort_key(value: str) -> tuple[int, str]:
    """Sort shorter labels first, then lexicographically."""
    return (len(value), value)

def parse_number_site_status(html: str, target_label: str) -> Dict[str, Dict[str, List[str]]]:
    """
    Return dict {group_name: {"vacant": [...], "reserved": [...], "closed": [...]}}.
    Only includes labels starting with digits 1–4.
    Uses gooutsideandplay CSS classes to determine site status.
    """
    out: Dict[str, Dict[str, List[str]]] = {
        v: {status: [] for status in STATUS_KEYS} for v in GROUP_NAMES.values()
    }
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", id="site_grid_table") or soup.find("table")
    if not table:
        return out

    thead = table.find("thead")
    header_row = None
    if thead:
        header_rows = thead.find_all("tr")
        if header_rows:
            header_row = header_rows[-1]
    if header_row is None:
        header_row = table.find("tr")
    if header_row is None:
        return out

    raw_headers = header_row.find_all(["th", "td"])
    headers = [" ".join(h.get_text(separator=" ", strip=True).split()) for h in raw_headers]
    normalized_target = re.sub(r"\s+", "", target_label.lower())
    numeric_target = re.sub(r"\D", "", target_label)
    col_index = None
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

    for tr in data_rows:
        tds = tr.find_all(["td", "th"])
        if not tds:
            continue
        label = " ".join(tds[0].get_text(strip=True).split())
        if not label or not label[0].isdigit():
            continue
        group_key = label[0]
        if group_key not in GROUP_NAMES:
            continue
        if col_index >= len(tds):
            continue
        status = _normalize_status(tds[col_index].get("class", []))
        if status == "unknown":
            continue
        out[GROUP_NAMES[group_key]][status].append(label)

    for group in out.values():
        for status in STATUS_KEYS:
            group[status].sort(key=_status_sort_key)
    return out

# ---------- Wrap helper ----------
def wrap_list(draw: ImageDraw.ImageDraw, font: ImageFont.ImageFont,
              items: List[str], max_w: int, max_lines: int = 3) -> List[str]:
    tokens = items[:]
    lines, cur = [], ""
    i = 0
    while i < len(tokens) and len(lines) < max_lines:
        t = tokens[i]
        cand = t if not cur else f"{cur}, {t}"
        if draw.textlength(cand, font=font) <= max_w:
            cur = cand
            i += 1
        else:
            if cur:
                lines.append(cur)
                cur = ""
            else:
                s = t
                while s and draw.textlength(s + "...", font=font) > max_w:
                    s = s[:-1]
                lines.append(s + "...")
                return lines
    if cur and len(lines) < max_lines:
        lines.append(cur)
    if i < len(tokens) and lines:
        last = lines[-1]
        while last and draw.textlength(last + "...", font=font) > max_w:
            last = last[:-1]
        lines[-1] = (last + "...") if last else "..."
    return lines

def finalize_1bit(img: Image.Image) -> Image.Image:
    target = (RES_W, RES_H)
    if int(DITHER):
        bw = img.convert("1")
    else:
        bw = img.convert("1", dither=Image.NONE)
    if bw.size != target:
        bw = bw.resize(target)
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
    """Footer with timestamp on the left and labeled NWS advisories on the right."""
    y0 = RES_H - SAFE_BOTTOM - FOOTER_H
    y1 = RES_H - SAFE_BOTTOM
    draw.rectangle([SAFE_LEFT, y0, RES_W - SAFE_RIGHT, y1], fill=255)

    # Divider line above the footer block
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

# ---------- Render ----------
def _determine_display_state(total_vacant: int, total_reserved: int, total_closed: int) -> tuple[str, str]:
    """Return the status key to display and the matching title text."""
    if total_vacant == 0 and total_reserved == 0:
        if total_closed > 0:
            return "closed", TITLE_CLOSED
        return "vacant", TITLE_AVAILABLE
    if total_vacant == 0:
        return "reserved", TITLE_RESERVED
    if total_reserved == 0:
        return "vacant", TITLE_AVAILABLE
    if total_vacant <= total_reserved:
        return "vacant", TITLE_AVAILABLE
    return "reserved", TITLE_RESERVED

def generate_image(today_html: Optional[str], advisories: List[str]) -> Image.Image:
    img = Image.new("L", (RES_W, RES_H), 255)
    d = ImageDraw.Draw(img)

    x0, y = SAFE_LEFT, SAFE_TOP
    x1 = RES_W - SAFE_RIGHT
    safe_w = x1 - x0

    # Data
    now = datetime.now(LOCAL_TZ)
    label_today = _day_label(now)
    html = today_html or fetch_html(now)
    groups = parse_number_site_status(html or "", label_today)

    total_vacant = sum(len(v["vacant"]) for v in groups.values())
    total_reserved = sum(len(v["reserved"]) for v in groups.values())
    total_closed = sum(len(v["closed"]) for v in groups.values())
    total_sites = total_vacant + total_reserved + total_closed
    total_reservable = total_vacant + total_reserved

    display_status, title_text = _determine_display_state(
        total_vacant, total_reserved, total_closed
    )

    # Header
    title_counts = ""
    if total_reservable > 0:
        title_counts = f" - {total_reserved}/{total_reservable}"

    tfont = H1()
    if TITLE_ALIGN == "left":
        d.text((x0, y), title_text + title_counts, font=tfont, fill=0)
    else:
        tw = d.textlength(title_text + title_counts, font=tfont)
        d.text((x0 + (safe_w - tw)//2, y), title_text + title_counts, font=tfont, fill=0)
    y += int(tfont.size * 1.15)

    if SUBTITLE:
        subtitle_font = H2()
        d.text((x0, y), SUBTITLE, font=subtitle_font, fill=0)
        y += int(subtitle_font.size * 1.2)

    d.line([(x0, y), (x1, y)], fill=0, width=1)
    y += 8

    body = BODY()
    line_h = int(body.size * LINE_SPACING)
    max_bottom = RES_H - SAFE_BOTTOM - FOOTER_H - 4

    selected = {name: group[display_status] for name, group in groups.items()}
    total_selected = sum(len(v) for v in selected.values())

    if total_selected == 0:
        if total_sites == 0:
            txt = "No campsites found"
        elif display_status == "reserved":
            txt = "No reserved campsites"
        elif display_status == "closed":
            txt = "No closed campsites"
        else:
            txt = "No vacant campsites"
        tw = d.textlength(txt, font=H1())
        d.text((x0 + (safe_w - tw)//2, y + 20), txt, font=H1(), fill=0)
    else:
        for key in sorted(GROUP_NAMES):
            gname = GROUP_NAMES[key]
            items = selected.get(gname, [])
            group_data = groups.get(gname, {status: [] for status in STATUS_KEYS})
            total_known = sum(len(group_data[s]) for s in ("vacant", "reserved", "closed"))
            all_closed = total_known > 0 and len(group_data["closed"]) == total_known
            if y + line_h > max_bottom:
                d.text((x0, max_bottom - line_h), "...", font=body, fill=0)
                break
            d.text((x0, y), gname, font=body, fill=0)
            y += line_h

            if all_closed:
                if y + line_h > max_bottom:
                    break
                d.text((x0 + NUM_INDENT, y), "Closed", font=body, fill=0)
                y += line_h
            elif items:
                max_w = max(10, safe_w - NUM_INDENT)
                for line in wrap_list(d, body, items, max_w=max_w, max_lines=3):
                    if y + line_h > max_bottom:
                        d.text((x0 + NUM_INDENT, max_bottom - line_h), "...", font=body, fill=0)
                        break
                    d.text((x0 + NUM_INDENT, y), line, font=body, fill=0)
                    y += line_h
            else:
                if y + line_h > max_bottom:
                    break
                d.text((x0 + NUM_INDENT, y), "—", font=body, fill=0)
                y += line_h

            y += GROUP_SPACING
            if y > max_bottom:
                break

    draw_footer(d, _last_fetched_utc, advisories)
    return img

def _image_to_png_bytes(img: Image.Image) -> bytes:
    out = io.BytesIO()
    finalize_1bit(img).save(out, format="PNG", optimize=True)
    return out.getvalue()


def render_image(today_html: Optional[str], advisories: List[str]) -> bytes:
    img = generate_image(today_html, advisories)
    return _image_to_png_bytes(img)

# ---------- Cache & HTTP ----------
_last_img: Optional[bytes] = None
_last_hash: Optional[str] = None
_last_render_ts: float = 0.0
_last_pil: Optional[Image.Image] = None

# Cross-renderer caches so the Inky button toggles never trigger fresh renders.
_group_bytes: Optional[bytes] = None
_group_render_ts: float = 0.0
_uvas_bytes: Optional[bytes] = None
_uvas_render_ts: float = 0.0


def _clear_render_cache():
    global _last_img, _last_hash, _last_render_ts, _last_pil
    global _group_bytes, _group_render_ts, _uvas_bytes, _uvas_render_ts
    _last_img = None
    _last_hash = None
    _last_render_ts = 0.0
    _last_pil = None
    _group_bytes = None
    _group_render_ts = 0.0
    _uvas_bytes = None
    _uvas_render_ts = 0.0


def render_cached(force: bool = False, output: str = "bytes"):
    global _last_img, _last_hash, _last_render_ts, _last_pil
    now_ts = time.time()
    cached = (
        _last_img is not None
        and (now_ts - _last_render_ts) < CACHE_SECONDS
        and (_last_pil is not None or output == "bytes")
    )

    if not force and cached:
        if output == "pil" and _last_pil is not None:
            return _last_pil.copy()
        return _last_img

    html = fetch_html(datetime.now(LOCAL_TZ))
    advisories = fetch_weather_advisories()
    pil_image = generate_image(html, advisories)
    png_bytes = _image_to_png_bytes(pil_image)
    new_hash = hashlib.sha256(png_bytes).hexdigest()

    _last_hash = new_hash
    _last_img = png_bytes
    _last_pil = pil_image.copy()
    _last_render_ts = now_ts

    if output == "pil":
        return _last_pil.copy()
    return _last_img


def render_all_pngs(force: bool = False, refresh_window: Optional[int] = None) -> Dict[str, Image.Image]:
    """Render and cache all three PNG variants, returning PIL images keyed by name.

    The button handlers only swap between the cached images in memory; we refresh
    the underlying PNGs on the configured timer or when ``force`` is ``True``.
    """
    global _group_bytes, _group_render_ts, _uvas_bytes, _uvas_render_ts
    images: Dict[str, Image.Image] = {}

    try:
        primary_img = render_cached(force=force, output="pil")
        if primary_img is not None:
            with open(OUTPUT, "wb") as f:
                f.write(_image_to_png_bytes(primary_img))
            images["madonna"] = primary_img.copy()
    except Exception:
        log.exception("Failed to render primary Madonna campsites image")

    now_ts = time.time()
    window = CACHE_SECONDS if refresh_window is None else max(0, int(refresh_window))
    need_group = force or _group_bytes is None or (now_ts - _group_render_ts) >= window
    need_uvas = force or _uvas_bytes is None or (now_ts - _uvas_render_ts) >= window

    try:
        if need_group:
            _group_bytes = madonna_group_sites.render_group_sites_cached(force=True)
            _group_render_ts = now_ts
        if _group_bytes:
            with open(GROUP_OUTPUT, "wb") as f:
                f.write(_group_bytes)
            images["group"] = Image.open(io.BytesIO(_group_bytes)).convert("RGB")
    except Exception:
        log.exception("Failed to render Madonna group sites image")

    try:
        if need_uvas:
            _uvas_bytes = uvas_canyon_reservations.render_uvas_cached(force=True)
            _uvas_render_ts = now_ts
        if _uvas_bytes:
            with open(UVAS_OUTPUT, "wb") as f:
                f.write(_uvas_bytes)
            images["uvas"] = Image.open(io.BytesIO(_uvas_bytes)).convert("RGB")
    except Exception:
        log.exception("Failed to render Uvas Canyon reservations image")

    return images

def _update_resolution(width: int, height: int):
    global RES_W, RES_H
    width = int(width)
    height = int(height)
    if width <= 0 or height <= 0:
        return
    if (width, height) != (RES_W, RES_H):
        log.info("Switching canvas size to %dx%d", width, height)
        RES_W = width
        RES_H = height
        _clear_render_cache()


def prepare_inky_image(pil_image: Image.Image, inky_display) -> Image.Image:
    """Convert the grayscale canvas into an RGB image sized for the Inky display."""
    target_width = int(getattr(inky_display, "width", pil_image.width))
    target_height = int(getattr(inky_display, "height", pil_image.height))
    resample = Image.LANCZOS if hasattr(Image, "LANCZOS") else Image.BICUBIC

    img = pil_image.convert("RGB")
    if img.size != (target_width, target_height):
        img = img.resize((target_width, target_height), resample)

    rotation = INKY_ROTATE % 360
    if rotation not in (0, 180):
        if rotation:
            log.warning("INKY_ROTATE of %d is not supported; use 0 or 180", rotation)
        rotation = 0
    if rotation:
        img = img.rotate(-rotation, expand=True)
        if img.size != (target_width, target_height):
            img = img.resize((target_width, target_height), resample)

    return img


def _apply_inky_border(inky_display):
    if not hasattr(inky_display, "set_border"):
        return
    border = INKY_BORDER
    if border in {"", "none"}:
        return
    colour_attr = border.upper()
    colour = getattr(inky_display, colour_attr, None)
    if colour is None:
        colour = getattr(inky_display, "WHITE", None)
    try:
        if colour is not None:
            inky_display.set_border(colour)
    except Exception as exc:  # pragma: no cover - depends on hardware
        log.debug("Unable to set Inky border: %s", exc)


def run_inky_display(loop: bool = True):
    if not _INKY_AVAILABLE or auto_detect_inky is None:
        extra = (
            "Install it with 'pip install "
            '"inky[rpi]"'" inside your Pi virtualenv, then 'sudo apt install -y \n"
            "python3-rpi.gpio python3-spidev' on Raspberry Pi OS."
        )
        if _INKY_IMPORT_ERROR:
            log.error(
                "Inky display support requires the 'inky' library on the Raspberry Pi (import error: %s). %s",
                _INKY_IMPORT_ERROR,
                extra,
            )
        else:
            log.error(
                "Inky display support requires the 'inky' library on the Raspberry Pi (import error: unknown). %s",
                extra,
            )
        return
    try:
        verbose = bool(int(os.getenv("INKY_VERBOSE", "0")))
    except Exception:
        verbose = False
    try:
        inky = auto_detect_inky(ask_user=False, verbose=verbose)
    except Exception as exc:  # pragma: no cover - hardware only
        log.error("Failed to initialize Inky display: %s", exc)
        msg = str(exc).lower()
        if "pins" in msg and "in use" in msg:
            log.error(
                "Another process is already using the Inky pins (often a running systemd service). "
                "Stop it with 'sudo systemctl stop campsites.service' before running manually."
            )
        return

    _update_resolution(getattr(inky, "width", RES_W), getattr(inky, "height", RES_H))
    _apply_inky_border(inky)

    refresh = max(0, INKY_REFRESH_SECONDS)
    cross_refresh = max(0, INKY_CROSS_RENDER_SECONDS)
    log.info("Starting Inky refresh loop (%ss interval)", refresh)

    cached_images = render_all_pngs(force=True, refresh_window=cross_refresh)
    log.info("Initial cached_images keys: %s", list(cached_images))
    selected_key = INKY_BUTTON_IMAGE_KEYS.get("A", "madonna")
    redraw_needed = threading.Event()
    redraw_needed.set()

    def _show_selection():
        img = cached_images.get(selected_key)
        if img is None:
            first_available = next(iter(cached_images.items()), (None, None))
            if first_available[1] is None:
                log.error("No cached images available to display")
                return
            fallback_key, img = first_available
            log.warning(
                "No cached image for key %s; falling back to %s (available keys: %s)",
                selected_key,
                fallback_key,
                list(cached_images),
            )
            # Keep the user's selection sticky for the next refresh, but show something
            # immediately so the loop does not fail silently.
        prepared = prepare_inky_image(img, inky)
        inky.set_image(prepared, saturation=INKY_SATURATION)
        inky.show()
        log.info("Inky display updated (%s) at %s", selected_key, datetime.now(LOCAL_TZ).isoformat())

    def _bind_button(name: str, key: str):
        if not _INKY_BUTTONS_AVAILABLE or Button is None:
            log.warning(
                "GPIO buttons unavailable; skipping binding for %s (import failed)", name
            )
            return None
        pin = INKY_BUTTON_PINS.get(name)
        if pin is None:
            return None
        try:
            btn = Button(
                pin,
                hold_time=INKY_BUTTON_HOLD_TIME,
                bounce_time=INKY_BUTTON_BOUNCE,
                pull_up=INKY_BUTTON_PULL_UP,
            )

            def _handler():
                nonlocal selected_key
                selected_key = key
                log.info("Button %s pressed; switching to %s", name, key)
                redraw_needed.set()

            btn.when_pressed = _handler
            log.info("Inky button %s bound to pin %s", name, pin)
            return btn
        except Exception as exc:  # pragma: no cover - hardware specific
            log.warning("Unable to bind button %s on pin %s: %s", name, pin, exc)
            return None

    buttons = {name: _bind_button(name, key) for name, key in INKY_BUTTON_IMAGE_KEYS.items()}
    if not any(buttons.values()):
        log.warning("No Inky buttons were bound; check wiring or gpiozero configuration")

    next_refresh = time.time()
    while True:
        try:
            now = time.time()
            if refresh > 0 and now >= next_refresh:
                new_images = render_all_pngs(force=True, refresh_window=cross_refresh)
                if new_images:
                    cached_images.update(new_images)
                next_refresh = now + refresh
                redraw_needed.set()

            if redraw_needed.is_set():
                _show_selection()
                redraw_needed.clear()
        except KeyboardInterrupt:  # pragma: no cover - manual stop
            log.info("Inky loop interrupted by user")
            break
        except Exception as exc:  # pragma: no cover - hardware/network issues
            log.exception("Failed to refresh Inky display: %s", exc)

        if not loop or refresh <= 0:
            break
        time.sleep(0.1)


# ---------- HTTP server ----------
if Flask is not None:
    app = Flask(__name__)

    @app.get("/render.png")
    def http_render():
        force = request.args.get("force") is not None
        content = render_cached(force=force)
        resp = make_response(send_file(io.BytesIO(content), mimetype="image/png", max_age=0))
        resp.headers["Cache-Control"] = "no-store, max-age=0"
        return resp

    @app.get("/healthz")
    def healthz():
        pulled = _last_fetched_utc.astimezone(LOCAL_TZ).isoformat() if _last_fetched_utc else None
        return {"ok": True, "last_error": _last_error, "last_ok_fetched_at": pulled, "tz": TZ_NAME}
else:  # pragma: no cover - depends on environment
    app = None


# ---------- Server bootstrap ----------
def _can_bind(port: int) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if hasattr(socket, 'SOL_SOCKET') and hasattr(socket, 'SO_REUSEADDR'):
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    except Exception:
        pass
    try:
        s.bind(("0.0.0.0", port))
        return True
    except Exception:
        return False
    finally:
        try:
            s.close()
        except Exception:
            pass


def start_server():
    if Flask is None or app is None:
        log.error("Flask is not installed; install it or use RUN_MODE=inky/once.")
        raise SystemExit(1)
    p = PORT
    tries = 0
    while tries < PORT_SCAN_MAX and not _can_bind(p):
        if not PORT_AUTO:
            break
        p += 1
        tries += 1
        log.warning("Port busy; trying %d", p)
    log.info("Listening on %s:%d", HOST, p)
    app.run(host=HOST, port=p, use_reloader=False)


# ---------- Main ----------
if __name__ == "__main__":
    if RUN_MODE == "once":
        images = render_all_pngs(force=True)
        print(f"Saved {OUTPUT}")
        if images.get("group"):
            print(f"Saved {GROUP_OUTPUT}")
        if images.get("uvas"):
            print(f"Saved {UVAS_OUTPUT}")
    elif RUN_MODE == "inky_once":
        run_inky_display(loop=False)
    elif RUN_MODE == "inky":
        run_inky_display(loop=True)
    else:
        start_server()
