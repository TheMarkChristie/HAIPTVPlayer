"""One entry: a provider login (Xtream Codes) or a playlist (M3U). Reads the account every 15 minutes (Xtream) and the
channel list twice a day; the list is cached on disk so a restart does not ask the provider again. Holds Mark's
selection (Home Assistant storage) and the entry's guide."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from dataclasses import asdict
from datetime import timedelta
from typing import Any
from urllib.parse import urlsplit

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from . import m3u
from .const import (
    ACCOUNT_MINUTES, CATALOG_HOURS, CONF_KIND, CONF_OUTPUT, CONF_PASSWORD, CONF_URL, CONF_USER_AGENT, CONF_USERNAME,
    DEFAULT_OUTPUT, DEFAULT_USER_AGENT, DOMAIN, EVENT_UPDATED, KIND_XTREAM, LOGO_URL, NAME, PLAY_HLS, PLAY_RAW,
    PROVIDER_TIMEOUT_SECONDS, STORE_VERSION,
)
from .guide import GuideManager
from .model import Catalog, Channel, Group, apply_changes, catalog_from_m3u, catalog_from_xtream, normal_selection, shown_channels
from .xtream import XtreamAuthError, XtreamClient, XtreamError

_LOGGER = logging.getLogger(__name__)
PLAYLIST_MAX_BYTES = 30 * 1024 * 1024


class SourceError(Exception):
    pass


def catalog_to_json(catalog: Catalog, at: float) -> dict[str, Any]:
    return {"at": at, "groups": [asdict(g) for g in catalog.groups], "channels": [c.as_dict() for c in catalog.channels],
            "skipped": catalog.skipped, "guide_urls": catalog.guide_urls}


def catalog_from_json(data: dict[str, Any]) -> tuple[Catalog, float]:
    groups = [Group(**g) for g in data.get("groups", [])]
    channels = [Channel(**c) for c in data.get("channels", [])]
    return Catalog(groups, channels, int(data.get("skipped") or 0), list(data.get("guide_urls") or [])), float(data.get("at") or 0)


def play_kind_for_url(url: str) -> str | None:
    """HLS by its address; None when only the answer can tell."""
    parts = urlsplit(url.lower())
    if parts.path.endswith((".m3u8", ".m3u")) or "m3u8" in parts.query:
        return PLAY_HLS
    if parts.path.endswith((".ts", ".mp3", ".aac", ".mp4")):
        return PLAY_RAW
    return None


class IPTVCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, _LOGGER, name=f"{NAME} {entry.title}", config_entry=entry,
                         update_interval=timedelta(minutes=ACCOUNT_MINUTES))
        self.entry = entry
        self.kind: str = entry.data[CONF_KIND]
        self.user_agent = str(entry.options.get(CONF_USER_AGENT) or DEFAULT_USER_AGENT)
        self.client: XtreamClient | None = None
        if self.kind == KIND_XTREAM:
            self.client = XtreamClient(async_get_clientsession(hass), entry.data[CONF_URL], entry.data[CONF_USERNAME],
                                       entry.data[CONF_PASSWORD], self.user_agent)
        self.catalog: Catalog | None = None
        self.catalog_at: float = 0
        self.account: dict[str, Any] = {}
        self.selection: dict[str, Any] = normal_selection(None)
        self.play_kinds: dict[str, str] = {}
        self.logos: dict[str, str] = {}
        self.guide = GuideManager(hass, self)
        self._store = Store(hass, STORE_VERSION, f"{DOMAIN}.{entry.entry_id}")
        self._catalog_file = hass.config.cache_path(DOMAIN, f"{entry.entry_id}-catalog.json")
        self._force_catalog = False
        self.version = 0

    @property
    def options(self) -> dict[str, Any]:
        return dict(self.entry.options)

    def scrub(self, text: str) -> str:
        return self.client._scrub(text) if self.client else text

    # ---- storage ----
    async def async_load(self) -> None:
        stored = await self._store.async_load() or {}
        self.selection = normal_selection(stored.get("selection"))

        def read() -> dict[str, Any] | None:
            try:
                with open(self._catalog_file, encoding="utf-8") as f:
                    return json.load(f)
            except (OSError, ValueError):
                return None

        cached = await self.hass.async_add_executor_job(read)
        if cached:
            try:
                self.catalog, self.catalog_at = catalog_from_json(cached)
                self._index_logos()
            except (TypeError, ValueError):
                self.catalog, self.catalog_at = None, 0

    async def _save_catalog(self) -> None:
        if self.catalog is None:
            return
        body = json.dumps(catalog_to_json(self.catalog, self.catalog_at))

        def write() -> None:
            os.makedirs(os.path.dirname(self._catalog_file), exist_ok=True)
            with open(self._catalog_file + ".part", "w", encoding="utf-8") as f:
                f.write(body)
            os.replace(self._catalog_file + ".part", self._catalog_file)

        await self.hass.async_add_executor_job(write)

    # ---- reading the provider ----
    async def _async_update_data(self) -> dict[str, Any]:
        if self.client is not None:
            try:
                self.account = await self.client.account()
            except XtreamAuthError as err:
                raise ConfigEntryAuthFailed(str(err)) from err
            except XtreamError as err:
                if self.catalog is None:
                    raise UpdateFailed(str(err)) from err
                _LOGGER.debug("Account not read (%s); keeping the channel list", err)
        stale = time.time() - self.catalog_at > CATALOG_HOURS * 3600
        if self.catalog is None or stale or self._force_catalog:
            self._force_catalog = False
            try:
                catalog = await self._read_catalog()
            except (XtreamError, SourceError) as err:
                if isinstance(err, XtreamAuthError):
                    raise ConfigEntryAuthFailed(str(err)) from err
                if self.catalog is None:
                    raise UpdateFailed(f"channel list not read: {err}") from err
                _LOGGER.warning("Channel list not read (%s); keeping the last one", err)
            else:
                self.catalog, self.catalog_at = catalog, time.time()
                self._index_logos()
                await self._save_catalog()
                self.guide.schedule_rebuild(5)
                self._changed("catalog")
        return {"account": self.account, "catalog_at": self.catalog_at, "version": self.version}

    async def _read_catalog(self) -> Catalog:
        if self.client is not None:
            categories = await self.client.live_categories()
            streams = await self.client.live_streams()
            if not streams:
                raise SourceError("the provider listed no live channels")
            return catalog_from_xtream(categories, streams)
        session = async_get_clientsession(self.hass)
        try:
            async with session.get(self.entry.data[CONF_URL], headers={"User-Agent": self.user_agent},
                                   timeout=aiohttp.ClientTimeout(total=PROVIDER_TIMEOUT_SECONDS)) as resp:
                if resp.status >= 400:
                    raise SourceError(f"the playlist address answered HTTP {resp.status}")
                body = await resp.content.read(PLAYLIST_MAX_BYTES + 1)
        except (aiohttp.ClientError, TimeoutError) as err:
            raise SourceError(f"{type(err).__name__}: {err}") from err
        if len(body) > PLAYLIST_MAX_BYTES:
            raise SourceError("the playlist is over 30 MB")
        text = body.decode("utf-8", "replace")
        entries = m3u.parse(text)
        if not entries:
            raise SourceError("the playlist holds no channels")
        return catalog_from_m3u(entries, m3u.header_guides(text))

    async def async_refresh_catalog(self) -> None:
        self._force_catalog = True
        await self.async_request_refresh()

    # ---- selection ----
    async def async_select(self, changes: list[dict[str, Any]], group_order: list[str] | None = None,
                           channel_order: list[str] | None = None) -> None:
        self.selection = apply_changes(self.selection, changes, group_order, channel_order)
        await self._store.async_save({"selection": self.selection})
        self.guide.schedule_rebuild()
        self._changed("selection")

    def shown(self) -> list[Channel]:
        return shown_channels(self.catalog, self.selection) if self.catalog else []

    # ---- events ----
    @callback
    def _changed(self, what: str) -> None:
        self.version += 1
        self.hass.bus.async_fire(EVENT_UPDATED, {"entry_id": self.entry.entry_id, "what": what, "version": self.version})
        self.async_update_listeners()

    @callback
    def async_guide_changed(self) -> None:
        self._changed("guide")

    # ---- playing and logos ----
    @property
    def max_streams(self) -> int | None:
        try:
            value = int(self.account.get("max_connections") or 0)
        except (TypeError, ValueError):
            return None
        return value or None

    def upstream(self, channel: Channel) -> tuple[str, dict[str, str], str | None]:
        """(address, request headers, play kind or None to find out) for one channel. Server side only."""
        headers = {"User-Agent": channel.user_agent or self.user_agent}
        if channel.referrer:
            headers["Referer"] = channel.referrer
        if self.client is not None and channel.stream_id:
            output = str(self.options.get(CONF_OUTPUT) or DEFAULT_OUTPUT)
            return self.client.stream_url(channel.stream_id, output), headers, PLAY_RAW if output == "ts" else PLAY_HLS
        url = channel.url or ""
        return url, headers, self.play_kinds.get(channel.key) or play_kind_for_url(url)

    def _index_logos(self) -> None:
        self.logos = {}
        for c in self.catalog.channels if self.catalog else []:
            if c.logo and c.logo.lower().startswith("http://"):
                self.logos[hashlib.sha1(c.logo.encode()).hexdigest()[:16]] = c.logo

    def logo_path(self, channel: Channel) -> str | None:
        """https logos load straight from their site; http ones go through the proxy (mixed content otherwise)."""
        if not channel.logo:
            return None
        if channel.logo.lower().startswith("https://"):
            return channel.logo
        if channel.logo.lower().startswith("http://"):
            return f"{LOGO_URL}/{self.entry.entry_id}/{hashlib.sha1(channel.logo.encode()).hexdigest()[:16]}"
        return None
