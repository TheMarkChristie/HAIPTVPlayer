"""Sign-in, channels and selection, the guide, the relay, Play on TV and the media browser in a real Home Assistant."""
from __future__ import annotations

import re
import time

from homeassistant import config_entries
from homeassistant.components import media_source
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.setup import async_setup_component

from conftest import DOMAIN, FREE_UK, PANEL, setup_xtream


async def test_config_flow_xtream(hass: HomeAssistant, provider) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.MENU
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"next_step_id": "xtream"})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"url": "panel.example:8080/", "username": "user", "password": "wrong"})
    assert result["errors"] == {"base": "invalid_auth"}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"url": "panel.example:8080/", "username": "user", "password": "secret"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["url"] == PANEL and result["options"]["output"] == "m3u8"
    assert result["options"]["guide_urls"] == FREE_UK and result["options"]["provider_guide"] is True


async def test_config_flow_m3u_header_guides(hass: HomeAssistant, aioclient_mock) -> None:
    many = ", ".join(f"https://g.example/{i}.xml.gz" for i in range(8))
    aioclient_mock.get("https://free.example/many.m3u8", text=f'#EXTM3U x-tvg-url="{many}"\n#EXTINF:-1 group-title="UK",A\nhttps://a/a.m3u8\n')
    aioclient_mock.get("https://free.example/two.m3u8", text='#EXTM3U url-tvg="https://g.example/uk.xml.gz, https://g.example/ALL_SOURCES1.xml.gz"\n#EXTINF:-1,A\nhttps://a/a.m3u8\n')
    aioclient_mock.get("https://free.example/none.m3u8", text="<html>nothing</html>")
    aioclient_mock.get(re.compile(r"https://g\.example/.*"), status=404)          # the new entries' guide downloads
    for url, guides in (("https://free.example/many.m3u8", ""), ("https://free.example/two.m3u8", "https://g.example/uk.xml.gz")):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"next_step_id": "m3u"})
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"url": url, "name": "Free"})
        assert result["type"] is FlowResultType.CREATE_ENTRY and result["options"]["guide_urls"] == guides
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"next_step_id": "m3u"})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"url": "https://free.example/none.m3u8"})
    assert result["errors"] == {"base": "no_playlist"}


async def test_selection_channels_and_guide(hass: HomeAssistant, provider, hass_ws_client) -> None:
    entry, c = await setup_xtream(hass)
    ws = await hass_ws_client(hass)
    await ws.send_json({"id": 1, "type": "iptv_player/channels"})
    msg = await ws.receive_json()
    assert msg["success"] and msg["result"]["channels"] == [] and msg["result"]["is_admin"]
    assert msg["result"]["entries"][0]["account"]["max_connections"] == "2"

    await ws.send_json({"id": 2, "type": "iptv_player/select", "entry_id": entry.entry_id,
                        "changes": [{"group": "7", "on": True}, {"channel": "103", "on": False}]})
    assert (await ws.receive_json())["result"]["shown"] == 2
    await c.guide.async_refresh(download=False)          # what the debounced rebuild does

    await ws.send_json({"id": 3, "type": "iptv_player/channels"})
    result = (await ws.receive_json())["result"]
    names = [ch["name"] for ch in result["channels"]]
    assert names == ["BBC ONE SCOTLAND", "BBC 2"]
    bbc1, bbc2 = result["channels"]
    assert bbc1["now"]["title"] == "BBC One Scotland show 0" and bbc1["next"]["title"] == "BBC One Scotland show 1"
    assert bbc2["now"]["title"] == "BBC Two HD show 0"                  # filled from the free guide by name
    assert bbc1["logo"].startswith("/api/iptv_player/logo/") and "authSig=" in bbc1["logo"]
    assert "secret" not in str(result)

    await ws.send_json({"id": 4, "type": "iptv_player/catalog", "entry_id": entry.entry_id})
    cat = (await ws.receive_json())["result"]
    assert [(g["name"], g["on"], g["shown"], g["total"]) for g in cat["groups"]] == [("UNITED KINGDOM", True, 2, 3), ("UK-SPORTS", False, 0, 1)]
    assert cat["guide"]["matched"] == 2 and [s["label"] for s in cat["guide"]["sources"]] == ["Provider guide", "epgshare01 UK1"]
    assert cat["guide"]["sources"][0]["url"] is None                     # the provider's guide address carries the password
    await ws.send_json({"id": 5, "type": "iptv_player/catalog", "entry_id": entry.entry_id, "group": "7"})
    chans = (await ws.receive_json())["result"]["channels"]
    assert [(x["key"], x["on"], x["own"]) for x in chans] == [("101", True, None), ("102", True, None), ("103", False, False)]
    assert chans[1]["guide"] == {"source": "epgshare01 UK1", "id": "BBC.Two.HD.uk", "how": "name"}

    await ws.send_json({"id": 6, "type": "iptv_player/guide", "entry_id": entry.entry_id, "keys": ["101"], "details": True})
    progs = (await ws.receive_json())["result"]["programmes"]["101"]
    assert len(progs) == 3 and progs[0]["desc"] == "About BBC One Scotland 0."

    await ws.send_json({"id": 7, "type": "iptv_player/guide_search", "entry_id": entry.entry_id, "query": "stv"})
    found = (await ws.receive_json())["result"]["results"]
    assert found[0]["id"] == "STV.HD.uk"
    await ws.send_json({"id": 8, "type": "iptv_player/select", "entry_id": entry.entry_id,
                        "changes": [{"channel": "103", "on": True, "name": "STV North", "guide": "epgshare01 UK1|STV.HD.uk"}]})
    await ws.receive_json()
    await c.guide.async_refresh(download=False)
    await ws.send_json({"id": 9, "type": "iptv_player/channels"})
    stv = (await ws.receive_json())["result"]["channels"][-1]
    assert stv["name"] == "STV North" and stv["now"]["title"] == "STV HD show 0"

    assert hass.states.get("sensor.iptv_player_provider_channels_shown").state == "3"
    assert hass.states.get("sensor.iptv_player_provider_connections_in_use").state == "0"
    assert hass.states.get("sensor.iptv_player_provider_subscription_ends").state.startswith("2026-11-20")


async def test_relay_and_connection_limit(hass: HomeAssistant, provider, hass_ws_client, hass_client_no_auth) -> None:
    provider["max"] = 1
    entry, c = await setup_xtream(hass)
    ws = await hass_ws_client(hass)
    await ws.send_json({"id": 1, "type": "iptv_player/stream", "entry_id": entry.entry_id, "key": "101"})
    s = (await ws.receive_json())["result"]
    assert s["kind"] == "hls" and s["url"].endswith("/index.m3u8") and "secret" not in s["url"]

    client = await hass_client_no_auth()                 # a Cast device has no sign-in: the token is the key
    resp = await client.get(s["url"])
    assert resp.status == 200 and resp.headers["Access-Control-Allow-Origin"] == "*"
    text = await resp.text()
    assert "streams.example" not in text and "secret" not in text
    segment = [line for line in text.splitlines() if line.startswith("s/")][0]
    base = s["url"].rsplit("/", 1)[0]
    resp = await client.get(f"{base}/{segment}")
    assert resp.status == 200 and resp.headers["Content-Type"] == "video/mp2t" and (await resp.read())[:1] == b"G"

    # the login allows one stream and this one was just asked for: a second channel is refused, not pushed off
    await ws.send_json({"id": 2, "type": "iptv_player/stream", "entry_id": entry.entry_id, "key": "102"})
    msg = await ws.receive_json()
    assert not msg["success"] and msg["error"]["code"] == "busy"
    # the same channel is shared
    await ws.send_json({"id": 3, "type": "iptv_player/stream", "entry_id": entry.entry_id, "key": "101"})
    assert (await ws.receive_json())["result"]["token"] == s["token"]

    for i in (4, 5):
        await ws.send_json({"id": i, "type": "iptv_player/release", "token": s["token"]})
        await ws.receive_json()
    assert (await client.get(s["url"])).status == 404
    await ws.send_json({"id": 6, "type": "iptv_player/stream", "entry_id": entry.entry_id, "key": "102"})
    assert (await ws.receive_json())["success"]


async def test_logo_proxy(hass: HomeAssistant, provider, hass_ws_client, hass_client) -> None:
    entry, c = await setup_xtream(hass)
    await c.async_select([{"group": "7", "on": True}])
    ws = await hass_ws_client(hass)
    await ws.send_json({"id": 1, "type": "iptv_player/channels"})
    logo = (await ws.receive_json())["result"]["channels"][0]["logo"]
    client = await hass_client()
    resp = await client.get(logo)
    assert resp.status == 200 and resp.headers["Content-Type"] == "image/png"


async def test_play_service(hass: HomeAssistant, provider) -> None:
    entry, c = await setup_xtream(hass)
    await c.async_select([{"group": "7", "on": True}])
    calls: list[ServiceCall] = []

    async def play_media(call: ServiceCall) -> None:
        calls.append(call)

    hass.services.async_register("media_player", "play_media", play_media)
    await hass.services.async_call(DOMAIN, "play", {"channel": "BBC One Scotland", "player": "media_player.tv"}, blocking=True)
    data = calls[0].data
    assert data["entity_id"] == ["media_player.tv"] or data["entity_id"] == "media_player.tv"
    assert data["media_content_id"].startswith("/api/iptv_player/hls/") and data["media_content_type"] == "application/vnd.apple.mpegurl"
    assert data["extra"]["stream_type"] == "LIVE" and data["extra"]["metadata"]["title"] == "BBC ONE SCOTLAND"


async def test_media_source(hass: HomeAssistant, provider) -> None:
    assert await async_setup_component(hass, "media_source", {})
    entry, c = await setup_xtream(hass)
    await c.async_select([{"group": "7", "on": True}])
    root = await media_source.async_browse_media(hass, f"{media_source.URI_SCHEME}{DOMAIN}")
    assert [x.title for x in root.children] == ["Provider"]
    groups = await media_source.async_browse_media(hass, root.children[0].media_content_id)
    assert [x.title for x in groups.children] == ["UNITED KINGDOM"]
    chans = await media_source.async_browse_media(hass, groups.children[0].media_content_id)
    assert [x.title for x in chans.children] == ["BBC ONE SCOTLAND", "BBC 2", "STV"]
    play = await media_source.async_resolve_media(hass, chans.children[0].media_content_id, None)
    assert play.url.startswith("/api/iptv_player/hls/") and play.mime_type == "application/vnd.apple.mpegurl"


async def test_catalog_cached_across_restart(hass: HomeAssistant, provider, aioclient_mock) -> None:
    entry, c = await setup_xtream(hass)
    asked = sum(1 for call in aioclient_mock.mock_calls if "get_live_streams" in str(call[1]))
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    again = sum(1 for call in aioclient_mock.mock_calls if "get_live_streams" in str(call[1]))
    assert asked == 1 and again == 1                      # the channel list came from the cache, not the provider
    assert entry.runtime_data.catalog is not None and len(entry.runtime_data.catalog.channels) == 4
    assert time.time() - entry.runtime_data.catalog_at < 60


async def test_read_capped_reads_every_chunk(hass: HomeAssistant) -> None:
    """A body that arrives in pieces is read whole (StreamReader.read(n) stops at what has arrived)."""
    import asyncio
    from unittest import mock

    from aiohttp.streams import StreamReader

    from custom_components.iptv_player.net import TooBig, read_capped

    def answer() -> mock.Mock:
        stream = StreamReader(mock.Mock(_reading_paused=False), limit=2**16)
        stream.feed_data(b"#EXTM3U\n" + b"a" * 100)
        loop = asyncio.get_running_loop()
        loop.call_soon(stream.feed_data, b"b" * 100)
        loop.call_soon(stream.feed_eof)
        return mock.Mock(content=stream)

    assert len(await answer().content.read(10_000)) == 108          # what the old code got
    assert len(await read_capped(answer(), 10_000)) == 208
    try:
        await read_capped(answer(), 150)
    except TooBig:
        pass
    else:
        raise AssertionError("no limit")

