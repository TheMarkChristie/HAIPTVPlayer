"""The guide for one entry: download each XMLTV source once a day into Home Assistant's cache folder (not in backups),
then read it as a stream for the channels shown, from three hours ago to 36 hours ahead.

Sources, first match wins: the provider's own guide (Xtream), the guides a playlist names in its header (when it names
five or fewer), and the extra addresses in the options (epgshare01 UK1 fills the gaps by default). A guide over 60 MB
compressed is refused. Choosing channels re-reads the downloaded files (no download); only the daily refresh and the
Refresh service download."""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

import aiohttp
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_call_later, async_track_time_change

from .const import (
    CONF_GUIDE_HOUR, CONF_GUIDE_HOURS, CONF_GUIDE_URLS, CONF_PROVIDER_GUIDE, DEFAULT_GUIDE_HOUR, DEFAULT_GUIDE_HOURS,
    DOMAIN, GUIDE_DESC_CHARS, GUIDE_MAX_AGE_HOURS, GUIDE_MAX_DOWNLOAD_MB, GUIDE_MAX_HEADER_URLS, GUIDE_PAST_HOURS,
    KIND_XTREAM,
)
from .model import GuideSource, Programme, match_guides, shown_channels
from .xmltv import read_channels, read_programmes

if TYPE_CHECKING:
    from .coordinator import IPTVCoordinator

_LOGGER = logging.getLogger(__name__)
PROVIDER_LABEL = "Provider guide"


@dataclass
class SourceStatus:
    label: str
    url: str                      # never shown when it carries a password (the provider's)
    secret: bool = False
    path: str = ""
    downloaded_at: float | None = None
    size: int = 0
    channels: int = 0
    error: str | None = None

    def public(self) -> dict[str, Any]:
        return {"label": self.label, "url": None if self.secret else self.url, "downloaded_at": self.downloaded_at,
                "size": self.size, "channels": self.channels, "error": self.error}


@dataclass
class GuideState:
    sources: list[GuideSource] = field(default_factory=list)
    matches: dict[str, tuple[int, str, str]] = field(default_factory=dict)    # channel key -> (source, id, how)
    programmes: dict[str, list[Programme]] = field(default_factory=dict)      # channel key -> programmes
    built_at: float | None = None


def label_for(url: str) -> str:
    name = os.path.basename(urlsplit(url).path) or urlsplit(url).netloc
    for ext in (".gz", ".xml"):
        if name.lower().endswith(ext):
            name = name[: -len(ext)]
    return name.replace("epg_ripper_", "epgshare01 ") or url


def configured_urls(options: dict[str, Any], header: list[str]) -> list[str]:
    """The extra guide addresses: the options' lines, else the playlist header's (five or fewer, never an
    all-countries file)."""
    lines = [u.strip() for u in str(options.get(CONF_GUIDE_URLS) or "").splitlines() if u.strip()]
    if CONF_GUIDE_URLS in options:
        return [u for u in lines if u.startswith(("http://", "https://"))]
    usable = [u for u in header if "ALL_SOURCES" not in u.upper()]
    return usable if len(usable) <= GUIDE_MAX_HEADER_URLS else []


class GuideManager:
    def __init__(self, hass: HomeAssistant, coordinator: IPTVCoordinator) -> None:
        self.hass = hass
        self.coordinator = coordinator
        self.state = GuideState()
        self.status: list[SourceStatus] = []
        self._lock = asyncio.Lock()
        self._unsubs: list[Any] = []
        self._rebuild_handle: Any = None
        self.folder = hass.config.cache_path(DOMAIN)

    # ---- sources ----
    def _sources(self) -> list[SourceStatus]:
        c = self.coordinator
        out: list[SourceStatus] = []
        if c.kind == KIND_XTREAM and c.options.get(CONF_PROVIDER_GUIDE, True) and c.client is not None:
            out.append(SourceStatus(PROVIDER_LABEL, c.client.guide_url(), secret=True))
        for url in configured_urls(c.options, c.catalog.guide_urls if c.catalog else []):
            if not any(s.url == url for s in out):
                out.append(SourceStatus(label_for(url), url))
        for s in out:
            digest = hashlib.sha1(f"{c.entry.entry_id}|{s.url}".encode()).hexdigest()[:12]
            s.path = os.path.join(self.folder, f"{c.entry.entry_id}-{digest}.xml")
            if os.path.exists(s.path):
                st = os.stat(s.path)
                s.downloaded_at, s.size = st.st_mtime, st.st_size
        return out

    # ---- lifecycle ----
    async def async_start(self) -> None:
        """Read what is on disk now; download what is missing or a day old in the background; refresh daily."""
        hour = int(self.coordinator.options.get(CONF_GUIDE_HOUR, DEFAULT_GUIDE_HOUR))
        minute = int(hashlib.sha1(self.coordinator.entry.entry_id.encode()).hexdigest(), 16) % 50 + 5
        self._unsubs.append(async_track_time_change(self.hass, self._daily, hour=hour, minute=minute, second=0))
        self.coordinator.entry.async_create_background_task(self.hass, self.async_refresh(download=None), f"{DOMAIN} guide")

    @callback
    def async_stop(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        if self._rebuild_handle:
            self._rebuild_handle()
            self._rebuild_handle = None

    async def _daily(self, _now: Any) -> None:
        await self.async_refresh(download=True)

    @callback
    def schedule_rebuild(self, delay: float = 15) -> None:
        """After the selection changes: read the guide again for the new channels, once the changes settle."""
        if self._rebuild_handle:
            self._rebuild_handle()

        async def _run(_now: Any) -> None:
            self._rebuild_handle = None
            await self.async_refresh(download=False)

        self._rebuild_handle = async_call_later(self.hass, delay, _run)

    # ---- work ----
    async def async_refresh(self, download: bool | None) -> None:
        """download True: fetch every source; None: only missing or stale ones; False: none."""
        async with self._lock:
            sources = self._sources()
            await self.hass.async_add_executor_job(os.makedirs, self.folder, 0o755, True)
            for s in sources:
                stale = s.downloaded_at is None or time.time() - s.downloaded_at > GUIDE_MAX_AGE_HOURS * 3600
                if download or (download is None and stale):
                    await self._download(s)
            self.status = sources
            await self._rebuild(sources)

    async def _download(self, s: SourceStatus) -> None:
        session = async_get_clientsession(self.hass)
        tmp = s.path + ".part"
        limit = GUIDE_MAX_DOWNLOAD_MB * 1024 * 1024
        # gzip only: aiohttp would also offer brotli and zstd, which the reader cannot open (a provider chose one on
        # 19 Oct 2026 and the guide read as empty)
        headers = {"User-Agent": self.coordinator.user_agent, "Accept-Encoding": "gzip"}
        try:
            async with session.get(s.url, headers=headers, timeout=aiohttp.ClientTimeout(total=600, sock_read=60),
                                   auto_decompress=False) as resp:
                if resp.status >= 400:
                    raise OSError(f"HTTP {resp.status}")
                encoding = resp.headers.get("Content-Encoding", "").lower()
                if encoding not in ("", "gzip", "identity", "x-gzip"):
                    raise OSError(f"answered in {encoding}, which cannot be read")
                length = resp.headers.get("Content-Length", "")
                if length.isdigit() and int(length) > limit:
                    raise OSError(f"{int(length) // 1_000_000} MB is over the {GUIDE_MAX_DOWNLOAD_MB} MB limit")
                # kept as it came: a gzip-encoded answer stays compressed on disk, and the reader recognises gzip by
                # its first bytes
                f = await self.hass.async_add_executor_job(open, tmp, "wb")
                size = 0
                try:
                    async for chunk in resp.content.iter_chunked(1 << 20):
                        size += len(chunk)
                        if size > limit:
                            raise OSError(f"over the {GUIDE_MAX_DOWNLOAD_MB} MB limit")
                        await self.hass.async_add_executor_job(f.write, chunk)
                finally:
                    await self.hass.async_add_executor_job(f.close)
            await self.hass.async_add_executor_job(os.replace, tmp, s.path)
            s.downloaded_at, s.size, s.error = time.time(), size, None
            _LOGGER.debug("Guide %s downloaded, %d bytes", s.label, size)
        except (aiohttp.ClientError, TimeoutError, OSError) as err:
            s.error = self.coordinator.scrub(f"{type(err).__name__}: {err}")
            _LOGGER.warning("Guide %s not downloaded: %s", s.label, s.error)
            try:
                await self.hass.async_add_executor_job(os.remove, tmp)
            except OSError:
                pass

    async def _rebuild(self, sources: list[SourceStatus]) -> None:
        c = self.coordinator
        if c.catalog is None:
            return
        channels = shown_channels(c.catalog, c.selection)
        selection = c.selection
        hours = int(c.options.get(CONF_GUIDE_HOURS, DEFAULT_GUIDE_HOURS))
        now = int(time.time())
        start, end = now - GUIDE_PAST_HOURS * 3600, now + hours * 3600

        def work() -> GuideState:
            guide_sources: list[GuideSource] = []
            for s in sources:
                names: dict[str, list[str]] = {}
                if s.downloaded_at is not None:
                    try:
                        names = read_channels(s.path)
                    except (OSError, EOFError, ValueError) as err:
                        s.error = f"unreadable: {err}"
                s.channels = len(names)
                guide_sources.append(GuideSource(s.label, names))
            matches = match_guides(channels, selection, guide_sources)
            wanted: list[set[str]] = [set() for _ in sources]
            for src, gid, _how in matches.values():
                wanted[src].add(gid)
            by_source: list[dict[str, list[Programme]]] = []
            for i, s in enumerate(sources):
                try:
                    by_source.append(read_programmes(s.path, wanted[i], start, end, GUIDE_DESC_CHARS) if wanted[i] else {})
                except (OSError, EOFError, ValueError) as err:
                    s.error = f"unreadable: {err}"
                    by_source.append({})
            programmes = {key: by_source[src].get(gid, []) for key, (src, gid, _how) in matches.items()}
            return GuideState(guide_sources, matches, programmes, time.time())

        started = time.monotonic()
        self.state = await self.hass.async_add_executor_job(work)
        _LOGGER.debug("Guide read for %d channels in %.1f s", len(channels), time.monotonic() - started)
        c.async_guide_changed()

    def public_status(self) -> list[dict[str, Any]]:
        return [s.public() for s in self.status]
