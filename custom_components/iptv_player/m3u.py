"""M3U / M3U8 playlist reading (extended M3U as IPTV providers and Free-TV write it). Pure Python.

    #EXTM3U x-tvg-url="https://a.xml.gz, https://b.xml.gz"
    #EXTINF:-1 tvg-id="BBCOne.uk" tvg-name="BBC One" tvg-logo="https://..." group-title="UK",BBC One Ⓖ
    #EXTVLCOPT:http-user-agent=...
    https://example/bbc_one.m3u8
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_ATTR = re.compile(r'([A-Za-z0-9_-]+)="([^"]*)"')


@dataclass(frozen=True)
class M3UEntry:
    name: str
    url: str
    group: str | None = None
    tvg_id: str | None = None
    logo: str | None = None
    chno: str | None = None
    country: str | None = None
    user_agent: str | None = None
    referrer: str | None = None


def _split_extinf(line: str) -> tuple[dict[str, str], str]:
    """'#EXTINF:-1 a="x, y" b="z",Name, with comma' -> ({a: 'x, y', b: 'z'}, 'Name, with comma'). The title starts
    at the first comma outside quotes."""
    body = line[len("#EXTINF:"):]
    quoted = False
    for i, ch in enumerate(body):
        if ch == '"':
            quoted = not quoted
        elif ch == "," and not quoted:
            return dict(_ATTR.findall(body[:i])), body[i + 1:].strip()
    return dict(_ATTR.findall(body)), ""


def header_guides(text: str) -> list[str]:
    """The guide addresses an #EXTM3U header names (x-tvg-url / url-tvg, comma separated)."""
    for line in text.splitlines()[:5]:
        if line.startswith("#EXTM3U"):
            attrs = dict(_ATTR.findall(line))
            raw = attrs.get("x-tvg-url") or attrs.get("url-tvg") or ""
            return [u.strip() for u in raw.split(",") if u.strip().startswith(("http://", "https://"))]
    return []


def parse(text: str) -> list[M3UEntry]:
    entries: list[M3UEntry] = []
    attrs: dict[str, str] | None = None
    title = ""
    group_line: str | None = None
    opts: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip().lstrip("﻿")
        if not line:
            continue
        if line.startswith("#EXTINF:"):
            attrs, title = _split_extinf(line)
            group_line, opts = None, {}
        elif line.startswith("#EXTGRP:"):
            group_line = line[len("#EXTGRP:"):].strip() or None
        elif line.startswith("#EXTVLCOPT:"):
            key, _, value = line[len("#EXTVLCOPT:"):].partition("=")
            opts[key.strip().lower()] = value.strip()
        elif line.startswith("#"):
            continue
        elif attrs is not None:
            name = title or attrs.get("tvg-name") or line
            entries.append(M3UEntry(
                name=name.strip(), url=line,
                group=(attrs.get("group-title") or group_line or "").strip() or None,
                tvg_id=(attrs.get("tvg-id") or "").strip() or None,
                logo=(attrs.get("tvg-logo") or "").strip() or None,
                chno=(attrs.get("tvg-chno") or "").strip() or None,
                country=(attrs.get("tvg-country") or "").strip() or None,
                user_agent=opts.get("http-user-agent") or None,
                referrer=opts.get("http-referrer") or opts.get("http-referer") or None,
            ))
            attrs, title, group_line, opts = None, "", None, {}
    return entries
