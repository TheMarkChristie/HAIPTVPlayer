"""HLS playlist rewriting for the stream relay. Pure Python.

Every address in a playlist (variant playlists, segments, encryption keys, subtitle and audio renditions, init
sections) is made absolute against the playlist's own final address and replaced by a short path the relay answers, so the player only ever talks to Home Assistant: no mixed content on an https page, no CORS, and the
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


LIVE_KEEP = 30
_SEGMENT_TAGS = ("#EXTINF:", "#EXT-X-BYTERANGE:", "#EXT-X-DISCONTINUITY", "#EXT-X-PROGRAM-DATE-TIME:", "#EXT-X-KEY:",
                 "#EXT-X-MAP:", "#EXT-X-GAP", "#EXT-X-BITRATE:", "#EXT-X-CUE", "#EXT-X-DATERANGE:", "#EXT-OATCLS")


def trim_live(text: str, keep: int = LIVE_KEEP) -> str:
    """A live media playlist cut to its last `keep` segments. Some channels list hours of rewind (NRK1: 3,394
    segments); a player starts at the live edge anyway, and rewriting thousands of addresses every few seconds is
    wasted work. The media and discontinuity sequence numbers move on by what was cut, and the key and init section
    in force carry over to the first kept segment. Master playlists, finished (VOD) and low-latency playlists are
    left as they are."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if any(line.startswith(("#EXT-X-ENDLIST", "#EXT-X-STREAM-INF", "#EXT-X-PART:", "#EXT-X-PART-INF"))
           or line == "#EXT-X-PLAYLIST-TYPE:VOD" for line in lines):
        return text
    header: list[str] = []
    segments: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        if not line.startswith("#"):
            segments.append(current + [line])
            current = []
        elif segments or current or line.startswith(_SEGMENT_TAGS):
            current.append(line)
        else:
            header.append(line)
    if len(segments) <= keep:
        return text
    dropped, kept = segments[:-keep], segments[-keep:]
    key = init = None
    discontinuities = 0
    for seg in dropped:
        for line in seg:
            if line.startswith("#EXT-X-KEY:"):
                key = line
            elif line.startswith("#EXT-X-MAP:"):
                init = line
            elif line == "#EXT-X-DISCONTINUITY":
                discontinuities += 1
    carry = [t for t, tag in ((key, "#EXT-X-KEY:"), (init, "#EXT-X-MAP:"))
             if t and not any(x.startswith(tag) for x in kept[0])]
    kept[0] = carry + kept[0]
    out: list[str] = []
    has_media = has_disc = False
    for line in header:
        if line.startswith("#EXT-X-MEDIA-SEQUENCE:"):
            line = f"#EXT-X-MEDIA-SEQUENCE:{int(line.split(':', 1)[1] or 0) + len(dropped)}"
            has_media = True
        elif line.startswith("#EXT-X-DISCONTINUITY-SEQUENCE:"):
            line = f"#EXT-X-DISCONTINUITY-SEQUENCE:{int(line.split(':', 1)[1] or 0) + discontinuities}"
            has_disc = True
        out.append(line)
    extra = [] if has_media else [f"#EXT-X-MEDIA-SEQUENCE:{len(dropped)}"]
    if discontinuities and not has_disc:
        extra.append(f"#EXT-X-DISCONTINUITY-SEQUENCE:{discontinuities}")
    out = out[:1] + extra + out[1:]
    return "\n".join(out + [line for seg in kept for line in seg] + current) + "\n"


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
