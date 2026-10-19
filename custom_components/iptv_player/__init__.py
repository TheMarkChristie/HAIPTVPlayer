"""IPTV Player: live TV in Home Assistant from an IPTV login (Xtream Codes) or an M3U playlist, showing only the
groups and channels chosen in the card's Manage channels, with a TV guide from the provider and free XMLTV sources.

The integration serves its own card and two player libraries (hls.js, mpegts.js), relays every stream through Home
Assistant (no mixed content, no CORS, the provider password never reaches a device), proxies http logos, and offers
websocket commands, two services (play, refresh), sensors and the channels under Media. The views, websocket commands
and services are registered once, in async_setup, and look the loaded entries up per call."""
from __future__ import annotations

import hashlib
from pathlib import Path

from homeassistant.components import frontend
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType
from homeassistant.loader import async_get_integration

from .card_resource import async_remove_card_resource, async_schedule_card_resource
from .const import CARD_FILE, DOMAIN, URL_BASE
from .coordinator import IPTVCoordinator
from .relay import Relay, relay_views
from .services import async_register_services
from .views import LogoView
from .websocket import async_register_websocket

PLATFORMS = [Platform.SENSOR]
_CARD_URL = f"{DOMAIN}_card_url"


def _card_hash() -> str:
    try:
        return hashlib.sha256((Path(__file__).parent / "www" / CARD_FILE).read_bytes()).hexdigest()[:10]
    except OSError:
        return "0"


async def _card_url(hass: HomeAssistant) -> str:
    """The card's URL with a version and a hash of the file, so a changed file is never served from a browser cache."""
    if url := hass.data.get(_CARD_URL):
        return url
    integration = await async_get_integration(hass, DOMAIN)
    digest = await hass.async_add_executor_job(_card_hash)
    url = f"{URL_BASE}/{CARD_FILE}?v={integration.version}-{digest}"
    hass.data[_CARD_URL] = url
    return url


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Serve the card, put it in front of every dashboard, and register the relay, the logo proxy, the websocket
    commands and the services. Once per run: views cannot be removed, so they are never registered twice."""
    if DOMAIN in hass.data:
        return True
    relay = Relay(hass)
    hass.data[DOMAIN] = {"relay": relay}
    await hass.http.async_register_static_paths(
        [StaticPathConfig(URL_BASE, str(Path(__file__).parent / "www"), cache_headers=False)])
    for view in relay_views(hass, relay):
        hass.http.register_view(view)
    hass.http.register_view(LogoView(hass))
    async_register_websocket(hass)
    async_register_services(hass)
    url = await _card_url(hass)
    frontend.add_extra_js_url(hass, url)
    async_schedule_card_resource(hass, url)
    return True


def coordinators(hass: HomeAssistant) -> list[IPTVCoordinator]:
    out: list[IPTVCoordinator] = []
    for entry in hass.config_entries.async_entries(DOMAIN):
        coordinator = getattr(entry, "runtime_data", None)
        if isinstance(coordinator, IPTVCoordinator):
            out.append(coordinator)
    return out


def coordinator_for(hass: HomeAssistant, entry_id: str | None = None) -> IPTVCoordinator | None:
    for coordinator in coordinators(hass):
        if entry_id is None or coordinator.entry.entry_id == entry_id:
            return coordinator
    return None


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    coordinator = IPTVCoordinator(hass, entry)
    await coordinator.async_load()
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await coordinator.guide.async_start()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_options_changed))
    entry.async_on_unload(coordinator.guide.async_stop)
    return True


async def _async_options_changed(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if ok:
        entry.runtime_data = None          # the services and the card then say the entry is not loaded
    return ok


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """The last entry removed drops the card's dashboard resource."""
    if not any(e.entry_id != entry.entry_id for e in hass.config_entries.async_entries(DOMAIN)):
        frontend.remove_extra_js_url(hass, await _card_url(hass))
        await async_remove_card_resource(hass)
