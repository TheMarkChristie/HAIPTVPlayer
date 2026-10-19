"""The stream relay: Home Assistant fetches the channel and passes it on, so a browser on an https page can play an
http provider, nothing needs CORS from the provider, and the provider address (with an Xtream password in it) never
leaves the server. Nothing is re-encoded.

    /api/iptv_player/hls/<token>/index.m3u8       the channel's playlist, every address in it rewritten
    /api/iptv_player/hls/<token>/p/<id>.m3u8      a variant, audio or subtitle playlist
    /api/iptv_player/hls/<token>/s/<id>.<ext>     a segment, key or init section
    /api/iptv_player/hls/<token>/live             a channel that is one continuous stream (MPEG-TS, radio)

No sign-in on these addresses: the token is the key, as with Home Assistant's own camera streams, so a Cast device
can open them. A session belongs to one channel, is shared by everyone watching it (one provider connection), ends
45 seconds after its last request or after 12 hours, and an Xtream login never gets more sessions than the
connections it allows: an idle one makes way, a busy one is not pushed off."""
from __future__ import annotations

import logging
import secrets
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

import aiohttp
from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    PLAY_HLS, PLAY_RAW, PLAYLIST_MAX_BYTES, RELAY_URL, SEGMENT_CHUNK, SESSION_IDLE_SECONDS, SESSION_MAX_HOURS, SESSIONS_MAX,
)
from .hls import extension, is_playlist, rewrite, trim_live
from .net import TooBig, read_capped

_LOGGER = logging.getLogger(__name__)
URLS_MAX = 3000
BUSY_SECONDS = 20          # a session asked for in the last 20 s is being watched and is never pushed off
MEDIA_TYPES = ("video/", "audio/", "application/octet-stream", "binary/octet-stream", "application/vnd.apple.mpegurl",
               "application/x-mpegurl", "application/mp4")
CORS = {"Access-Control-Allow-Origin": "*", "Access-Control-Expose-Headers": "Content-Length, Content-Type"}
SAFE = {"X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer"}


class RelayFull(Exception):
    """Every connection the login allows is in use."""


@dataclass
class Session:
    token: str
    entry_id: str
    channel_key: str
    kind: str
    start_url: str
    headers: dict[str, str]
    current: str | None = None                  # the main playlist's address after redirects
    urls: OrderedDict[str, tuple[str, bool]] = field(default_factory=OrderedDict)
    keys: dict[str, str] = field(default_factory=dict)      # upstream address -> its key in urls
    created: float = field(default_factory=time.monotonic)
    last_seen: float = field(default_factory=time.monotonic)
    viewers: int = 0

    @property
    def path(self) -> str:
        return f"{RELAY_URL}/{self.token}/" + ("index.m3u8" if self.kind == PLAY_HLS else "live")

    def register(self, url: str, is_list: bool) -> str:
        """The relative address the relay answers for an upstream address."""
        key = self.keys.get(url)
        if key is not None and key in self.urls:
            self.urls.move_to_end(key)
        else:
            key = secrets.token_hex(6)
            self.urls[key] = (url, is_list)
            self.keys[url] = key
            while len(self.urls) > URLS_MAX:
                _, (old, _) = self.urls.popitem(last=False)
                self.keys.pop(old, None)
        return f"p/{key}.m3u8" if is_list else f"s/{key}{extension(url)}"


class Relay:
    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self.sessions: dict[str, Session] = {}

    def _expire(self) -> None:
        now = time.monotonic()
        for token, s in list(self.sessions.items()):
            if now - s.last_seen > SESSION_IDLE_SECONDS or now - s.created > SESSION_MAX_HOURS * 3600:
                self.sessions.pop(token, None)

    def get(self, token: str) -> Session | None:
        self._expire()
        s = self.sessions.get(token)
        if s:
            s.last_seen = time.monotonic()
        return s

    def open(self, entry_id: str, channel_key: str, kind: str, start_url: str, headers: dict[str, str],
             max_streams: int | None) -> Session:
        """The channel's session (shared when it is already open), counting one more viewer."""
        self._expire()
        for s in self.sessions.values():
            if s.entry_id == entry_id and s.channel_key == channel_key:
                s.viewers += 1
                s.last_seen = time.monotonic()
                return s
        same = [s for s in self.sessions.values() if s.entry_id == entry_id]
        if max_streams and len(same) >= max_streams:
            now = time.monotonic()
            idle = sorted((s for s in same if s.viewers <= 0 or now - s.last_seen > BUSY_SECONDS), key=lambda s: s.last_seen)
            if not idle:
                raise RelayFull(f"all {max_streams} connections this login allows are in use")
            self.sessions.pop(idle[0].token, None)
        if len(self.sessions) >= SESSIONS_MAX:
            oldest = min(self.sessions.values(), key=lambda s: s.last_seen)
            self.sessions.pop(oldest.token, None)
        s = Session(secrets.token_urlsafe(18), entry_id, channel_key, kind, start_url, headers, viewers=1)
        self.sessions[s.token] = s
        return s

    def release(self, token: str) -> None:
        """A viewer left (the card changed channel or closed). The last one out ends the session now, so its
        connection is free for the next channel."""
        s = self.sessions.get(token)
        if s is None:
            return
        s.viewers -= 1
        if s.viewers <= 0:
            self.sessions.pop(token, None)

    def active(self, entry_id: str | None = None) -> list[dict[str, Any]]:
        self._expire()
        return [{"entry_id": s.entry_id, "channel": s.channel_key, "viewers": s.viewers,
                 "idle": round(time.monotonic() - s.last_seen)} for s in self.sessions.values()
                if entry_id is None or s.entry_id == entry_id]

    async def probe_kind(self, url: str, headers: dict[str, str]) -> str:
        """For a playlist address that does not say: read the first bytes once."""
        session = async_get_clientsession(self.hass)
        try:
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                head = await resp.content.read(512)
                ctype = resp.headers.get("Content-Type", "").lower()
        except (aiohttp.ClientError, TimeoutError):
            return PLAY_HLS
        return PLAY_HLS if is_playlist(head) or "mpegurl" in ctype else PLAY_RAW


def _headers(extra: dict[str, str] | None = None) -> dict[str, str]:
    return {**CORS, **SAFE, **(extra or {})}


def _media_type(value: str | None) -> str:
    ctype = (value or "").split(";")[0].strip().lower()
    return ctype if ctype.startswith(MEDIA_TYPES) else "application/octet-stream"


class _RelayView(HomeAssistantView):
    requires_auth = False
    cors_allowed = False

    def __init__(self, hass: HomeAssistant, relay: Relay) -> None:
        self.hass = hass
        self.relay = relay

    def _gone(self) -> web.Response:
        return web.Response(status=404, text="this stream has ended; open the channel again", headers=_headers())

    async def _fetch_playlist(self, s: Session, url: str) -> tuple[int, str, str]:
        """(status, final address, text) of one upstream playlist."""
        session = async_get_clientsession(self.hass)
        try:
            async with session.get(url, headers=s.headers, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                body = await read_capped(resp, PLAYLIST_MAX_BYTES)
                return resp.status, str(resp.url), body.decode("utf-8", "replace") if is_playlist(body) else ""
        except (aiohttp.ClientError, TimeoutError, TooBig) as err:
            _LOGGER.debug("Playlist for %s not read: %s", s.channel_key, type(err).__name__)
            return 504, url, ""

    def _playlist_response(self, s: Session, base: str, text: str) -> web.Response:
        return web.Response(text=rewrite(trim_live(text), base, s.register), content_type="application/vnd.apple.mpegurl",
                            headers=_headers({"Cache-Control": "no-store"}))

    def _refused(self, status: int) -> web.Response:
        message = {403: "the provider refused the stream (the login's connections may all be in use)",
                   404: "the provider has no stream for this channel now"}.get(status, f"the provider answered {status}")
        return web.Response(status=502 if status >= 500 else status, text=message, headers=_headers())


class RelayIndexView(_RelayView):
    url = RELAY_URL + "/{token}/index.m3u8"
    name = "api:iptv_player:hls:index"

    async def get(self, request: web.Request, token: str) -> web.Response:
        s = self.relay.get(token)
        if s is None:
            return self._gone()
        status, final, text = (0, "", "")
        if s.current:
            status, final, text = await self._fetch_playlist(s, s.current)
        if not text:
            # first time, or the provider's short-lived address expired: start again from the channel's own address
            status, final, text = await self._fetch_playlist(s, s.start_url)
        if not text:
            return self._refused(status if status >= 400 else 502)
        s.current = final
        return self._playlist_response(s, final, text)


class RelayPlaylistView(_RelayView):
    url = RELAY_URL + "/{token}/p/{key}.m3u8"
    name = "api:iptv_player:hls:playlist"

    async def get(self, request: web.Request, token: str, key: str) -> web.Response:
        s = self.relay.get(token)
        if s is None or key not in s.urls:
            return self._gone()
        status, final, text = await self._fetch_playlist(s, s.urls[key][0])
        if not text:
            return self._refused(status if status >= 400 else 502)
        return self._playlist_response(s, final, text)


async def _pipe(hass: HomeAssistant, request: web.Request, s: Session, url: str, cache: str) -> web.StreamResponse:
    """Pass one upstream answer through, a chunk at a time, until it ends or the player goes away. Every chunk
    counts as the session being watched, so a continuous stream is never taken for an idle one."""
    session = async_get_clientsession(hass)
    # uncompressed: aiohttp would unpack a gzip answer while its Content-Length still counted the packed bytes, and a
    # player told 27 bytes that gets 7 waits for the rest (NRK's subtitle segments, 19 Oct 2026)
    headers = {**s.headers, "Accept-Encoding": "identity"}
    try:
        resp = await session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=None, sock_connect=15, sock_read=30))
    except (aiohttp.ClientError, TimeoutError):
        return web.Response(status=504, text="the provider did not answer", headers=_headers())
    try:
        if resp.status >= 400:
            return web.Response(status=502, text=f"the provider answered {resp.status}", headers=_headers())
        out = web.StreamResponse(status=200, headers=_headers({"Cache-Control": cache}))
        out.content_type = _media_type(resp.headers.get("Content-Type"))
        length = resp.headers.get("Content-Length")
        if length and length.isdigit() and resp.headers.get("Content-Encoding", "identity").lower() == "identity":
            out.content_length = int(length)
        await out.prepare(request)
        try:
            async for chunk in resp.content.iter_chunked(SEGMENT_CHUNK):
                s.last_seen = time.monotonic()
                await out.write(chunk)
        except (aiohttp.ClientError, TimeoutError, ConnectionResetError):
            pass
        return out
    finally:
        resp.release()


class RelaySegmentView(_RelayView):
    url = RELAY_URL + "/{token}/s/{name}"
    name = "api:iptv_player:hls:segment"

    async def get(self, request: web.Request, token: str, name: str) -> web.StreamResponse:
        s = self.relay.get(token)
        key = name.split(".", 1)[0]
        if s is None or key not in s.urls:
            return self._gone()
        return await _pipe(self.hass, request, s, s.urls[key][0], "private, max-age=60")


class RelayLiveView(_RelayView):
    url = RELAY_URL + "/{token}/live"
    name = "api:iptv_player:hls:live"

    async def get(self, request: web.Request, token: str) -> web.StreamResponse:
        s = self.relay.get(token)
        if s is None:
            return self._gone()
        return await _pipe(self.hass, request, s, s.start_url, "no-store")


def relay_views(hass: HomeAssistant, relay: Relay) -> list[HomeAssistantView]:
    return [cls(hass, relay) for cls in (RelayIndexView, RelayPlaylistView, RelaySegmentView, RelayLiveView)]
