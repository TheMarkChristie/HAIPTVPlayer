"""IPTV Player against a real Home Assistant (pytest-homeassistant-custom-component). Run from the repository root:

    .venv-ha\\Scripts\\python -m pytest -c tests_ha/pytest.ini tests_ha -q

The harness does not install Home Assistant's frontend, so the integration is set up without its dependencies, and its
async_setup (which serves the card and adds it to every page) is replaced by one that registers only the relay, the
logo proxy, the websocket commands and the services. The provider is stood in for by aioclient_mock: a small Xtream
panel (two groups, four channels), its guide, a free guide, a channel's playlist and its segments."""
from __future__ import annotations

import gzip
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
# import this repository's custom_components now: the harness later puts its own testing_config first on the path
import custom_components.iptv_player  # noqa: E402,F401

if sys.platform == "win32":
    # asyncio's own loop needs a local socket pair on Windows, which the harness's socket guard refuses
    import pytest_socket

    pytest_socket.disable_socket = lambda *args, **kwargs: None

from homeassistant.core import HomeAssistant  # noqa: E402
from homeassistant.loader import async_get_integration  # noqa: E402
from homeassistant.setup import async_setup_component  # noqa: E402
from pytest_homeassistant_custom_component.common import MockConfigEntry  # noqa: E402

DOMAIN = "iptv_player"
PANEL = "http://panel.example:8080"
STREAMS = "http://streams.example"
FREE_UK = "https://epgshare01.online/epgshare01/epg_ripper_UK1.xml.gz"

CATEGORIES = [{"category_id": "7", "category_name": "UNITED KINGDOM"}, {"category_id": "8", "category_name": "UK-SPORTS"}]
STREAM_LIST = [
    {"stream_id": 101, "name": "UK: BBC ONE SCOTLAND", "category_id": "7", "epg_channel_id": "BBCOneScotland.uk", "num": 1,
     "stream_icon": "http://logos.example/bbc1.png", "stream_type": "live"},
    {"stream_id": 102, "name": "UK: BBC 2", "category_id": "7", "epg_channel_id": "", "num": 2, "stream_type": "live"},
    {"stream_id": 103, "name": "UK: STV", "category_id": "7", "epg_channel_id": "", "num": 3, "stream_type": "live"},
    {"stream_id": 201, "name": "UK: SKY SPORTS F1", "category_id": "8", "epg_channel_id": "SkySportsF1.uk", "num": 10,
     "stream_type": "live"},
]


def account(max_connections: int = 2, auth: int = 1) -> dict[str, Any]:
    return {"user_info": {"username": "user", "password": "secret", "auth": auth, "status": "Active", "exp_date": "1795132800",
                          "is_trial": "0", "active_cons": "0", "max_connections": str(max_connections),
                          "allowed_output_formats": ["m3u8", "ts", "rtmp"]},
            "server_info": {"url": "streams.example", "port": "80", "https_port": "443", "server_protocol": "http",
                            "timezone": "UTC"}}


def _xt(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y%m%d%H%M%S +0000")


def guide_xml(channels: dict[str, str], now: float | None = None) -> bytes:
    """An XMLTV file: each channel id -> display name, with three hour-long programmes around now."""
    now = now or time.time()
    start = now - 1800
    parts = ['<?xml version="1.0" encoding="UTF-8"?><tv>']
    parts += [f'<channel id="{cid}"><display-name>{name}</display-name></channel>' for cid, name in channels.items()]
    for cid, name in channels.items():
        for i in range(3):
            s, e = start + i * 3600, start + (i + 1) * 3600
            parts.append(f'<programme start="{_xt(s)}" stop="{_xt(e)}" channel="{cid}"><title>{name} show {i}</title>'
                         f'<desc>About {name} {i}.</desc></programme>')
    parts.append("</tv>")
    return gzip.compress("".join(parts).encode())


@pytest.fixture
def provider(aioclient_mock) -> dict[str, Any]:
    """The stand-in Xtream panel. Returns a dict the test can change (max connections) before setup."""
    state = {"max": 2}
    aioclient_mock.get(f"{PANEL}/player_api.php?action=get_live_categories", json=CATEGORIES)
    aioclient_mock.get(f"{PANEL}/player_api.php?action=get_live_streams", json=STREAM_LIST)

    async def acct(method, url, data):
        from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMockResponse

        return AiohttpClientMockResponse(method, url, json=account(state["max"], 0 if "wrong" in str(url) else 1))

    aioclient_mock.get(f"{PANEL}/player_api.php", side_effect=acct)
    aioclient_mock.get(f"{PANEL}/xmltv.php", content=guide_xml({"BBCOneScotland.uk": "BBC One Scotland", "SkySportsF1.uk": "Sky Sports F1"}),
                       headers={"Content-Type": "application/xml"})
    aioclient_mock.get(FREE_UK, content=guide_xml({"BBC.Two.HD.uk": "BBC Two HD", "STV.HD.uk": "STV HD"}))
    for sid in (101, 102, 103, 201):
        aioclient_mock.get(f"{STREAMS}/live/user/secret/{sid}.m3u8",
                           text=f"#EXTM3U\n#EXT-X-TARGETDURATION:10\n#EXTINF:10.0,\n/hls/tok{sid}/{sid}_0.ts\n#EXTINF:10.0,\n/hls/tok{sid}/{sid}_1.ts\n",
                           headers={"Content-Type": "application/x-mpegurl"})
        # channel 201's first segment comes gzip-marked with the packed length, as NRK's subtitle segments do
        packed = {"Content-Encoding": "gzip", "Content-Length": "27"} if sid == 201 else {}
        aioclient_mock.get(f"{STREAMS}/hls/tok{sid}/{sid}_0.ts", content=b"G" + bytes(187) * 3,
                           headers={"Content-Type": "video/mp2t", **packed})
    aioclient_mock.get("http://logos.example/bbc1.png", content=b"\x89PNG\r\n\x1a\nlogo", headers={"Content-Type": "image/png"})
    return state


async def _light_setup(hass: HomeAssistant, config: Any) -> bool:
    from custom_components.iptv_player import const, relay, services, views, websocket

    rel = relay.Relay(hass)
    hass.data[const.DOMAIN] = {"relay": rel}
    for view in relay.relay_views(hass, rel):
        hass.http.register_view(view)
    hass.http.register_view(views.LogoView(hass))
    websocket.async_register_websocket(hass)
    services.async_register_services(hass)
    return True


@pytest.fixture(autouse=True)
async def light_setup(hass: HomeAssistant, enable_custom_integrations: None, tmp_path):
    hass.config.config_dir = str(tmp_path)          # the cache folder (.cache/iptv_player) per test, not the harness's shared one
    await async_setup_component(hass, "http", {})
    integration = await async_get_integration(hass, DOMAIN)
    integration.__dict__["dependencies"] = []
    with patch("custom_components.iptv_player.async_setup", _light_setup):
        yield


def xtream_entry(**options: Any) -> MockConfigEntry:
    from custom_components.iptv_player.const import (
        CONF_GUIDE_HOUR, CONF_GUIDE_HOURS, CONF_GUIDE_URLS, CONF_OUTPUT, CONF_PLAYERS, CONF_PROVIDER_GUIDE, CONF_USER_AGENT,
    )

    return MockConfigEntry(
        domain=DOMAIN, title="Provider", unique_id="xtream:panel.example:8080:user",
        data={"kind": "xtream", "url": PANEL, "username": "user", "password": "secret"},
        options={CONF_PROVIDER_GUIDE: True, CONF_GUIDE_URLS: FREE_UK, CONF_GUIDE_HOURS: 36, CONF_GUIDE_HOUR: 4,
                 CONF_OUTPUT: "m3u8", CONF_PLAYERS: [], CONF_USER_AGENT: "Mozilla/5.0", **options},
    )


async def setup_xtream(hass: HomeAssistant, **options: Any):
    entry = xtream_entry(**options)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    return entry, entry.runtime_data
