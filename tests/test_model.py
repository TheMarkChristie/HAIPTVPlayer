"""The catalogue, the selection, names and guide matching, and now/next. Run: python -m pytest tests -q"""
import _load  # noqa: F401
from custom_components.iptv_player import m3u, model as m

FREE = """#EXTM3U x-tvg-url="https://epgshare01.online/epgshare01/epg_ripper_UK1.xml.gz, https://x/ALL_SOURCES1.xml.gz"
#EXTINF:-1 tvg-name="BBC One" tvg-logo="https://up/bbc1.png" tvg-id="BBCOne.uk" tvg-chno="1" tvg-country="GB" group-title="UK",BBC One Ⓖ
https://vs-hls-pushb-uk-live.akamaized.net/x=4/i=urn:bbc:pips:service:bbc_one_yorks/iptv_hd_abr_v1.m3u8
#EXTINF:-1 tvg-id="NRK1.no" group-title="Norway",NRK1 Ⓖ
https://nrk-live-no.akamaized.net/nrk1/muxed.m3u8
#EXTINF:-1 tvg-id="Kanal10Norway.no" group-title="Norway",Kanal 10 Norge Ⓨ
https://www.youtube.com/c/Kanal10Norge/live
#EXTINF:-1 group-title="Denmark",TV 2/Fyn
https://cdn.jwplayer.com/live/broadcast/igp9r9oc.mpd
#EXTINF:-1 group-title="Ireland",Today FM
#EXTVLCOPT:http-user-agent=Radio/1.0
https://live-bauerie.sharp-stream.com/TDAAC
#EXTINF:-1 group-title="UK",BBC One Ⓖ
https://other/bbc1.m3u8
"""


def test_m3u_parse_and_header():
    entries = m3u.parse(FREE)
    assert [e.name for e in entries][:2] == ["BBC One Ⓖ", "NRK1 Ⓖ"]
    assert entries[0].tvg_id == "BBCOne.uk" and entries[0].group == "UK" and entries[0].chno == "1"
    assert entries[4].user_agent == "Radio/1.0"
    assert m3u.header_guides(FREE) == ["https://epgshare01.online/epgshare01/epg_ripper_UK1.xml.gz", "https://x/ALL_SOURCES1.xml.gz"]


def test_m3u_comma_inside_quotes():
    text = '#EXTM3U\n#EXTINF:-1 tvg-name="A, B" group-title="News, World",Name, with comma\nhttp://a/b.m3u8\n'
    e = m3u.parse(text)[0]
    assert e.group == "News, World" and e.name == "Name, with comma"


def test_catalog_from_m3u_skips_unplayable_and_dedupes_keys():
    cat = m.catalog_from_m3u(m3u.parse(FREE), m3u.header_guides(FREE))
    assert cat.skipped == 2                                   # YouTube and DASH
    assert [g.name for g in cat.groups] == ["UK", "Norway", "Ireland"]
    keys = [c.key for c in cat.channels]
    assert keys[0] == "uk/bbc-one" and keys[-1] == "uk/bbc-one~2"
    assert len(set(keys)) == len(keys)


def test_catalog_from_xtream():
    cats = [{"category_id": "7", "category_name": "UNITED KINGDOM"}, {"category_id": "8", "category_name": "UK-SPORTS"}]
    streams = [
        {"stream_id": 1000931, "name": "UK: BBC 2", "category_id": "7", "epg_channel_id": "BBCTwo.uk", "num": 12, "stream_icon": "http://logo/b2.png", "stream_type": "live"},
        {"stream_id": 5, "name": "UK: SKY SPORTS F1", "category_id": "8", "epg_channel_id": "", "stream_type": "live"},
        {"stream_id": 6, "name": "Orphan", "category_id": "99", "stream_type": "live"},
        {"stream_id": 7, "name": "A film", "category_id": "7", "stream_type": "movie"},
    ]
    cat = m.catalog_from_xtream(cats, streams)
    assert [c.key for c in cat.channels] == ["1000931", "5", "6"]
    assert cat.channels[0].guide_id == "BBCTwo.uk" and cat.channels[0].number == 12 and cat.channels[1].guide_id is None
    assert cat.groups[-1].id == "_other" and cat.channels[2].group == "_other"


def _cat():
    return m.Catalog(
        groups=[m.Group("uk", "UK", 0), m.Group("no", "Norway", 1)],
        channels=[m.Channel("a", "UK: BBC ONE", "uk", 0), m.Channel("b", "UK: BBC 2", "uk", 1),
                  m.Channel("c", "NRK1", "no", 2), m.Channel("d", "NRK2", "no", 3)],
    )


def test_selection_group_tick_untick_and_new_channels():
    cat = _cat()
    sel = m.apply_changes(m.empty_selection(), [{"group": "uk", "on": True}])
    assert [c.key for c in m.shown_channels(cat, sel)] == ["a", "b"]
    sel = m.apply_changes(sel, [{"channel": "b", "on": False}, {"channel": "c", "on": True}])
    assert [c.key for c in m.shown_channels(cat, sel)] == ["a", "c"]
    # the provider adds a channel to the ticked group: it shows by itself (Mark, 19 Oct 2026)
    cat.channels.append(m.Channel("e", "UK: BBC FOUR", "uk", 4))
    assert [c.key for c in m.shown_channels(cat, sel)] == ["a", "e", "c"]
    # follow the group again
    sel = m.apply_changes(sel, [{"channel": "b", "on": None}])
    assert "b" in [c.key for c in m.shown_channels(cat, sel)]
    sel = m.apply_changes(sel, [{"group": "uk", "on": False}])
    assert [c.key for c in m.shown_channels(cat, sel)] == ["c"]


def test_order_and_rename():
    cat = _cat()
    sel = m.apply_changes(m.empty_selection(), [{"group": "uk", "on": True}, {"group": "no", "on": True}],
                          group_order=["no", "uk"])
    assert [c.key for c in m.shown_channels(cat, sel)] == ["c", "d", "a", "b"]
    sel = m.apply_changes(sel, [{"order": ["d", "c"]}])
    sel = m.apply_changes(sel, [{"order": ["b", "a"]}])
    assert [c.key for c in m.shown_channels(cat, sel)] == ["d", "c", "b", "a"]      # the Norway order survived
    sel = m.apply_changes(sel, [{"channel": "a", "name": "BBC One Scotland"}])
    assert m.display_name(cat.channel("a"), sel) == "BBC One Scotland"
    sel = m.apply_changes(sel, [{"channel": "a", "name": ""}])
    assert m.display_name(cat.channel("a"), sel) == "UK: BBC ONE" and "a" not in sel["channels"]


def test_names():
    assert m.tidy_name("UK: BBC 2") == "BBC 2"
    assert m.tidy_name("US-S: BIG TEN NETWORK BTN") == "BIG TEN NETWORK BTN"
    assert m.tidy_name("NRK1 Ⓖ") == "NRK1"
    assert m.norm_name("UK: BBC TWO FHD") == m.norm_name("BBC Two HD") == m.norm_name("BBC 2") == "bbc2"
    assert m.norm_name("Sky Sports+ HD") == "skysportsplus"
    assert m.norm_name("Channel 4 +1") != m.norm_name("Channel 4")


def test_match_guides_order():
    cat = m.Catalog(groups=[m.Group("uk", "UK", 0)], channels=[
        m.Channel("a", "UK: BBC ONE SCOTLAND", "uk", 0, guide_id="BBCOneScotland.uk"),
        m.Channel("b", "UK: BBC 2", "uk", 1, guide_id="Wrong.uk"),
        m.Channel("c", "UK: STV", "uk", 2),
        m.Channel("d", "UK: Nothing", "uk", 3),
    ])
    provider = m.GuideSource("Provider guide", {"BBCOneScotland.uk": ["BBC One Scotland"], "STVx.uk": ["STV"]})
    free = m.GuideSource("epgshare01 UK1", {"BBC.Two.HD.uk": ["BBC Two HD"], "STV.HD.uk": ["STV HD"]})
    sel = m.empty_selection()
    got = m.match_guides(cat.channels, sel, [provider, free])
    assert got["a"] == (0, "BBCOneScotland.uk", "id")
    assert got["b"] == (1, "BBC.Two.HD.uk", "name")            # its own id is in neither guide; the free one has the name
    assert got["c"] == (0, "STVx.uk", "name")                  # the provider's guide first
    assert "d" not in got
    sel = m.apply_changes(sel, [{"channel": "c", "guide": "epgshare01 UK1|STV.HD.uk"}])
    assert m.match_guides(cat.channels, sel, [provider, free])["c"] == (1, "STV.HD.uk", "manual")
    found = m.search_guide_channels([provider, free], "bbc two")
    assert found and found[0]["id"] == "BBC.Two.HD.uk" and found[0]["source"] == "epgshare01 UK1"


def test_now_next_and_window():
    progs = [(100, 200, "A", "", "", ""), (200, 300, "B", "", "", ""), (300, 400, "C", "", "", "")]
    cur, nxt = m.now_next(progs, 250)
    assert cur[2] == "B" and nxt[2] == "C"
    cur, nxt = m.now_next(progs, 50)
    assert cur is None and nxt[2] == "A"
    assert [p[2] for p in m.window(progs, 150, 310)] == ["A", "B", "C"]
    assert m.programme_dict(progs[0])["sub"] is None


def test_playable_url():
    assert m.playable_url("https://a/b.m3u8")
    assert not m.playable_url("https://www.youtube.com/c/x/live")
    assert not m.playable_url("https://cdn/x.mpd?token=1")
    assert not m.playable_url("rtmp://a/b")
