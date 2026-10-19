"""XMLTV guide reading, as a stream: the Green never holds a whole guide (the provider's is 146 MB of XML).

The file is scanned for <channel> and <programme> elements; only the programmes of wanted channels inside the time
window are parsed. Channels come first in an XMLTV file, so reading the channel list stops at the first programme
and costs only the start of the file. Gzip is recognised by its first bytes. Pure Python (no Home Assistant)."""
from __future__ import annotations

import gzip
import io
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from typing import Iterator

from .model import Programme

_START = re.compile(r"<(channel|programme)[\s>/]")
_CHANNEL_ATTR = re.compile(r'\schannel="([^"]*)"')
_ID_ATTR = re.compile(r'\sid="([^"]*)"')
_DISPLAY = re.compile(r"<display-name[^>]*>([^<]*)</display-name>")
_TIME = re.compile(r"(\d{14})(?:\s*([+-])(\d{2})(\d{2}))?")
CHUNK = 1 << 20


def open_text(path: str) -> io.TextIOBase:
    """The file as text: gzip by its first two bytes, else plain XML. Anything else (a brotli or zstd answer saved as
    it came, an error page) raises ValueError rather than reading as a guide with no channels."""
    with open(path, "rb") as probe:
        head = probe.read(64)
    if head[:2] == b"\x1f\x8b":
        return gzip.open(path, "rt", encoding="utf-8", errors="replace")
    if not head.lstrip(b"\xef\xbb\xbf \t\r\n").startswith(b"<"):
        raise ValueError("not an XMLTV file")
    return open(path, encoding="utf-8", errors="replace")


def blocks(f: io.TextIOBase, stop_at_programme: bool = False) -> Iterator[tuple[str, str]]:
    """("channel" | "programme", the element's text) for every top-level element, read a megabyte at a time."""
    buf = ""
    eof = False
    while not eof:
        data = f.read(CHUNK)
        eof = not data
        buf += data
        pos = 0
        while True:
            m = _START.search(buf, pos)
            if not m:
                buf = buf[-20:]
                break
            tag = m.group(1)
            if stop_at_programme and tag == "programme":
                return
            gt = buf.find(">", m.start())
            if gt < 0:
                buf = buf[m.start():]
                break
            if buf[gt - 1] == "/":
                yield tag, buf[m.start():gt + 1]
                pos = gt + 1
                continue
            close = buf.find(f"</{tag}>", gt)
            if close < 0:
                buf = buf[m.start():]
                break
            end = close + len(tag) + 3
            yield tag, buf[m.start():end]
            pos = end


def parse_time(text: str | None) -> int | None:
    """'20261019040000 +0100' -> epoch seconds (no offset: UTC)."""
    m = _TIME.match((text or "").strip())
    if not m:
        return None
    when = datetime.strptime(m.group(1), "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
    if m.group(2):
        offset = timedelta(hours=int(m.group(3)), minutes=int(m.group(4)))
        when = when - offset if m.group(2) == "+" else when + offset
    return int(when.timestamp())


def read_channels(path: str) -> dict[str, list[str]]:
    """Guide channel id -> its display names."""
    out: dict[str, list[str]] = {}
    with open_text(path) as f:
        for tag, text in blocks(f, stop_at_programme=True):
            if tag != "channel":
                continue
            m = _ID_ATTR.search(text[:text.find(">") + 1])
            if not m:
                continue
            names = [_unescape(n).strip() for n in _DISPLAY.findall(text)]
            out.setdefault(_unescape(m.group(1)), [n for n in names if n])
    return out


def _unescape(text: str) -> str:
    return (text.replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"').replace("&apos;", "'")
            .replace("&#39;", "'").replace("&amp;", "&"))


def _text(el: ET.Element, tag: str) -> str:
    child = el.find(tag)
    return (child.text or "").strip() if child is not None and child.text else ""


def read_programmes(path: str, wanted: set[str], start: int, end: int, desc_chars: int = 600
                    ) -> dict[str, list[Programme]]:
    """The wanted channels' programmes that overlap [start, end), sorted, one per start time."""
    out: dict[str, dict[int, Programme]] = {}
    if not wanted:
        return {}
    with open_text(path) as f:
        for tag, text in blocks(f):
            if tag != "programme":
                continue
            head = text[:text.find(">") + 1]
            m = _CHANNEL_ATTR.search(head)
            if not m:
                continue
            cid = _unescape(m.group(1))
            if cid not in wanted:
                continue
            try:
                el = ET.fromstring(text)
            except ET.ParseError:
                continue
            p_start, p_stop = parse_time(el.get("start")), parse_time(el.get("stop"))
            if p_start is None:
                continue
            if p_stop is None or p_stop <= p_start:
                p_stop = p_start + 1800
            if p_stop <= start or p_start >= end:
                continue
            desc = _text(el, "desc")
            if len(desc) > desc_chars:
                desc = desc[:desc_chars].rsplit(" ", 1)[0] + "…"
            out.setdefault(cid, {})[p_start] = (p_start, p_stop, _text(el, "title") or "?", _text(el, "sub-title"),
                                                desc, _text(el, "category"))
    return {cid: [progs[k] for k in sorted(progs)] for cid, progs in out.items()}
