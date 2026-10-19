"""HLS playlist rewriting for the stream relay. Pure Python.

Every address in a playlist (variant playlists, segments, encryption keys, subtitle and audio renditions, init
sections) is made absolute against the playlist's own final address and replaced by a short relative one the relay
answers, so the player only ever talks to Home Assistant: no mixed content on an https page, no CORS, and the
provider address (with an Xtream password in it) never reaches a device."""
from __future__ import annotations

import re
from typing import Callable
from urllib.parse import urljoin, urlsplit

# tags whose URI="..." is a playlist; every other URI attribute (keys, maps, parts, hints) is fetched as a file
_PLAYLIST_TAGS = ("#EXT-X-MEDIA:", "#EXT-X-I-FRAME-STREAM-INF:", "#EXT-X-RENDITION-REPORT:")
_FILE_TAGS = ("#EXT-X-KEY:", "#EXT-X-SESSION-KEY:", "#EXT-X-MAP:", "#EXT-X-PART:", "#EXT-X-PRELOAD-HINT:")
_URI = re.compile(r'URI="([^"]*)"')

Register = Callable[[str, bool], str]     # (absolute address, is a playlist) -> the relative address to write


def is_playlist(body: bytes) -> bool:
    return body.lstrip(b"\xef\xbb\xbf \t\r\n")[:7] == b"#EXTM3U"


def extension(url: str) -> str:
    """The address's file extension, for the relay's own name (".ts", ".aac", ".key"); ".bin" when there is none."""
    path = urlsplit(url).path
    m = re.search(r"\.([A-Za-z0-9]{1,5})$", path)
    return f".{m.group(1).lower()}" if m else ".bin"


def _keep(uri: str) -> bool:
    """Addresses the relay leaves alone: inline data and DRM key systems."""
    return uri.startswith(("data:", "skd:")) or not uri


def rewrite(text: str, base_url: str, register: Register) -> str:
    out: list[str] = []
    next_is_playlist = False
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            if line.startswith("#EXT-X-STREAM-INF:"):
                next_is_playlist = True
            playlist_tag = line.startswith(_PLAYLIST_TAGS)
            if playlist_tag or line.startswith(_FILE_TAGS):
                line = _URI.sub(lambda m: m.group(0) if _keep(m.group(1)) else
                                f'URI="{register(urljoin(base_url, m.group(1)), playlist_tag)}"', line)
            out.append(line)
            continue
        if _keep(line):
            out.append(line)
            next_is_playlist = False
            continue
        absolute = urljoin(base_url, line)
        is_list = next_is_playlist or urlsplit(absolute).path.lower().endswith((".m3u8", ".m3u"))
        out.append(register(absolute, is_list))
        next_is_playlist = False
    return "\n".join(out) + "\n"
