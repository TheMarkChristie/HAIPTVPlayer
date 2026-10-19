"""The chosen channels under Media in Home Assistant: source, then group, then channel. Playing one opens a relay
session, so any media player that takes a stream address can play it."""
from __future__ import annotations

from homeassistant.components.media_player import BrowseError, MediaClass
from homeassistant.components.media_source import BrowseMediaSource, MediaSource, MediaSourceItem, PlayMedia, Unresolvable
from homeassistant.core import HomeAssistant

from .const import DOMAIN, NAME, PLAY_HLS
from .model import group_name, tidy_name


async def async_get_media_source(hass: HomeAssistant) -> MediaSource:
    return IPTVMediaSource(hass)


def _coordinators(hass: HomeAssistant):
    from . import coordinators  # noqa: PLC0415

    return [c for c in coordinators(hass) if c.catalog is not None]


class IPTVMediaSource(MediaSource):
    name = NAME

    def __init__(self, hass: HomeAssistant) -> None:
        super().__init__(DOMAIN)
        self.hass = hass

    async def async_resolve_media(self, item: MediaSourceItem) -> PlayMedia:
        from .websocket import open_session  # noqa: PLC0415

        entry_id, _, key = (item.identifier or "").partition("/")
        for c in _coordinators(self.hass):
            if c.entry.entry_id == entry_id and (channel := c.catalog.channel(key)):
                session = await open_session(self.hass, c, channel)
                if isinstance(session, str):
                    raise Unresolvable(session)
                mime = "application/vnd.apple.mpegurl" if session.kind == PLAY_HLS else "video/mp2t"
                return PlayMedia(session.path, mime)
        raise Unresolvable("That channel is not there any more")

    async def async_browse_media(self, item: MediaSourceItem) -> BrowseMediaSource:
        parts = [p for p in (item.identifier or "").split("/", 2) if p]
        loaded = _coordinators(self.hass)
        if not parts:
            children = [self._folder(c.entry.entry_id, c.entry.title) for c in loaded if c.shown()]
            return self._folder("", NAME, children)
        c = next((c for c in loaded if c.entry.entry_id == parts[0]), None)
        if c is None:
            raise BrowseError("That source is not loaded")
        shown = c.shown()
        if len(parts) == 1:
            names = {g.id: group_name(g, c.selection) for g in c.catalog.groups}
            groups: list[str] = []
            for ch in shown:
                if ch.group not in groups:
                    groups.append(ch.group)
            return self._folder(parts[0], c.entry.title,
                                [self._folder(f"{parts[0]}/g/{gid}", names.get(gid, gid)) for gid in groups])
        gid = item.identifier.split("/g/", 1)[1] if "/g/" in item.identifier else ""
        children = [BrowseMediaSource(
            domain=DOMAIN, identifier=f"{c.entry.entry_id}/{ch.key}", media_class=MediaClass.CHANNEL,
            media_content_type="video", title=str(c.selection["channels"].get(ch.key, {}).get("name") or "") or tidy_name(ch.name),
            can_play=True, can_expand=False,
            thumbnail=ch.logo if ch.logo and ch.logo.startswith("https://") else None,
        ) for ch in shown if ch.group == gid]
        return self._folder(item.identifier, next((group_name(g, c.selection) for g in c.catalog.groups if g.id == gid), gid), children)

    def _folder(self, identifier: str, title: str, children: list[BrowseMediaSource] | None = None) -> BrowseMediaSource:
        return BrowseMediaSource(
            domain=DOMAIN, identifier=identifier or None, media_class=MediaClass.DIRECTORY, media_content_type="",
            title=title, can_play=False, can_expand=True, children=children,
            children_media_class=MediaClass.CHANNEL if children and children[0].media_class == MediaClass.CHANNEL else MediaClass.DIRECTORY,
        )
