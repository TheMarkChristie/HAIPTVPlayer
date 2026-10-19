"""Render the IPTV Player card in headless Chrome or Edge from sample data: the channel grid wide and on a phone, the
guide, Manage channels, the TV layout with a focused tile (moved there with the arrow keys), and compact. Saves PNGs
under tests/out (gitignored).

The page inlines the card's script (file:// pages cannot fetch), stubs the slice of `hass` the card uses and defines a
stand-in `home-assistant` element so the card registers at once. Logos are SVG data URLs. Nothing plays: the shots
judge the layout.

    python tests/render_card.py
"""
from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CARD = os.path.join(ROOT, "custom_components", "iptv_player", "www", "iptv-player-card.js")
OUT = os.path.join(HERE, "out")
BROWSERS = [r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"]
COLOURS = ["#bb1919", "#0a4a8f", "#00704a", "#5b2a86", "#d4561b", "#111", "#0f7b8a", "#7a1f4e"]
ENTRY = "01KPROVIDER"
RENAMED = {"UNITED KINGDOM": "UK", "UK-SPORTS": "Sport"}
FREE = "01KFREE"

UK = [("BBC ONE SCOTLAND", "Reporting Scotland", "The One Show"), ("BBC 2", "Eggheads", "Antiques Road Trip"),
      ("BBC ALBA", "Speaking Our Language", "Eòrpa"), ("STV", "STV News at Six", "Emmerdale"),
      ("CHANNEL 4", "Four in a Bed", "The Simpsons"), ("CHANNEL 5", "Police Interceptors", "Traffic Cops"),
      ("BBC NEWS", "BBC News at Six", "The Context"), ("DAVE", "Taskmaster", "QI XL"),
      ("SKY SPORTS F1", "F1 Show", "Ted's Notebook"), ("TNT SPORTS 1", "Premiership Rugby", "Rugby Tonight"),
      ("SKY SPORTS MAIN EVENT", "Monday Night Football", "Gillette Soccer Saturday"), ("EUROSPORT 1", "Cycling", "Snooker")]
NORDIC = [("NRK1", "Dagsrevyen", "Norge Rundt"), ("NRK2", "Urix", "Dokumentar"), ("TV 2 Fyn", "Nyheder", "Vejret"),
          ("RTÉ News", "News at One", "Six One")]


def logo(name: str, i: int) -> str:
    text = "".join(w[0] for w in name.split()[:3])
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="120" height="80"><rect width="120" height="80" rx="8" fill="{COLOURS[i % len(COLOURS)]}"/>'
           f'<text x="60" y="52" font-family="Segoe UI, Arial" font-size="30" font-weight="700" fill="#fff" text-anchor="middle">{text}</text></svg>')
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()


def sample() -> dict:
    now = int(time.time())
    base = now - (now % 1800)
    channels, groups, guide = [], [], {}

    def add(entry: str, gid: str, gname: str, rows: list, start: int) -> None:
        groups.append({"id": f"{entry}:{gid}", "entry_id": entry, "name": RENAMED.get(gname, gname), "original": gname})
        for n, (name, cur, nxt) in enumerate(rows):
            key = str(start + n)
            s = base - 600 - (n % 4) * 300
            progs = []
            t = s - 3600
            titles = [f"{cur} (earlier)", cur, nxt, "Late programme", "Film: The Long Night", "Nightly news", "Closedown"]
            for k, title in enumerate(titles):
                length = 3600 if k % 3 else 1800
                progs.append({"start": t, "stop": t + length, "title": title, "sub": None, "desc": f"About {title}.", "category": "News" if k == 1 else None})
                t += length
            cur_p = next(p for p in progs if p["start"] <= now < p["stop"])
            nxt_p = progs[progs.index(cur_p) + 1]
            channels.append({"uid": f"{entry}:{key}", "entry_id": entry, "key": key, "group": f"{entry}:{gid}", "name": name,
                             "number": start + n - 100, "logo": logo(name, n + start), "now": cur_p, "next": nxt_p})
            guide.setdefault(entry, {})[key] = progs

    add(ENTRY, "7", "UNITED KINGDOM", UK[:8], 101)
    add(ENTRY, "8", "UK-SPORTS", UK[8:], 201)
    add(FREE, "Norway", "Norway", NORDIC[:2], 301)
    add(FREE, "Denmark", "Denmark", NORDIC[2:3], 311)
    add(FREE, "Ireland", "Ireland", NORDIC[3:], 321)
    data = {
        "entries": [{"entry_id": ENTRY, "title": "My provider", "kind": "xtream", "shown": 12, "account": {"status": "Active", "exp_date": "1795046400", "active_cons": "0", "max_connections": "2"}},
                    {"entry_id": FREE, "title": "Free-TV", "kind": "m3u", "shown": 4, "account": None}],
        "groups": groups, "channels": channels, "now": now, "is_admin": True, "loading": False,
        "players": [{"entity_id": "media_player.77_oled", "name": '77" OLED', "available": True},
                    {"entity_id": "media_player.living_room_tv", "name": "Living Room TV", "available": True},
                    {"entity_id": "media_player.bedroom_big_tv", "name": "Bedroom big tv", "available": False}],
    }
    catalog = {
        "entry_id": ENTRY, "title": "My provider", "kind": "xtream", "channels_total": 6581, "skipped": 0, "catalog_at": now - 3600,
        "groups": [{"id": "7", "name": "UNITED KINGDOM", "on": True, "total": 112, "shown": 8},
                   {"id": "8", "name": "UK-SPORTS", "on": True, "total": 95, "shown": 4},
                   {"id": "1", "name": "US-ENTERTAINMENT", "on": False, "total": 236, "shown": 0},
                   {"id": "30", "name": "EPL", "on": False, "total": 41, "shown": 0},
                   {"id": "31", "name": "EFL/SPFL", "on": False, "total": 58, "shown": 0}],
        "guide": {"sources": [{"label": "Provider guide", "url": None, "channels": 4421, "error": None},
                              {"label": "epgshare01 UK1", "url": "https://epgshare01.online/epgshare01/epg_ripper_UK1.xml.gz", "channels": 486, "error": None}],
                  "built_at": now - 600, "matched": 11, "shown": 12},
        "account": {"status": "Active", "exp_date": "1795046400", "active_cons": "0", "max_connections": "2"}, "streams": [],
    }
    group7 = [{"key": c["key"], "name": f"UK: {c['name']}", "display": "BBC One Scotland" if c["key"] == "101" else "", "tidy": c["name"],
               "group": "7", "on": c["key"] != "105", "own": False if c["key"] == "105" else None, "number": c["number"], "logo": c["logo"],
               "guide_id": None, "guide": {"source": "Provider guide", "id": c["name"].title().replace(" ", "") + ".uk", "how": "id" if int(c["key"]) % 3 else "name"},
               "guide_manual": None} for c in channels[:8]]
    return {"data": data, "guide": guide, "catalog": catalog, "group7": group7}


def page(sample_data: dict, config: dict, width: int, dark: bool, steps: str) -> str:
    script = open(CARD, encoding="utf-8").read()
    theme = ("--primary-text-color:#e1e1e1;--secondary-text-color:#9b9b9b;--card-background-color:#1c1c1c;--ha-card-background:#1c1c1c;--secondary-background-color:#2b2b2b;--primary-background-color:#111;--primary-color:#03a9f4;--text-primary-color:#fff;--divider-color:#333;--error-color:#ef5350;"
             if dark else
             "--primary-text-color:#212121;--secondary-text-color:#727272;--card-background-color:#fff;--ha-card-background:#fff;--secondary-background-color:#f0f0f0;--primary-background-color:#fafafa;--primary-color:#03a9f4;--text-primary-color:#fff;--divider-color:#e0e0e0;--error-color:#db4437;")
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>IPTV Player card</title>
<style>html{{{theme}}} body{{margin:0;padding:12px;background:var(--primary-background-color);font-family:Roboto,'Segoe UI',Arial,sans-serif;width:{width}px;box-sizing:border-box}} ha-card{{display:block;background:var(--ha-card-background);border-radius:12px;box-shadow:0 2px 6px rgba(0,0,0,0.2)}} #err{{position:fixed;top:0;left:0;z-index:99;color:#ff0;background:rgba(0,0,0,0.85);font:12px monospace;white-space:pre-wrap}}</style></head>
<body><div id="err"></div><iptv-player-card id="card"></iptv-player-card>
<script>
window.onerror=(m,s,l,c)=>{{document.getElementById('err').textContent+=m+' @'+l+':'+c+'\\n';}};
customElements.define('home-assistant', class extends HTMLElement{{}});
const S={json.dumps(sample_data)};
const hass={{language:'en',locale:{{language:'en-GB'}},config:{{time_zone:'Europe/London'}},
  callWS:async(msg)=>{{
    if(msg.type==='iptv_player/channels') return S.data;
    if(msg.type==='iptv_player/guide') {{ const g=S.guide[msg.entry_id]||{{}}; const out={{}}; msg.keys.forEach(k=>out[k]=g[k]||[]); return {{programmes:out}}; }}
    if(msg.type==='iptv_player/catalog') return msg.group ? {{channels:S.group7}} : S.catalog;
    throw new Error('unknown '+msg.type); }},
  callService:async()=>({{}}),
  connection:{{subscribeMessage:async()=>()=>{{}}}} }};
</script>
<script>{script}</script>
<script>
const card=document.getElementById('card'); card.setConfig({json.dumps(config)}); card.hass=hass; document.body.appendChild(card);
const R=()=>card.shadowRoot;
setTimeout(async()=>{{ {steps} }}, 300);
</script></body></html>"""


def shoot(html: str, out: str, width: int, height: int) -> None:
    browser = next((b for b in BROWSERS if os.path.exists(b)), None)
    if not browser:
        raise SystemExit("no Chrome or Edge found")
    tmp = tempfile.mkdtemp(prefix="iptvplayer-")
    try:
        path = os.path.join(tmp, "card.html")
        open(path, "w", encoding="utf-8").write(html)
        url = "file:///" + path.replace("\\", "/")
        subprocess.run([browser, "--headless=new", "--disable-gpu", "--hide-scrollbars", f"--user-data-dir={os.path.join(tmp, 'p')}",
                        "--virtual-time-budget=4000", f"--window-size={width + 24},{height}", f"--screenshot={out}", url],
                       capture_output=True, timeout=120)
        if not os.path.exists(out):
            raise SystemExit(f"no screenshot produced for {out}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


PLAYING = f"card._current='{ENTRY}:101'; card._veil(null); card._render();"


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    s = sample()
    shots = [
        ("card_wide.png", {}, 1180, True, PLAYING, 1250),
        ("card_phone.png", {}, 488, False, PLAYING, 1500),
        ("card_guide.png", {}, 1180, True, PLAYING + " R().querySelector('[data-act=guide]').click();", 1100),
        ("card_manage.png", {}, 1180, False, "R().querySelector('[data-act=manage]').click(); setTimeout(()=>{ R().querySelector('[data-gopen=\"7\"]').click(); }, 300);", 1500),
        ("card_cast_menu.png", {}, 1180, True, PLAYING + " R().querySelector('[data-act=cast]').click();", 700),
        ("card_tv.png", {"layout": "tv"}, 1280, True,
         "card._veil('idle'); const t=R().querySelector('.tile'); t.focus(); for (const k of ['ArrowRight','ArrowRight','ArrowDown']) R().activeElement.dispatchEvent(new KeyboardEvent('keydown',{key:k,bubbles:true,composed:true}));", 1300),
        ("card_compact.png", {"compact": True}, 520, False, PLAYING, 560),
    ]
    for name, config, width, dark, steps, height in shots:
        shoot(page(s, config, width, dark, steps), os.path.join(OUT, name), width, height)
    print("written:", ", ".join(os.path.join(OUT, n[0]) for n in shots))


if __name__ == "__main__":
    main()
