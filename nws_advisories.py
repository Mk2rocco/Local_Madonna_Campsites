#!/usr/bin/env python3
"""Standalone, paginated NWS advisory display for the configured park point."""
from datetime import datetime, timezone
import logging
import os
from pathlib import Path
import re
import threading
import time
from zoneinfo import ZoneInfo

import requests
from PIL import Image, ImageDraw, ImageFont

log = logging.getLogger(__name__)
REFRESH_SECONDS = 2 * 60 * 60
LAT = float(os.getenv('NWS_LAT', '37.01213'))
LON = float(os.getenv('NWS_LON', '-121.70494'))
USER_AGENT = os.getenv('NWS_USER_AGENT', 'madonna-campsites/1.0 (admin@example.com)')
TIMEOUT = float(os.getenv('DATA_TIMEOUT', '8'))
try:
    LOCAL_TZ = ZoneInfo(os.getenv('TZ_NAME', 'America/Los_Angeles'))
except Exception:
    LOCAL_TZ = timezone.utc


def font(size, bold=False):
    name = 'DejaVuSans-Bold.ttf' if bold else 'DejaVuSans.ttf'
    for path in [f'/usr/share/fonts/truetype/dejavu/{name}', '/Library/Fonts/Arial.ttf']:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            pass
    return ImageFont.load_default()


def wrap_text(text, draw, face, width):
    """Pixel-wrap paragraphs, splitting even long URLs without dropping text."""
    lines = []
    for paragraph in re.split(r'\n\s*\n', str(text).strip()):
        words = paragraph.split()
        line = ''
        for word in words:
            candidate = f'{line} {word}' if line else word
            if draw.textlength(candidate, font=face) <= width:
                line = candidate
                continue
            if line:
                lines.append(line)
                line = ''
            while word and draw.textlength(word, font=face) > width:
                cut = 1
                while cut < len(word) and draw.textlength(word[:cut + 1], font=face) <= width:
                    cut += 1
                lines.append(word[:cut])
                word = word[cut:]
            line = word
        if line:
            lines.append(line)
        lines.append('')
    return lines[:-1] if lines else []


def timestamp(value):
    if not value:
        return 'Not specified'
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(LOCAL_TZ).strftime('%b %d, %I:%M %p %Z')
    except (ValueError, TypeError):
        return str(value)


def advisory_text(alert):
    """Keep the complete headline, affected area, description, and instructions."""
    sections = [alert.get('event') or 'NWS advisory']
    for key, label in [('headline', 'Headline'), ('severity', 'Severity'),
                       ('urgency', 'Urgency'), ('certainty', 'Certainty'),
                       ('areaDesc', 'Affected area')]:
        if alert.get(key):
            sections.append(f'{label}: {alert[key]}')
    for key, label in [('effective', 'Effective'), ('onset', 'Starts'), ('ends', 'Ends'), ('expires', 'Expires')]:
        if alert.get(key):
            sections.append(f'{label}: {timestamp(alert[key])}')
    sections.append('Details:\n' + (alert.get('description') or 'No additional description supplied by NWS.'))
    if alert.get('instruction'):
        sections.append('Instructions:\n' + alert['instruction'])
    return '\n\n'.join(sections)


def render_pages(alerts, *, fetched_at=None, error=None, width=800, height=480):
    """Render every line across as many full-size pages as necessary."""
    body = font(16)
    title = font(24, bold=True)
    footer = font(13)
    margin = 24
    content_width = width - 2 * margin
    line_height = max(20, body.getbbox('Ag')[3] - body.getbbox('Ag')[1] + 5)
    banner = 'Last successful data shown; NWS refresh failed.' if error and fetched_at else 'NWS request failed; current conditions unknown.'
    top = 92 if error else 62
    bottom = height - 48
    capacity = max(1, (bottom - top) // line_height)
    draw = ImageDraw.Draw(Image.new('L', (width, height), 255))
    if alerts:
        texts = [advisory_text(alert) for alert in alerts]
    elif error:
        texts = ['Unable to retrieve NWS advisories.\n\nPlease try again later. This does not mean there are no active advisories.']
    else:
        texts = ['No active NWS advisories.\n\nThere are currently no active NWS alerts for the configured park location.']
    chunks = []
    for text in texts:
        lines = wrap_text(text, draw, body, content_width)
        chunks.extend(lines[i:i + capacity] for i in range(0, len(lines), capacity))
    pages = []
    checked = fetched_at.astimezone(LOCAL_TZ).strftime('%b %d %I:%M %p %Z') if fetched_at else 'Unavailable'
    for index, lines in enumerate(chunks):
        image = Image.new('RGB', (width, height), 'white')
        d = ImageDraw.Draw(image)
        d.text((margin, 12), 'NWS Advisories', font=title, fill='black')
        d.line((margin, 48, width - margin, 48), fill='black')
        if error:
            # Short status banner; full API errors remain in logs.
            d.text((margin, 57), banner, font=footer, fill='black')
        y = top
        for line in lines:
            d.text((margin, y), line, font=body, fill='black')
            y += line_height
        d.line((margin, height - 43, width - margin, height - 43), fill='black')
        d.text((margin, height - 35), f'Checked: {checked}', font=footer, fill='black')
        navigation = f'Page {index + 1}/{len(chunks)} | D: next page'
        d.text((width - margin - d.textlength(navigation, font=footer), height - 35), navigation, font=footer, fill='black')
        pages.append(image)
    return pages


class AdvisoryProgram:
    """Independent two-hour cache; preserve and label last data on fetch errors."""
    def __init__(self):
        self.alerts = None
        self.fetched_at = None
        self.error = None
        self.last_attempt = None
        self.lock = threading.Lock()

    def pages(self, *, force=False, width=800, height=480):
        with self.lock:
            now = time.monotonic()
            if force or self.last_attempt is None or now - self.last_attempt >= REFRESH_SECONDS:
                try:
                    response = requests.get('https://api.weather.gov/alerts/active',
                                            params={'point': f'{LAT},{LON}'},
                                            headers={'User-Agent': USER_AGENT, 'Accept': 'application/geo+json'},
                                            timeout=TIMEOUT)
                    response.raise_for_status()
                    payload = response.json()
                    if not isinstance(payload, dict) or not isinstance(payload.get('features'), list):
                        raise ValueError('NWS response has no alert feature list')
                    alerts = []
                    for feature in payload['features']:
                        props = feature.get('properties')
                        if not isinstance(props, dict):
                            raise ValueError('NWS alert properties are missing')
                        if props.get('status', 'Actual') == 'Actual' and props.get('messageType') != 'Cancel':
                            alerts.append(props)
                    self.alerts = alerts
                    self.fetched_at = datetime.now(timezone.utc)
                    self.error = None
                except Exception as exc:
                    self.error = str(exc)
                    log.warning('NWS detailed advisory fetch failed: %s', exc)
                self.last_attempt = now
            return render_pages(self.alerts or [], fetched_at=self.fetched_at, error=self.error,
                                width=width, height=height)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    output = Path(os.getenv('OUTPUT_ADVISORIES', 'render_advisories.png'))
    for index, page in enumerate(AdvisoryProgram().pages(force=True)):
        target = output if index == 0 else output.with_name(f'{output.stem}_{index + 1}{output.suffix}')
        page.save(target, format='PNG')
        print(f'Saved {target}')
