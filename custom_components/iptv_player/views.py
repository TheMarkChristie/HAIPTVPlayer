"""The logo proxy: /api/iptv_player/logo/<entry>/<key>, for channel logos on plain http (a browser blocks them on an
https page). Signed per websocket answer; only images are passed on, kept in memory for a day (up to 400 of them or
30 MB), and a logo that failed is not asked for again for ten minutes."""
from __future__ import annotations

import logging
import time
from collections import OrderedDict

import aiohttp
from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import LOGO_URL
from .net import TooBig, read_capped

_LOGGER = logging.getLogger(__name__)
CACHE_MAX = 400
CACHE_MAX_BYTES = 30 * 1024 * 1024
LOGO_MAX_BYTES = 1024 * 1024
CACHE_TTL = 86400
FAILED_SECONDS = 600
SAFE = {"X-Content-Type-Options": "nosniff", "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'"}


class LogoView(HomeAssistantView):
    url = LOGO_URL + "/{entry_id}/{key}"
    name = "api:iptv_player:logo"
    requires_auth = True

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._cache: OrderedDict[str, tuple[float, bytes, str]] = OrderedDict()
        self._bytes = 0
        self._failed: dict[str, float] = {}

    def _put(self, key: str, body: bytes, ctype: str) -> None:
        old = self._cache.pop(key, None)
        if old:
            self._bytes -= len(old[1])
        self._cache[key] = (time.monotonic(), body, ctype)
        self._bytes += len(body)
        while self._cache and (len(self._cache) > CACHE_MAX or self._bytes > CACHE_MAX_BYTES):
            _, (_, gone, _) = self._cache.popitem(last=False)
            self._bytes -= len(gone)

    async def get(self, request: web.Request, entry_id: str, key: str) -> web.Response:
        from . import coordinator_for  # noqa: PLC0415

        headers = {"Cache-Control": "private, max-age=86400", **SAFE}
        hit = self._cache.get(key)
        if hit and time.monotonic() - hit[0] < CACHE_TTL:
            return web.Response(body=hit[1], content_type=hit[2], headers=headers)
        coordinator = coordinator_for(self.hass, entry_id)
        url = coordinator.logos.get(key) if coordinator else None
        if not url:
            return web.Response(status=404, headers=SAFE)
        if time.monotonic() - self._failed.get(key, -1e9) < FAILED_SECONDS:
            return web.Response(status=502, headers=SAFE)
        try:
            async with async_get_clientsession(self.hass).get(
                    url, headers={"User-Agent": coordinator.user_agent}, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                ctype = resp.headers.get("Content-Type", "").split(";")[0].strip().lower()
                if resp.status >= 400 or not ctype.startswith("image/"):
                    raise ValueError(f"HTTP {resp.status} {ctype}")
                body = await read_capped(resp, LOGO_MAX_BYTES)
        except (aiohttp.ClientError, TimeoutError, ValueError, TooBig) as err:
            _LOGGER.debug("Logo %s not read: %s", key, err)
            self._failed[key] = time.monotonic()
            if len(self._failed) > 2000:
                self._failed.clear()
            return web.Response(status=502, headers=SAFE)
        # an SVG is served under default-src 'none', so a script inside one cannot run
        self._put(key, body, ctype)
        return web.Response(body=body, content_type=ctype, headers=headers)
