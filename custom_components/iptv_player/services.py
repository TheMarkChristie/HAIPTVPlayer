"""Services: iptv_player.play (a channel on a TV) and iptv_player.refresh (read the channel list and the guide again).

Play opens a relay session and hands its address to media_player.play_media; Home Assistant makes the address absolute
with its own (home network) URL, so a Cast device fetches the channel from the Green, never from the provider."""
from __future__ import annotations

import voluptuous as vol
from homeassistant.components.media_player import ATTR_MEDIA_CONTENT_ID, ATTR_MEDIA_CONTENT_TYPE, ATTR_MEDIA_EXTRA
from homeassistant.components.media_player import DOMAIN as MP_DOMAIN, SERVICE_PLAY_MEDIA
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv

from .const import ATTR_CHANNEL, ATTR_ENTRY_ID, ATTR_GUIDE, ATTR_PLAYER, DOMAIN, PLAY_HLS, SERVICE_PLAY, SERVICE_REFRESH
from .model import display_name, norm_name, tidy_name

PLAY_SCHEMA = vol.Schema({
    vol.Required(ATTR_CHANNEL): cv.string,
    vol.Required(ATTR_PLAYER): cv.entity_id,
    vol.Optional(ATTR_ENTRY_ID): cv.string,
})
REFRESH_SCHEMA = vol.Schema({vol.Optional(ATTR_ENTRY_ID): cv.string, vol.Optional(ATTR_GUIDE, default=True): cv.boolean})


@callback
def async_register_services(hass: HomeAssistant) -> None:
    """Registered once, in async_setup; each call looks the loaded entries up."""
    hass.services.async_register(DOMAIN, SERVICE_PLAY, _play, schema=PLAY_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_REFRESH, _refresh, schema=REFRESH_SCHEMA)


def find_channel(hass: HomeAssistant, wanted: str, entry_id: str | None = None):
    """(coordinator, channel) for a uid ("<entry>:<key>"), a key, or a shown channel's name."""
    from . import coordinators  # noqa: PLC0415

    loaded = [c for c in coordinators(hass) if c.catalog is not None and entry_id in (None, c.entry.entry_id)]
    if ":" in wanted:
        eid, _, key = wanted.partition(":")
        for c in loaded:
            if c.entry.entry_id == eid and (ch := c.catalog.channel(key)):
                return c, ch
    for c in loaded:
        if ch := c.catalog.channel(wanted):
            return c, ch
    target = norm_name(wanted)
    for c in loaded:
        for ch in c.shown():
            if target in (norm_name(display_name(ch, c.selection)), norm_name(ch.name)):
                return c, ch
    return None, None


async def _play(call: ServiceCall) -> None:
    from .websocket import open_session  # noqa: PLC0415

    hass = call.hass
    c, channel = find_channel(hass, call.data[ATTR_CHANNEL], call.data.get(ATTR_ENTRY_ID))
    if channel is None:
        raise ServiceValidationError(f"No channel called {call.data[ATTR_CHANNEL]}")
    session = await open_session(hass, c, channel)
    if isinstance(session, str):
        raise HomeAssistantError(session)
    name = str(c.selection["channels"].get(channel.key, {}).get("name") or "") or tidy_name(channel.name)
    if session.kind == PLAY_HLS:
        media_type = "application/vnd.apple.mpegurl"
    else:
        media_type = "audio/mpeg" if (channel.url or "").lower().endswith(".mp3") else "video/mp2t"
    metadata = {"metadataType": 0, "title": name}
    logo = c.logo_path(channel)
    if logo and logo.startswith("https://"):
        metadata["images"] = [{"url": logo}]
    await hass.services.async_call(MP_DOMAIN, SERVICE_PLAY_MEDIA, {
        ATTR_ENTITY_ID: call.data[ATTR_PLAYER],
        ATTR_MEDIA_CONTENT_ID: session.path,
        ATTR_MEDIA_CONTENT_TYPE: media_type,
        ATTR_MEDIA_EXTRA: {"stream_type": "LIVE", "metadata": metadata},
    }, blocking=True, context=call.context)


async def _refresh(call: ServiceCall) -> None:
    from . import coordinators  # noqa: PLC0415

    loaded = [c for c in coordinators(call.hass) if call.data.get(ATTR_ENTRY_ID) in (None, c.entry.entry_id)]
    if not loaded:
        raise ServiceValidationError("IPTV Player is not loaded")
    for c in loaded:
        await c.async_refresh_catalog()
        if call.data.get(ATTR_GUIDE, True):
            await c.guide.async_refresh(download=True)
