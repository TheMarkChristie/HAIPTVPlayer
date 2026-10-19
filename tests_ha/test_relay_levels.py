"""A two-level channel (master list -> encrypted variant -> key and segment, as NRK) followed through the relay the way
a player follows it: every address resolved against the playlist it is in. Relative addresses in variant playlists
pointed one folder too deep and NRK's keys answered 404 (keyLoadError, Mark, 19 Oct 2026)."""
from __future__ import annotations

import re

from homeassistant.core import HomeAssistant

from conftest import resolve, setup_xtream


async def test_master_variant_key_and_segment(hass: HomeAssistant, provider, hass_ws_client, hass_client_no_auth) -> None:
    entry, c = await setup_xtream(hass)
    ws = await hass_ws_client(hass)
    await ws.send_json({"id": 1, "type": "iptv_player/stream", "entry_id": entry.entry_id, "key": "103"})
    s = (await ws.receive_json())["result"]
    client = await hass_client_no_auth()

    master = await (await client.get(s["url"])).text()
    variant_ref = [line for line in master.splitlines() if line and not line.startswith("#")][0]
    variant_url = resolve(s["url"], variant_ref)
    resp = await client.get(variant_url)
    assert resp.status == 200, variant_url
    variant = await resp.text()
    assert "keys.example" not in variant and "streams.example" not in variant

    key_url = resolve(variant_url, re.search(r'URI="([^"]+)"', variant).group(1))
    resp = await client.get(key_url)
    assert resp.status == 200, key_url
    assert await resp.read() == bytes(range(16))

    segment_url = resolve(variant_url, [line for line in variant.splitlines() if line and not line.startswith("#")][0])
    resp = await client.get(segment_url)
    assert resp.status == 200, segment_url
    assert await resp.read() == b"\x15" * 376
    assert all(u.startswith(("http://127.0.0.1", "/api/iptv_player/hls/")) or "/api/iptv_player/hls/" in u
               for u in (variant_url, key_url, segment_url))
