"""The relay never passes on a Content-Length that no longer fits the body it sends (NRK's subtitle segments, 19 Oct
2026: a player told 27 bytes that gets 7 waits for the rest, and hls.js gave the channel up)."""
from __future__ import annotations

from homeassistant.core import HomeAssistant

from conftest import resolve, setup_xtream


async def test_relay_asks_uncompressed_and_drops_a_packed_length(hass: HomeAssistant, provider, aioclient_mock,
                                                                  hass_ws_client, hass_client_no_auth) -> None:
    entry, c = await setup_xtream(hass)
    ws = await hass_ws_client(hass)
    await ws.send_json({"id": 1, "type": "iptv_player/stream", "entry_id": entry.entry_id, "key": "201"})
    s = (await ws.receive_json())["result"]
    client = await hass_client_no_auth()
    text = await (await client.get(s["url"])).text()
    first = resolve(s["url"], [line for line in text.splitlines() if line and not line.startswith("#")][0])
    resp = await client.get(first)
    body = await resp.read()
    assert resp.status == 200 and len(body) == 562
    assert resp.headers.get("Content-Length") in (None, str(len(body)))          # never the packed 27
    sent = [call for call in aioclient_mock.mock_calls if str(call[1]).endswith("201_0.ts")]
    assert sent and sent[-1][3].get("Accept-Encoding") == "identity"


async def test_plain_segments_keep_their_length(hass: HomeAssistant, provider, hass_ws_client, hass_client_no_auth) -> None:
    entry, c = await setup_xtream(hass)
    ws = await hass_ws_client(hass)
    await ws.send_json({"id": 1, "type": "iptv_player/stream", "entry_id": entry.entry_id, "key": "101"})
    s = (await ws.receive_json())["result"]
    client = await hass_client_no_auth()
    text = await (await client.get(s["url"])).text()
    first = resolve(s["url"], [line for line in text.splitlines() if line and not line.startswith("#")][0])
    resp = await client.get(first)
    assert resp.status == 200 and len(await resp.read()) == 562
