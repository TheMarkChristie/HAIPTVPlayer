"""The XMLTV reader and the HLS rewrite. Run: python -m pytest tests -q"""
import gzip

import _load  # noqa: F401
from custom_components.iptv_player import hls, xmltv

XML = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE tv SYSTEM "xmltv.dtd">
<tv generator-info-name="test">
  <channel id="BBCOneScotland.uk"><display-name>BBC One Scotland</display-name><display-name lang="gd">BBC Aon</display-name></channel>
  <channel id="STV.uk"><display-name>STV &amp; more</display-name><icon src="x"/></channel>
  <channel id="Empty.uk"/>
  <programme start="20261019180000 +0100" stop="20261019183000 +0100" channel="BBCOneScotland.uk"><title lang="en">Reporting Scotland</title><desc>News &amp; weather.</desc><category>News</category></programme>
  <programme channel="BBCOneScotland.uk" stop="20261019190000 +0100" start="20261019183000 +0100"><title>The One Show</title><sub-title>Monday</sub-title></programme>
  <programme start="20261019170000 +0000" stop="20261019180000 +0000" channel="STV.uk"><title>STV News</title></programme>
  <programme start="20261020170000 +0000" stop="20261020180000 +0000" channel="STV.uk"><title>Too late</title></programme>
  <programme start="20261019170000 +0000" stop="20261019180000 +0000" channel="Other.uk"><title>Not wanted</title></programme>
  <programme start="20261019180000 +0000" channel="STV.uk"><title>No stop</title></programme>
</tv>
"""


def _write(tmp_path, gz: bool) -> str:
    path = tmp_path / ("g.xml.gz" if gz else "g.xml")
    path.write_bytes(gzip.compress(XML.encode()) if gz else XML.encode())
    return str(path)


def test_time():
    assert xmltv.parse_time("20261019180000 +0100") == xmltv.parse_time("20261019170000 +0000")
    assert xmltv.parse_time("20261019170000") == xmltv.parse_time("20261019170000 +0000")
    assert xmltv.parse_time("rubbish") is None


def test_channels_stop_at_first_programme(tmp_path):
    for gz in (False, True):
        chans = xmltv.read_channels(_write(tmp_path, gz))
        assert chans == {"BBCOneScotland.uk": ["BBC One Scotland", "BBC Aon"], "STV.uk": ["STV & more"], "Empty.uk": []}


def test_programmes_window_and_attribute_order(tmp_path, monkeypatch):
    monkeypatch.setattr(xmltv, "CHUNK", 97)       # elements split across reads
    path = _write(tmp_path, True)
    start = xmltv.parse_time("20261019160000 +0000")
    end = xmltv.parse_time("20261019200000 +0000")
    got = xmltv.read_programmes(path, {"BBCOneScotland.uk", "STV.uk"}, start, end, desc_chars=5)
    assert [p[2] for p in got["BBCOneScotland.uk"]] == ["Reporting Scotland", "The One Show"]
    first = got["BBCOneScotland.uk"][0]
    assert first[1] - first[0] == 1800 and first[5] == "News" and first[4] == "News…"
    assert got["BBCOneScotland.uk"][1][3] == "Monday"
    assert [p[2] for p in got["STV.uk"]] == ["STV News", "No stop"]
    assert got["STV.uk"][1][1] - got["STV.uk"][1][0] == 1800        # no stop: half an hour
    assert "Other.uk" not in got


XTREAM = """#EXTM3U
#EXT-X-VERSION:3
#EXT-X-MEDIA-SEQUENCE:0
#EXT-X-TARGETDURATION:10
#EXTINF:10.000000,
/hls/abc123/1000931_0.ts
#EXTINF:10.000000,
/hls/abc123/1000931_1.ts
"""

MASTER = """#EXTM3U
#EXT-X-INDEPENDENT-SEGMENTS
#EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID="sub1",LANGUAGE="no",NAME="Norsk",URI="sc-ga/s0_index.m3u8"
#EXT-X-STREAM-INF:BANDWIDTH=898800,CODECS="avc1.42e01e,mp4a.40.2",SUBTITLES="sub1"
sc-ga/m001_index.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=4390600
https://cdn2.example/nrk1/m4.m3u8?token=x
"""

MEDIA = """#EXTM3U
#EXT-X-KEY:METHOD=AES-128,URI="https://drm.example/content.key",IV=0xc61b
#EXT-X-MAP:URI="init.mp4"
#EXTINF:3.2,
m001_F1.ts
#EXT-X-KEY:METHOD=NONE
#EXTINF:3.2,
data:video/mp2t;base64,AAAA
"""


class _Reg:
    def __init__(self):
        self.seen = []

    def __call__(self, url, is_list):
        self.seen.append((url, is_list))
        return f"{'p' if is_list else 's'}/{len(self.seen)}"


def test_rewrite_media_playlist_with_absolute_paths():
    reg = _Reg()
    out = hls.rewrite(XTREAM, "http://lb.example:80/auth/tok", reg)
    assert reg.seen == [("http://lb.example:80/hls/abc123/1000931_0.ts", False), ("http://lb.example:80/hls/abc123/1000931_1.ts", False)]
    assert "lb.example" not in out and out.splitlines()[-1] == "s/2"


def test_rewrite_master_with_renditions():
    reg = _Reg()
    out = hls.rewrite(MASTER, "https://nrk-live-no.akamaized.net/nrk1/muxed.m3u8", reg)
    assert reg.seen == [("https://nrk-live-no.akamaized.net/nrk1/sc-ga/s0_index.m3u8", True),
                        ("https://nrk-live-no.akamaized.net/nrk1/sc-ga/m001_index.m3u8", True),
                        ("https://cdn2.example/nrk1/m4.m3u8?token=x", True)]
    assert 'URI="p/1"' in out and "akamaized" not in out


def test_rewrite_keys_maps_and_data():
    reg = _Reg()
    out = hls.rewrite(MEDIA, "https://a.example/nrk1/sc/m001_index.m3u8", reg)
    assert reg.seen[0] == ("https://drm.example/content.key", False)
    assert reg.seen[1] == ("https://a.example/nrk1/sc/init.mp4", False)
    assert 'URI="s/1",IV=0xc61b' in out and 'URI="s/2"' in out and "METHOD=NONE" in out
    assert out.splitlines()[-1] == "data:video/mp2t;base64,AAAA" and len(reg.seen) == 3      # inline data stays as it is


def test_is_playlist_and_extension():
    assert hls.is_playlist(b"\xef\xbb\xbf#EXTM3U\n")
    assert not hls.is_playlist(b"G@\x11")
    assert hls.extension("http://a/b/c.TS?x=1") == ".ts"
    assert hls.extension("http://a/hls/abc") == ".bin"


NRK_LONG = ("#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-TARGETDURATION:4\n#EXT-X-MEDIA-SEQUENCE:1000\n"
            "#EXT-X-PROGRAM-DATE-TIME:2026-10-19T04:38:00.759Z\n#EXT-X-KEY:METHOD=AES-128,URI=\"https://k/1.key\"\n"
            + "".join(f"#EXTINF:3.2,\nm_{i}.ts\n" + ("#EXT-X-DISCONTINUITY\n" if i == 5 else "") for i in range(100)))


def test_trim_live_keeps_the_live_edge():
    out = hls.trim_live(NRK_LONG, keep=30)
    lines = out.splitlines()
    assert lines[0] == "#EXTM3U" and "#EXT-X-MEDIA-SEQUENCE:1070" in lines
    assert "#EXT-X-DISCONTINUITY-SEQUENCE:1" in lines
    uris = [line for line in lines if not line.startswith("#")]
    assert uris[0] == "m_70.ts" and uris[-1] == "m_99.ts" and len(uris) == 30
    first = lines.index("m_70.ts")
    assert any(line.startswith("#EXT-X-KEY:METHOD=AES-128") for line in lines[:first])    # the key in force carried over


def test_trim_live_leaves_short_vod_and_master():
    assert hls.trim_live(XTREAM) == XTREAM
    assert hls.trim_live(MASTER) == MASTER
    vod = NRK_LONG + "#EXT-X-ENDLIST\n"
    assert hls.trim_live(vod, keep=30) == vod


def test_open_text_refuses_non_xml(tmp_path):
    p = tmp_path / "g.xml"
    p.write_bytes(b"(\xb5/\xfd\x00\x58zstd-ish")
    try:
        xmltv.read_channels(str(p))
    except ValueError:
        pass
    else:
        raise AssertionError("read a non-XML file as a guide")
