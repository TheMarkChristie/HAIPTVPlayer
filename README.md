# IPTV Player for Home Assistant

Live TV in Home Assistant from your own IPTV subscription or a free playlist: sign in with your provider's username and
password (Xtream Codes) or add an M3U link, tick the groups and channels you want, and watch them on a dashboard with
now and next, a TV guide, and Play on TV for your Google Cast devices.

It replaces the abandoned [lovelace-simple-iptv-player](https://github.com/manudj195/lovelace-simple-iptv-player) card
with an integration: the channel choice is kept by Home Assistant (every screen shows the same channels), streams are
relayed through Home Assistant (so an http provider plays on an https dashboard and the password never reaches a
browser or a TV), and there is a guide.

It ships no channels or playlists: it plays what you sign in to.

## Install

1. HACS > three dots > Custom repositories > add `https://github.com/TheMarkChristie/HAIPTVPlayer` as an Integration.
2. Install **IPTV Player**, restart Home Assistant.
3. Settings > Devices & services > Add integration > **IPTV Player**, then either:
   - **Provider login**: the server address, username and password your provider sent, or
   - **M3U playlist address**: any M3U / M3U8 link.

   Add both if you have both; each is its own source.
4. Add the card to a dashboard (`custom:iptv-player-card`) and open **Manage channels** on it to tick what shows.

## Choosing channels

**Manage channels** (admins only) lists every group with a tick box and how many of its channels show. Tick a group to
show its channels; channels the provider adds to a ticked group later show by themselves. Open a group to untick
single channels, rename them, move them up and down, preview them, or pick their guide channel by hand.

## The guide

Each source reads its guides once a day (04:00 by default) into Home Assistant's cache folder, which backups skip:

- a provider login uses the provider's own guide (`xmltv.php`), with epgshare01's free UK file filling the gaps;
- a playlist uses the guides its header names when there are five or fewer (Free-TV's list names a hundred, so set
  the ones you want in the options);
- any other XMLTV address can be added in the options, one per line. Files over 60 MB are refused.

Channels are matched to the guide by guide id first, then by name ("UK: BBC TWO FHD" finds "BBC Two HD"); anything
else can be chosen in Manage channels.

## The card

```yaml
type: custom:iptv-player-card
entry_id: ""        # only one source; default: all
groups: []          # only these groups (names); default: every group with chosen channels
compact: false      # a small player and one row of channels, for a Home dashboard section
layout: auto        # auto | standard | tv. tv: big tiles worked by a TV remote (arrows, OK, channel up/down)
guide_hours: 3
title: ""
```

On a Google TV or Android TV (Home Assistant's app, or a kiosk browser) the card switches to the TV layout by itself.

## Play on TV

The Play on TV button and the `iptv_player.play` service send the channel to a Google Cast device (or any media player
that takes a stream address). The TV fetches the stream from Home Assistant on your home network.

```yaml
action: iptv_player.play
data:
  channel: BBC One Scotland
  player: media_player.living_room_tv
```

`iptv_player.refresh` reads the channel list and downloads the guide again. Your chosen channels also appear under
Media in Home Assistant.

## Sensors

Per source: **Channels shown** and **Guide updated**; for a provider login also **Subscription ends** and
**Connections in use** (with how many the login allows).

## Good to know

- A provider login allows a set number of streams at once (often one or two). Everyone watching the same channel in
  Home Assistant shares one; a second channel is refused rather than pushing another screen off.
- Home Assistant only relays the stream; it never re-encodes it.
- Films, series and catch-up are not part of this integration.
- Channels marked geo-blocked in a free list only play from that country.

## Credits

Plays with [hls.js](https://github.com/video-dev/hls.js) and [mpegts.js](https://github.com/xqq/mpegts.js) (both
Apache-2.0), served by the integration. Licence: MIT.
