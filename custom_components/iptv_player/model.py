"""The channel catalogue, Mark's selection and the guide matching. Pure Python (no Home Assistant), so it is tested
on its own.

A catalogue is the provider's groups and live channels. The selection is what Mark ticked, kept by Home Assistant
(not by a browser) so every screen shows the same channels:

    {"groups":   {group_id: true | false},                     ticked groups
     "channels": {channel_key: {"on": bool, "name": str, "guide": str}},   per-channel choices, each optional
     "group_order": [group_id, ...], "channel_order": [channel_key, ...]}

A channel shows when its own "on" says so, else when its group is ticked: a channel the provider adds to a ticked
group shows by itself (Mark, 19 Oct 2026), and one he unticked stays hidden."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable

from .m3u import M3UEntry

UNPLAYABLE_HOSTS = ("youtube.com", "youtu.be", "twitch.tv", "dailymotion.com", "facebook.com")


@dataclass(frozen=True)
class Group:
    id: str
    name: str
    order: int


@dataclass(frozen=True)
class Channel:
    key: str                         # stable inside its entry: the Xtream stream id, or the playlist's group + name
    name: str
    group: str                       # Group.id
    order: int                       # the provider's order
    logo: str | None = None
    guide_id: str | None = None      # tvg-id / epg_channel_id
    number: int | None = None
    url: str | None = None           # M3U: the stream address; Xtream: None (built from the stream id when played)
    stream_id: str | None = None     # Xtream only
    user_agent: str | None = None    # from the playlist's #EXTVLCOPT
    referrer: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Catalog:
    groups: list[Group] = field(default_factory=list)
    channels: list[Channel] = field(default_factory=list)
    skipped: int = 0                 # entries that cannot play in a browser (YouTube, Twitch, DASH)
    guide_urls: list[str] = field(default_factory=list)    # guides the playlist names in its header

    def group(self, gid: str) -> Group | None:
        return next((g for g in self.groups if g.id == gid), None)

    def channel(self, key: str) -> Channel | None:
        return self.by_key().get(key)

    def by_key(self) -> dict[str, Channel]:
        return {c.key: c for c in self.channels}


# ---- building a catalogue -------------------------------------------------------------------------------------------

def _int(value: Any) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def catalog_from_xtream(categories: list[dict[str, Any]], streams: list[dict[str, Any]]) -> Catalog:
    """player_api.php's get_live_categories + get_live_streams."""
    groups = [Group(str(c.get("category_id")), str(c.get("category_name") or "").strip() or str(c.get("category_id")), i)
              for i, c in enumerate(categories or [])]
    known = {g.id for g in groups}
    channels: list[Channel] = []
    for i, s in enumerate(streams or []):
        if str(s.get("stream_type") or "live") not in ("live", "created_live", "radio_streams"):
            continue
        sid = str(s.get("stream_id") or "").strip()
        if not sid:
            continue
        gid = str(s.get("category_id") or "")
        if gid not in known:
            gid = "_other"
        channels.append(Channel(
            key=sid, name=str(s.get("name") or sid).strip(), group=gid, order=i,
            logo=str(s.get("stream_icon") or "").strip() or None,
            guide_id=str(s.get("epg_channel_id") or "").strip() or None,
            number=_int(s.get("num")), stream_id=sid,
        ))
    if any(c.group == "_other" for c in channels):
        groups.append(Group("_other", "Other", len(groups)))
    return Catalog(groups=groups, channels=channels)


def playable_url(url: str) -> bool:
    low = url.lower()
    if not low.startswith(("http://", "https://")):
        return False
    host = low.split("/")[2] if low.count("/") >= 2 else ""
    if any(host == h or host.endswith("." + h) for h in UNPLAYABLE_HOSTS):
        return False
    path = low.split("?")[0]
    return not path.endswith(".mpd")      # DASH needs another player library; not in this version


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()).strip("-")


def catalog_from_m3u(entries: Iterable[M3UEntry], header_guides: list[str] | None = None) -> Catalog:
    groups: dict[str, Group] = {}
    channels: list[Channel] = []
    used: dict[str, int] = {}
    skipped = 0
    for i, e in enumerate(entries):
        if not playable_url(e.url):
            skipped += 1
            continue
        gname = e.group or "Other"
        if gname not in groups:
            groups[gname] = Group(gname, gname, len(groups))
        base = f"{_slug(gname)}/{_slug(tidy_name(e.name)) or i}"
        used[base] = used.get(base, 0) + 1
        key = base if used[base] == 1 else f"{base}~{used[base]}"
        channels.append(Channel(
            key=key, name=e.name, group=gname, order=i, logo=e.logo, guide_id=e.tvg_id, number=_int(e.chno),
            url=e.url, user_agent=e.user_agent, referrer=e.referrer,
        ))
    return Catalog(groups=list(groups.values()), channels=channels, skipped=skipped, guide_urls=list(header_guides or []))


# ---- the selection ----------------------------------------------------------------------------------------------------

def empty_selection() -> dict[str, Any]:
    return {"groups": {}, "channels": {}, "group_order": [], "channel_order": []}


def normal_selection(data: Any) -> dict[str, Any]:
    sel = empty_selection()
    if isinstance(data, dict):
        sel["groups"] = {str(k): bool(v) for k, v in (data.get("groups") or {}).items()}
        sel["channels"] = {str(k): dict(v) for k, v in (data.get("channels") or {}).items() if isinstance(v, dict)}
        sel["group_order"] = [str(x) for x in data.get("group_order") or []]
        sel["channel_order"] = [str(x) for x in data.get("channel_order") or []]
    return sel


def is_shown(channel: Channel, sel: dict[str, Any]) -> bool:
    own = sel["channels"].get(channel.key, {})
    if "on" in own:
        return bool(own["on"])
    return bool(sel["groups"].get(channel.group, False))


def display_name(channel: Channel, sel: dict[str, Any]) -> str:
    return str(sel["channels"].get(channel.key, {}).get("name") or "").strip() or channel.name


def _ordered(items: list[Any], key, explicit: list[str]) -> list[Any]:
    """Items in their explicit order first (as listed), then the rest in their own order."""
    pos = {k: i for i, k in enumerate(explicit)}
    return sorted(items, key=lambda x: (0, pos[key(x)]) if key(x) in pos else (1, x.order))


def ordered_groups(catalog: Catalog, sel: dict[str, Any]) -> list[Group]:
    return _ordered(list(catalog.groups), lambda g: g.id, sel["group_order"])


def shown_channels(catalog: Catalog, sel: dict[str, Any]) -> list[Channel]:
    """The channels to show, group by group in Mark's order, each group's channels in his order."""
    by_group: dict[str, list[Channel]] = {}
    for c in catalog.channels:
        if is_shown(c, sel):
            by_group.setdefault(c.group, []).append(c)
    out: list[Channel] = []
    for g in ordered_groups(catalog, sel):
        out += _ordered(by_group.get(g.id, []), lambda c: c.key, sel["channel_order"])
    return out


def apply_changes(sel: dict[str, Any], changes: list[dict[str, Any]], group_order: list[str] | None = None,
                  channel_order: list[str] | None = None) -> dict[str, Any]:
    """A new selection with the Manage screen's changes:
        {"group": id, "on": bool}                       tick or untick a group
        {"channel": key, "on": bool | None}             show, hide, or follow the group again (None)
        {"channel": key, "name": str | None}            rename ("" or None: the provider's name)
        {"channel": key, "guide": str | None}           the guide channel ("<source>|<id>"; "" or None: automatic)
        {"order": [key, ...]}                           one group's channels in this order"""
    out = normal_selection(sel)
    for ch in changes:
        if "order" in ch:
            # one group's channels in a new order: they move to the end of the list in that order, which leaves every
            # other group's order as it was (order only counts between channels of the same group)
            keys = [str(k) for k in ch["order"] or []]
            out["channel_order"] = [k for k in out["channel_order"] if k not in set(keys)] + keys
            continue
        if "group" in ch:
            gid = str(ch["group"])
            if ch.get("on"):
                out["groups"][gid] = True
            else:
                out["groups"].pop(gid, None)
            continue
        if "channel" not in ch:
            continue
        key = str(ch["channel"])
        own = dict(out["channels"].get(key, {}))
        if "on" in ch:
            if ch["on"] is None:
                own.pop("on", None)
            else:
                own["on"] = bool(ch["on"])
        for field_name in ("name", "guide"):
            if field_name in ch:
                value = str(ch[field_name] or "").strip()
                if value:
                    own[field_name] = value
                else:
                    own.pop(field_name, None)
        if own:
            out["channels"][key] = own
        else:
            out["channels"].pop(key, None)
    if group_order is not None:
        out["group_order"] = [str(x) for x in group_order]
    if channel_order is not None:
        out["channel_order"] = [str(x) for x in channel_order]
    return out


# ---- names and guide matching -----------------------------------------------------------------------------------------

_PREFIX = re.compile(r"^\s*(?:[a-z]{2,3}(?:[-/][a-z0-9]{1,4})?|[a-z]{2,4}\s?\+?)\s*[:|]\s*", re.I)
_NOISE = re.compile(r"\b(?:fhd|uhd|hd|sd|4k|hevc|h265|1080p?|720p?|backup|raw|vip|live)\b", re.I)
_NUMBERS = {"one": "1", "two": "2", "three": "3", "four": "4", "five": "5"}


def tidy_name(name: str) -> str:
    """The name without a provider prefix ("UK: BBC 2" -> "BBC 2") or Free-TV's markers (Ⓖ geo-blocked, Ⓢ not
    24/7, Ⓨ YouTube, Ⓣ Twitch)."""
    text = re.sub(r"[Ⓐ-ⓩ]", "", name).strip()
    stripped = _PREFIX.sub("", text, count=1).strip()
    return stripped or text


def norm_name(name: str) -> str:
    """A matching key: no prefix, no quality words, numbers as digits, letters and digits only.
    "UK: BBC TWO FHD", "BBC Two HD" and "BBC 2" all give "bbc2"."""
    text = unicodedata.normalize("NFKD", tidy_name(name)).encode("ascii", "ignore").decode().lower()
    text = text.replace("&", " and ").replace("+", " plus ")
    text = _NOISE.sub(" ", text)
    words = [_NUMBERS.get(w, w) for w in re.split(r"[^a-z0-9]+", text) if w]
    return "".join(words)


@dataclass
class GuideSource:
    """One XMLTV source's channels: id -> display names, in source priority order (the provider's guide first)."""
    label: str
    names: dict[str, list[str]]

    def ids(self) -> set[str]:
        return set(self.names)

    def by_norm(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for gid, names in self.names.items():
            for n in names or [gid]:
                out.setdefault(norm_name(n), gid)
        return out


def match_guides(channels: Iterable[Channel], sel: dict[str, Any], sources: list[GuideSource]
                 ) -> dict[str, tuple[int, str, str]]:
    """channel key -> (source index, guide channel id, how): how is "manual" (Mark picked it), "id" (the playlist's
    guide id is in a guide) or "name" (a guide channel has the same name). Manual and id matches are looked for in
    every source before any name match, so a name in the provider's guide never beats an exact id in another."""
    id_sets = [s.ids() for s in sources]
    norms = [s.by_norm() for s in sources]
    out: dict[str, tuple[int, str, str]] = {}
    for c in channels:
        manual = str(sel["channels"].get(c.key, {}).get("guide") or "").strip()
        found = None
        if manual:
            src, _, gid = manual.partition("|") if "|" in manual else ("", "", manual)
            for i, ids in enumerate(id_sets):
                if gid in ids and (not src or sources[i].label == src):
                    found = (i, gid, "manual")
                    break
        if found is None and c.guide_id:
            found = next(((i, c.guide_id, "id") for i, ids in enumerate(id_sets) if c.guide_id in ids), None)
        if found is None:
            keys = {norm_name(display_name(c, sel)), norm_name(c.name)} - {""}
            for i, by_norm in enumerate(norms):
                gid = next((by_norm[k] for k in keys if k in by_norm), None)
                if gid:
                    found = (i, gid, "name")
                    break
        if found:
            out[c.key] = found
    return out


def search_guide_channels(sources: list[GuideSource], query: str, limit: int = 25) -> list[dict[str, Any]]:
    """Guide channels whose id or a display name contains every word of the query (for the Manage screen)."""
    words = [w for w in re.split(r"\s+", query.lower().strip()) if w]
    out: list[dict[str, Any]] = []
    for i, src in enumerate(sources):
        for gid, names in src.names.items():
            hay = " ".join([gid, *names]).lower()
            if all(w in hay for w in words):
                out.append({"source": src.label, "source_index": i, "id": gid, "name": (names or [gid])[0]})
                if len(out) >= limit:
                    return out
    return out


# ---- the guide at a moment --------------------------------------------------------------------------------------------

Programme = tuple[int, int, str, str, str, str]      # start, stop, title, sub-title, description, category


def now_next(programmes: list[Programme] | None, now: int) -> tuple[Programme | None, Programme | None]:
    if not programmes:
        return None, None
    current = nxt = None
    for p in programmes:
        if p[0] <= now < p[1]:
            current = p
        elif p[0] >= now:
            nxt = p
            break
    return current, nxt


def programme_dict(p: Programme | None) -> dict[str, Any] | None:
    if p is None:
        return None
    return {"start": p[0], "stop": p[1], "title": p[2], "sub": p[3] or None, "desc": p[4] or None, "category": p[5] or None}


def window(programmes: list[Programme] | None, start: int, end: int) -> list[Programme]:
    return [p for p in programmes or [] if p[1] > start and p[0] < end]
