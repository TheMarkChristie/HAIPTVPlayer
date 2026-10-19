/*
 * IPTV Player card: live TV from the IPTV Player integration, with the chosen channels, now and next, a guide grid,
 * Play on TV and, for admins, Manage channels.
 *
 *   type: custom:iptv-player-card
 *   entry_id: ""            # only this source; default: every source
 *   groups: []              # only these groups (names); default: every group with chosen channels
 *   compact: false          # true: a small player and one row of channels, for a Home dashboard section
 *   layout: auto            # auto | standard | tv. tv: big tiles worked by a TV remote (arrows, OK, channel up/down);
 *                           #   auto picks tv on a TV (Google TV, Android TV, Chromecast) or a screen with no pointer
 *   guide_hours: 3          # hours the guide grid shows at once
 *   title: ""
 *
 * Streams come through the integration's relay (same origin), played with hls.js or mpegts.js, which the integration
 * serves too; nothing is fetched from anywhere else. The video element is created once and kept, so a refresh of the
 * channel list never interrupts what is playing. Favourites and the last channel are kept per device.
 * Copyright (c) 2026 Mark Christie. MIT licence.
 */
(function () {
  const LIBS = {
    hls: { url: "/iptv_player/vendor/hls.min.js?v=1.7.3", global: "Hls" },
    mpegts: { url: "/iptv_player/vendor/mpegts.min.js?v=1.8.2", global: "mpegts" },
  };
  const FAV_KEY = "iptv_player_favourites";
  const LAST_KEY = "iptv_player_last";
  const REFRESH_MS = 5 * 60 * 1000;
  const TICK_MS = 30 * 1000;
  const PPM = 4;                       // guide pixels per minute

  const STR = {
    en: {
      title: "TV", notSetUp: "IPTV Player is not set up yet. Add it under Settings > Devices & services.",
      loading: "Loading channels", noChannels: "No channels chosen yet.", chooseHint: "Open Manage channels to tick the groups and channels to show.",
      manage: "Manage channels", guide: "Guide", channels: "Channels", playOn: "Play on TV", fullscreen: "Full screen",
      all: "All", favourites: "Favourites", favourite: "Favourite", unfavourite: "Remove favourite", now: "Now", next: "Next",
      nothing: "No guide for this channel", tapToPlay: "Choose a channel to watch", starting: "Starting",
      busy: "Every connection this login allows is in use. Stop watching on another screen and try again.",
      failed: "This channel did not play", retry: "Trying again", noPlayers: "No TVs found. IPTV Player offers the house's Google Cast devices, or the players in its options.",
      sending: (tv) => `Sending to ${tv}…`, sent: (tv) => `Playing on ${tv}`, sendFailed: "Could not play on the TV",
      close: "Close", watch: "Watch", back: "Back", search: "Search groups and channels", shownOf: (a, b) => `${a} of ${b} shown`,
      followGroup: "Follow the group again", rename: "Rename", renamePh: "The provider's name", guideAuto: "Automatic",
      guideChange: "Change guide", guideSearch: "Find a guide channel", guideNone: "No guide", how_manual: "chosen", how_id: "by guide id", how_name: "by name",
      moveUp: "Move up", moveDown: "Move down", preview: "Preview", open: "Show channels", hide: "Hide channels",
      sources: "Guide sources", channelsInGuide: (n) => `${n} channels`, matched: (a, b) => `Guide found for ${a} of ${b} shown channels`,
      expires: (d) => `Subscription ends ${d}`, connections: (a, b) => `${a ?? "?"} of ${b ?? "?"} connections in use`,
      skipped: (n) => `${n} channels skipped (YouTube, Twitch or DASH; they cannot play here)`, listRead: (d) => `Channel list read ${d}`,
      saved: "Saved", more: (n) => `Show ${n} more`, noMatch: "Nothing matches", minutesLeft: (m) => `${m} min left`, unavailable: "unavailable",
      tvHint: "Arrows move, OK plays, channel up and down change channel",
    },
    nb: {
      title: "TV", notSetUp: "IPTV Player er ikke satt opp ennå. Legg den til under Innstillinger > Enheter og tjenester.",
      loading: "Henter kanaler", noChannels: "Ingen kanaler er valgt ennå.", chooseHint: "Åpne Velg kanaler for å krysse av gruppene og kanalene som skal vises.",
      manage: "Velg kanaler", guide: "Programguide", channels: "Kanaler", playOn: "Spill på TV", fullscreen: "Fullskjerm",
      all: "Alle", favourites: "Favoritter", favourite: "Favoritt", unfavourite: "Fjern favoritt", now: "Nå", next: "Neste",
      nothing: "Ingen programguide for denne kanalen", tapToPlay: "Velg en kanal å se", starting: "Starter",
      busy: "Alle tilkoblingene denne innloggingen tillater er i bruk. Stopp på en annen skjerm og prøv igjen.",
      failed: "Kanalen startet ikke", retry: "Prøver igjen", noPlayers: "Fant ingen TV-er. IPTV Player tilbyr husets Google Cast-enheter, eller spillerne i valgene.",
      sending: (tv) => `Sender til ${tv}…`, sent: (tv) => `Spiller på ${tv}`, sendFailed: "Kunne ikke spille på TV-en",
      close: "Lukk", watch: "Se", back: "Tilbake", search: "Søk i grupper og kanaler", shownOf: (a, b) => `${a} av ${b} vises`,
      followGroup: "Følg gruppen igjen", rename: "Gi nytt navn", renamePh: "Leverandørens navn", guideAuto: "Automatisk",
      guideChange: "Bytt guide", guideSearch: "Finn en guidekanal", guideNone: "Ingen guide", how_manual: "valgt", how_id: "etter guide-id", how_name: "etter navn",
      moveUp: "Flytt opp", moveDown: "Flytt ned", preview: "Forhåndsvis", open: "Vis kanaler", hide: "Skjul kanaler",
      sources: "Guidekilder", channelsInGuide: (n) => `${n} kanaler`, matched: (a, b) => `Guide funnet for ${a} av ${b} viste kanaler`,
      expires: (d) => `Abonnementet slutter ${d}`, connections: (a, b) => `${a ?? "?"} av ${b ?? "?"} tilkoblinger i bruk`,
      skipped: (n) => `${n} kanaler hoppet over (YouTube, Twitch eller DASH; de kan ikke spilles her)`, listRead: (d) => `Kanalliste lest ${d}`,
      saved: "Lagret", more: (n) => `Vis ${n} til`, noMatch: "Ingenting passer", minutesLeft: (m) => `${m} min igjen`, unavailable: "utilgjengelig",
      tvHint: "Piltastene flytter, OK spiller, kanal opp og ned bytter kanal",
    },
  };

  const STYLE = `
    :host { display: block; --ip-radius: 12px; --ip-tile: 168px; --ip-accent: var(--primary-color, #03a9f4); }
    :host([layout="tv"]) { --ip-tile: 230px; font-size: 1.12em; }
    ha-card { overflow: hidden; display: block; }
    .title { font-size: 1.25em; font-weight: 500; padding: 12px 16px 0; color: var(--primary-text-color); }
    .stage { position: relative; background: #000; aspect-ratio: 16 / 9; max-height: 62vh; width: 100%; }
    :host([compact]) .stage { max-height: 240px; }
    .stage video { position: absolute; inset: 0; width: 100%; height: 100%; background: #000; }
    .stage .veil { position: absolute; inset: 0; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 10px; color: #fff; text-align: center; padding: 20px; background: radial-gradient(ellipse at center, rgba(40,40,48,0.6), rgba(0,0,0,0.92)); pointer-events: none; }
    .stage .veil[hidden] { display: none; }
    .stage .veil .big { font-size: 1.2em; font-weight: 600; }
    .stage .veil .small { font-size: 0.9em; opacity: 0.85; max-width: 560px; line-height: 1.4; }
    .spinner { width: 38px; height: 38px; border-radius: 50%; border: 4px solid rgba(255,255,255,0.25); border-top-color: #fff; animation: spin 0.9s linear infinite; }
    @keyframes spin { to { transform: rotate(360deg); } }
    @media (prefers-reduced-motion: reduce) { .spinner { animation-duration: 3s; } }
    .info { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 14px; padding: 10px 16px; border-bottom: 1px solid var(--divider-color, rgba(127,127,127,0.2)); }
    .info .what { flex: 1 1 260px; min-width: 0; }
    .info .ch { font-weight: 600; color: var(--primary-text-color); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .info .prog { font-size: 0.9em; color: var(--secondary-text-color); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .info .prog b { color: var(--primary-text-color); font-weight: 500; }
    .actions { display: flex; flex-wrap: wrap; gap: 8px; position: relative; }
    .btn { display: inline-flex; align-items: center; gap: 6px; border: 0; border-radius: 999px; padding: 8px 14px; font: inherit; font-size: 0.9em; font-weight: 500; cursor: pointer; background: var(--secondary-background-color, rgba(127,127,127,0.18)); color: var(--primary-text-color); }
    .btn.on { background: var(--ip-accent); color: var(--text-primary-color, #fff); }
    .btn[disabled] { opacity: 0.5; cursor: default; }
    .btn svg { width: 18px; height: 18px; flex: 0 0 18px; }
    .btn:focus-visible, .chip:focus-visible, .tile:focus-visible, .prog-block:focus-visible, .mrow button:focus-visible, .mrow input:focus-visible { outline: 3px solid var(--ip-accent); outline-offset: 2px; }
    :host([layout="tv"]) .btn:focus-visible, :host([layout="tv"]) .chip:focus-visible, :host([layout="tv"]) .tile:focus, :host([layout="tv"]) .prog-block:focus { outline: 4px solid var(--ip-accent); outline-offset: 3px; }
    .menu { position: absolute; right: 0; top: calc(100% + 6px); z-index: 5; min-width: 220px; background: var(--card-background-color, #fff); color: var(--primary-text-color); border-radius: 12px; box-shadow: 0 10px 30px rgba(0,0,0,0.3); padding: 6px; display: flex; flex-direction: column; }
    .menu button { text-align: left; border: 0; background: none; font: inherit; padding: 10px 12px; border-radius: 8px; cursor: pointer; color: inherit; }
    .menu button[disabled] { opacity: 0.45; cursor: default; }
    .menu button:hover, .menu button:focus-visible { background: var(--secondary-background-color, rgba(127,127,127,0.15)); outline: none; }
    .menu .note { padding: 10px 12px; font-size: 0.88em; color: var(--secondary-text-color); }
    .status { padding: 6px 16px 0; font-size: 0.85em; color: var(--secondary-text-color); min-height: 0; }
    .status.err { color: var(--error-color, #db4437); }
    .chips { display: flex; gap: 8px; overflow-x: auto; padding: 10px 16px 4px; scrollbar-width: thin; }
    :host([compact]) .chips { display: none; }
    .chip { flex: 0 0 auto; border: 1px solid var(--divider-color, rgba(127,127,127,0.3)); background: none; color: var(--primary-text-color); border-radius: 999px; padding: 6px 12px; font: inherit; font-size: 0.88em; cursor: pointer; white-space: nowrap; }
    .chip.on { background: var(--ip-accent); border-color: var(--ip-accent); color: var(--text-primary-color, #fff); }
    .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(var(--ip-tile), 1fr)); gap: 10px; padding: 10px 16px 16px; }
    :host([compact]) .grid { display: flex; overflow-x: auto; padding-bottom: 12px; }
    :host([compact]) .grid .tile { flex: 0 0 150px; }
    .tile { position: relative; display: flex; flex-direction: column; gap: 6px; text-align: left; border: 0; border-radius: var(--ip-radius); padding: 10px; background: var(--secondary-background-color, rgba(127,127,127,0.12)); color: var(--primary-text-color); font: inherit; cursor: pointer; min-width: 0; }
    .tile:hover { background: var(--state-icon-hover-color, rgba(127,127,127,0.2)); }
    .tile.playing { box-shadow: inset 0 0 0 2px var(--ip-accent); }
    .tile .top { display: flex; align-items: center; gap: 10px; min-width: 0; }
    .tile .top > span:last-child { min-width: 0; overflow: hidden; }
    .logo { flex: 0 0 auto; width: 54px; height: 36px; border-radius: 6px; background: rgba(255,255,255,0.92); display: flex; align-items: center; justify-content: center; overflow: hidden; }
    :host([layout="tv"]) .logo { width: 72px; height: 46px; }
    .logo img { max-width: 92%; max-height: 88%; object-fit: contain; }
    .logo .ini { font-weight: 700; font-size: 0.85em; color: #333; }
    .tile .name { font-weight: 600; font-size: 0.92em; line-height: 1.2; overflow: hidden; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; }
    .tile .num { font-size: 0.72em; color: var(--secondary-text-color); }
    .tile .now { font-size: 0.84em; line-height: 1.25; color: var(--primary-text-color); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .tile .nxt { font-size: 0.76em; color: var(--secondary-text-color); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .tile .fav { position: absolute; top: 6px; right: 8px; font-size: 0.8em; color: var(--ip-accent); }
    .bar { height: 3px; border-radius: 2px; background: rgba(127,127,127,0.3); overflow: hidden; }
    .bar i { display: block; height: 100%; background: var(--ip-accent); }
    .msg { padding: 22px 16px; color: var(--secondary-text-color); line-height: 1.5; }
    .hint { padding: 0 16px 10px; font-size: 0.8em; color: var(--secondary-text-color); }

    .guide { position: relative; overflow: auto; max-height: 70vh; margin: 8px 0 12px; }
    .g-inner { position: relative; }
    .g-head { position: sticky; top: 0; z-index: 3; display: flex; background: var(--card-background-color, #fff); border-bottom: 1px solid var(--divider-color, rgba(127,127,127,0.25)); }
    .g-corner { position: sticky; left: 0; z-index: 4; flex: 0 0 170px; background: var(--card-background-color, #fff); }
    .g-times { position: relative; height: 30px; }
    .g-times span { position: absolute; top: 7px; font-size: 0.78em; color: var(--secondary-text-color); padding-left: 4px; border-left: 1px solid var(--divider-color, rgba(127,127,127,0.3)); }
    .g-row { display: flex; border-bottom: 1px solid var(--divider-color, rgba(127,127,127,0.15)); }
    .g-ch { position: sticky; left: 0; z-index: 2; flex: 0 0 170px; display: flex; align-items: center; gap: 8px; padding: 6px 8px; background: var(--card-background-color, #fff); border: 0; border-right: 1px solid var(--divider-color, rgba(127,127,127,0.25)); font: inherit; font-size: 0.85em; text-align: left; color: var(--primary-text-color); cursor: pointer; min-width: 0; }
    .g-ch .logo { width: 40px; height: 28px; }
    .g-ch span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .g-progs { position: relative; height: 54px; }
    :host([layout="tv"]) .g-progs { height: 66px; }
    .prog-block { position: absolute; top: 4px; bottom: 4px; border: 0; border-radius: 8px; padding: 5px 8px; background: var(--secondary-background-color, rgba(127,127,127,0.14)); color: var(--primary-text-color); font: inherit; font-size: 0.8em; text-align: left; overflow: hidden; cursor: pointer; }
    .prog-block.live { background: color-mix(in srgb, var(--ip-accent) 22%, var(--card-background-color, #fff)); }
    .prog-block b { display: block; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .prog-block small { color: var(--secondary-text-color); }
    .g-now { position: absolute; top: 0; bottom: 0; width: 2px; background: var(--error-color, #db4437); z-index: 1; pointer-events: none; }

    .manage { padding: 6px 16px 16px; }
    .m-top { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin: 6px 0 10px; }
    .m-top input[type=search] { flex: 1 1 240px; min-width: 0; padding: 9px 12px; border-radius: 10px; border: 1px solid var(--divider-color, rgba(127,127,127,0.4)); background: var(--card-background-color); color: var(--primary-text-color); font: inherit; }
    .m-facts { font-size: 0.84em; color: var(--secondary-text-color); line-height: 1.6; margin-bottom: 10px; }
    .m-facts .err { color: var(--error-color, #db4437); }
    .mrow { display: flex; align-items: center; gap: 8px; padding: 6px 4px; border-bottom: 1px solid var(--divider-color, rgba(127,127,127,0.15)); min-width: 0; }
    .mrow.group { font-weight: 600; }
    .mrow.channel { padding-left: 30px; flex-wrap: wrap; }
    .mrow label { display: flex; align-items: center; gap: 10px; flex: 1 1 200px; min-width: 0; cursor: pointer; }
    .mrow label span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .mrow input[type=checkbox] { width: 20px; height: 20px; flex: 0 0 20px; accent-color: var(--ip-accent); }
    .mrow .count { font-size: 0.82em; font-weight: 400; color: var(--secondary-text-color); white-space: nowrap; }
    .mrow .gline { flex: 1 0 100%; padding-left: 30px; font-size: 0.8em; color: var(--secondary-text-color); display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
    .ibtn { border: 0; background: none; color: var(--secondary-text-color); font: inherit; font-size: 0.82em; padding: 4px 8px; border-radius: 8px; cursor: pointer; }
    .ibtn:hover { background: var(--secondary-background-color, rgba(127,127,127,0.15)); color: var(--primary-text-color); }
    .mrow input[type=text], .gsearch input { padding: 6px 10px; border-radius: 8px; border: 1px solid var(--divider-color, rgba(127,127,127,0.4)); background: var(--card-background-color); color: var(--primary-text-color); font: inherit; font-size: 0.88em; min-width: 0; }
    .gsearch { flex: 1 0 100%; padding: 4px 0 6px 30px; display: flex; flex-direction: column; gap: 4px; }
    .gsearch button { text-align: left; }
    .tabs { display: flex; gap: 6px; flex-wrap: wrap; }

    dialog.sheet { border: 0; padding: 0; border-radius: 16px; width: min(560px, calc(100vw - 32px)); background: var(--card-background-color, #1e1e1e); color: var(--primary-text-color); box-shadow: 0 20px 60px rgba(0,0,0,0.5); }
    dialog.sheet::backdrop { background: rgba(0,0,0,0.55); }
    .sheet-body { padding: 18px 20px 20px; }
    .sheet-body h2 { margin: 0 0 4px; font-size: 1.3em; }
    .sheet-body .when { color: var(--secondary-text-color); margin-bottom: 10px; }
    .sheet-body p { line-height: 1.5; margin: 0 0 14px; }
    .sheet-actions { display: flex; gap: 8px; justify-content: flex-end; }
  `;

  const ICON = {
    play: '<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M8 5v14l11-7z"/></svg>',
    cast: '<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M1 18v3h3a3 3 0 0 0-3-3m0-4v2a5 5 0 0 1 5 5h2a7 7 0 0 0-7-7m0-4v2a9 9 0 0 1 9 9h2A11 11 0 0 0 1 10m20-7H3a2 2 0 0 0-2 2v3h2V5h18v14h-7v2h7a2 2 0 0 0 2-2V5a2 2 0 0 0-2-2"/></svg>',
    guide: '<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M3 4h18v2H3zm0 4h7v5H3zm9 0h9v2h-9zm0 3h9v2h-9zM3 15h18v2H3zm0 4h12v2H3z"/></svg>',
    grid: '<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M3 3h8v8H3zm10 0h8v8h-8zM3 13h8v8H3zm10 0h8v8h-8z"/></svg>',
    gear: '<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M3 6h12v2H3zm0 5h18v2H3zm0 5h8v2H3zm14-11h2v4h-2zm-6 10h2v4h-2z"/></svg>',
    full: '<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M5 5h5v2H7v3H5zm9 0h5v5h-2V7h-3zM5 14h2v3h3v2H5zm12 3v-3h2v5h-5v-2z"/></svg>',
    star: '<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="m12 17.3 6.2 3.7-1.6-7 5.4-4.7-7.1-.6L12 2 9.1 8.7 2 9.3l5.4 4.7-1.6 7z"/></svg>',
  };

  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const store = {
    get(key, fallback) { try { const v = localStorage.getItem(key); return v == null ? fallback : JSON.parse(v); } catch (e) { return fallback; } },
    set(key, value) { try { localStorage.setItem(key, JSON.stringify(value)); } catch (e) { /* private mode */ } },
  };

  const loading = {};
  /* the player libraries are UMD builds; run them with no AMD or CommonJS loader in sight so each always sets its
     global, whatever else the page has loaded */
  function loadLib(name) {
    const lib = LIBS[name];
    if (window[lib.global]) return Promise.resolve(window[lib.global]);
    if (!loading[name]) {
      loading[name] = fetch(lib.url, { credentials: "same-origin" })
        .then((r) => { if (!r.ok) throw new Error(`${name} ${r.status}`); return r.text(); })
        .then((src) => {
          try { (new Function("define", "module", "exports", src)).call(window); } catch (e) { /* fall through to a script tag */ }
          if (window[lib.global]) return window[lib.global];
          return new Promise((resolve, reject) => {
            const s = document.createElement("script");
            s.src = lib.url;
            s.onload = () => (window[lib.global] ? resolve(window[lib.global]) : reject(new Error(`${name} did not load`)));
            s.onerror = () => reject(new Error(`${name} did not load`));
            document.head.appendChild(s);
          });
        })
        .catch((e) => { delete loading[name]; throw e; });
    }
    return loading[name];
  }

  function isTv() {
    const ua = navigator.userAgent || "";
    if (/Android TV|GoogleTV|Google TV|Chromecast|BRAVIA|AFT[A-Z]|SHIELD|Smart ?TV|Tizen|Web0S|HbbTV/i.test(ua)) return true;
    try { return window.matchMedia("(any-pointer: none)").matches && Math.min(screen.width, screen.height) >= 540; } catch (e) { return false; }
  }

  class IptvPlayerCard extends HTMLElement {
    static getStubConfig() { return {}; }

    constructor() {
      super();
      this.attachShadow({ mode: "open" });
      this._config = {};
      this._data = null;
      this._error = null;
      this._view = "channels";
      this._filter = store.get("iptv_player_filter", "all");
      this._favs = new Set(store.get(FAV_KEY, []));
      this._current = null;        // uid of the channel on screen
      this._session = null;        // {token, url, kind, entry_id, key}
      this._player = null;         // hls.js or mpegts.js instance
      this._attempts = 0;
      this._built = false;
      this._manage = { entry: null, open: new Set(), query: "", groups: null, channels: {}, search: null, guideFor: null, renameFor: null };
      this._guideData = {};
    }

    setConfig(config) {
      this._config = { guide_hours: 3, layout: "auto", ...(config || {}) };
      if (this._built) this._render();
    }

    set hass(hass) {
      const first = !this._hass;
      this._hass = hass;
      if (first && this.isConnected) this._start();
    }

    get _lang() { const l = (this._hass && (this._hass.locale?.language || this._hass.language)) || "en"; return /^(nb|no|nn)/.test(l) ? "nb" : "en"; }
    _t(key, ...args) { const v = (STR[this._lang] || STR.en)[key] ?? STR.en[key]; return typeof v === "function" ? v(...args) : v ?? key; }
    get _tv() { return this._config.layout === "tv" || (this._config.layout !== "standard" && isTv()); }

    connectedCallback() {
      if (this._hass) this._start();
    }

    disconnectedCallback() {
      this._stopPlayer(true);
      clearInterval(this._tick);
      clearInterval(this._reload);
      if (this._unsub) { this._unsub.then((u) => u && u()).catch(() => {}); this._unsub = null; }
      this._started = false;
    }

    getCardSize() { return this._config.compact ? 6 : 12; }

    _start() {
      if (this._started) return;
      this._started = true;
      if (!this._built) this._build();
      this._load();
      this._tick = setInterval(() => this._renderTimes(), TICK_MS);
      this._reload = setInterval(() => this._load(), REFRESH_MS);
      this._unsub = this._hass.connection.subscribeMessage(() => this._loadSoon(), { type: "iptv_player/subscribe" }).catch(() => null);
    }

    _loadSoon() { clearTimeout(this._soon); this._soon = setTimeout(() => this._load(), 800); }

    async _load() {
      try {
        const data = await this._hass.callWS({ type: "iptv_player/channels", ...(this._config.entry_id ? { entry_id: this._config.entry_id } : {}) });
        this._data = data;
        this._error = null;
      } catch (e) {
        this._error = e && e.code === "not_set_up" ? "notSetUp" : (this._data ? null : "notSetUp");
      }
      this._render();
      if (this._view === "guide") this._loadGuide();
      if (this._view === "manage" && this._manage.groups) this._loadCatalog(false);
    }

    /* ---- the frame: built once, so the video element survives every refresh ---- */
    _build() {
      this._built = true;
      const root = this.shadowRoot;
      root.innerHTML = `<style>${STYLE}</style><ha-card>
        <div class="title" hidden></div>
        <div class="stage"><video playsinline controls preload="none"></video>
          <div class="veil"><div class="big"></div><div class="small"></div></div></div>
        <div class="info"><div class="what"><div class="ch"></div><div class="prog"></div></div><div class="actions"></div></div>
        <div class="status" aria-live="polite"></div>
        <div class="chips" role="tablist"></div>
        <div class="body"></div>
        <div class="hint" hidden></div>
      </ha-card>`;
      this._video = root.querySelector("video");
      this._video.addEventListener("error", () => this._onVideoError());
      this._video.addEventListener("playing", () => { this._attempts = 0; this._veil(null); });
      this._video.addEventListener("waiting", () => { if (this._session) this._veil("spin"); });
      root.addEventListener("keydown", (ev) => this._keys(ev));
      root.querySelector(".body").addEventListener("click", (ev) => this._click(ev));
      root.querySelector(".chips").addEventListener("click", (ev) => {
        const chip = ev.target.closest(".chip");
        if (!chip) return;
        this._filter = chip.dataset.filter;
        store.set("iptv_player_filter", this._filter);
        this._render();
        if (this._view === "guide") this._loadGuide();
      });
      root.querySelector(".actions").addEventListener("click", (ev) => this._action(ev));
      this._veil("idle");
    }

    _veil(kind, text) {
      const veil = this.shadowRoot.querySelector(".veil");
      if (!veil) return;
      if (!kind) { veil.hidden = true; return; }
      veil.hidden = false;
      const big = veil.querySelector(".big"), small = veil.querySelector(".small");
      veil.querySelectorAll(".spinner").forEach((s) => s.remove());
      if (kind === "spin") {
        const sp = document.createElement("div"); sp.className = "spinner"; veil.prepend(sp);
        big.textContent = text || ""; small.textContent = "";
      } else if (kind === "idle") {
        big.textContent = this._t("tapToPlay"); small.textContent = this._tv ? this._t("tvHint") : "";
      } else {
        big.textContent = this._t("failed"); small.textContent = text || "";
      }
    }

    /* ---- what the card shows ---- */
    _channels() {
      const all = (this._data && this._data.channels) || [];
      const groups = this._config.groups && this._config.groups.length ? new Set(this._config.groups.map((g) => String(g).toLowerCase())) : null;
      const names = new Map(((this._data && this._data.groups) || []).map((g) => [g.id, g.name]));
      const scoped = groups ? all.filter((c) => groups.has(String(names.get(c.group) || "").toLowerCase())) : all;
      if (this._filter === "fav") return scoped.filter((c) => this._favs.has(c.uid));
      if (this._filter && this._filter !== "all") return scoped.filter((c) => c.group === this._filter);
      return scoped;
    }

    _byUid(uid) {
      const found = ((this._data && this._data.channels) || []).find((c) => c.uid === uid);
      return found || (this._extra && this._extra.uid === uid ? this._extra : undefined);
    }

    _render() {
      if (!this._built) return;
      const root = this.shadowRoot;
      this.toggleAttribute("compact", !!this._config.compact);
      this.setAttribute("layout", this._tv ? "tv" : "standard");
      const title = root.querySelector(".title");
      title.hidden = !this._config.title;
      title.textContent = this._config.title || "";
      const hint = root.querySelector(".hint");
      hint.hidden = !this._tv;
      hint.textContent = this._t("tvHint");
      this._renderInfo();
      this._renderChips();
      const body = root.querySelector(".body");
      if (this._error === "notSetUp") { body.innerHTML = `<div class="msg">${esc(this._t("notSetUp"))}</div>`; return; }
      if (!this._data) { body.innerHTML = `<div class="msg">${esc(this._t("loading"))}</div>`; return; }
      if (this._view === "manage") return this._renderManage();
      if (this._view === "guide") return this._renderGuide();
      this._renderGrid();
    }

    _renderChips() {
      const chips = this.shadowRoot.querySelector(".chips");
      if (!this._data || this._view === "manage") { chips.innerHTML = ""; return; }
      const groups = (this._data.groups || []).filter((g) => this._data.channels.some((c) => c.group === g.id));
      const scoped = this._config.groups && this._config.groups.length
        ? groups.filter((g) => this._config.groups.map((x) => String(x).toLowerCase()).includes(g.name.toLowerCase())) : groups;
      const items = [["all", this._t("all")], ...(this._favs.size ? [["fav", this._t("favourites")]] : []), ...scoped.map((g) => [g.id, g.name])];
      if (!items.some(([id]) => id === this._filter)) this._filter = "all";
      chips.innerHTML = items.length > 2 || this._favs.size
        ? items.map(([id, name]) => `<button class="chip${id === this._filter ? " on" : ""}" role="tab" aria-selected="${id === this._filter}" data-filter="${esc(id)}">${esc(name)}</button>`).join("")
        : "";
    }

    _progress(p, now) {
      if (!p || !p.start || !p.stop) return null;
      return Math.max(0, Math.min(100, Math.round(((now - p.start) / (p.stop - p.start)) * 100)));
    }

    _time(ts) {
      try {
        return new Intl.DateTimeFormat(this._lang === "nb" ? "nb-NO" : (this._hass.locale?.language || "en-GB"),
          { hour: "2-digit", minute: "2-digit", timeZone: this._hass.config?.time_zone || undefined }).format(new Date(ts * 1000));
      } catch (e) { return new Date(ts * 1000).toTimeString().slice(0, 5); }
    }

    _date(ts) {
      try {
        return new Intl.DateTimeFormat(this._lang === "nb" ? "nb-NO" : (this._hass.locale?.language || "en-GB"),
          { day: "numeric", month: "short", year: "numeric", timeZone: this._hass.config?.time_zone || undefined }).format(new Date(ts * 1000));
      } catch (e) { return new Date(ts * 1000).toDateString(); }
    }

    /* now and next as the clock moves: a programme that has ended gives way to the next one without a reload */
    _nowNext(c) {
      const now = Date.now() / 1000;
      let cur = c.now, nxt = c.next;
      if (cur && cur.stop <= now) { cur = nxt && nxt.start <= now ? nxt : null; nxt = cur === c.next ? null : nxt; }
      return [cur, nxt];
    }

    _logo(c) {
      const ini = esc((c.name || "?").replace(/[^A-Za-z0-9 ]/g, "").split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]).join("").toUpperCase());
      return `<span class="logo">${c.logo ? `<img src="${esc(c.logo)}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.replaceWith(Object.assign(document.createElement('span'),{className:'ini',textContent:'${ini}'}))">` : `<span class="ini">${ini}</span>`}</span>`;
    }

    _renderGrid() {
      const body = this.shadowRoot.querySelector(".body");
      const list = this._channels();
      if (!list.length) {
        const admin = this._data.is_admin;
        body.innerHTML = `<div class="msg">${esc(this._t("noChannels"))} ${admin ? esc(this._t("chooseHint")) : ""}</div>`;
        return;
      }
      const now = Date.now() / 1000;
      const focused = this.shadowRoot.activeElement && this.shadowRoot.activeElement.dataset ? this.shadowRoot.activeElement.dataset.uid : null;
      body.innerHTML = `<div class="grid">${list.map((c) => {
        const [cur, nxt] = this._nowNext(c);
        const pct = this._progress(cur, now);
        return `<button class="tile${c.uid === this._current ? " playing" : ""}" data-uid="${esc(c.uid)}" aria-label="${esc(c.name)}${cur ? `, ${esc(cur.title)}` : ""}">
          ${this._favs.has(c.uid) ? `<span class="fav" aria-hidden="true">★</span>` : ""}
          <span class="top">${this._logo(c)}<span><span class="name">${esc(c.name)}</span>${c.number != null && !this._config.compact ? `<span class="num">${esc(c.number)}</span>` : ""}</span></span>
          <span class="now">${cur ? esc(cur.title) : "&nbsp;"}</span>
          ${pct != null ? `<span class="bar"><i style="width:${pct}%"></i></span>` : ""}
          ${nxt && !this._config.compact ? `<span class="nxt">${esc(this._time(nxt.start))} ${esc(nxt.title)}</span>` : ""}
        </button>`;
      }).join("")}</div>`;
      if (focused) { const el = body.querySelector(`.tile[data-uid="${CSS.escape(focused)}"]`); if (el) el.focus({ preventScroll: true }); }
    }

    _renderTimes() {
      this._renderInfo();
      if (this._view === "channels") this._renderGrid();
      if (this._view === "guide") this._placeNowLine();
    }

    _renderInfo() {
      const root = this.shadowRoot;
      const c = this._current ? this._byUid(this._current) : null;
      root.querySelector(".info .ch").textContent = c ? c.name : (this._config.title || this._t("title"));
      const prog = root.querySelector(".info .prog");
      if (c) {
        const [cur, nxt] = this._nowNext(c);
        const now = Date.now() / 1000;
        prog.innerHTML = cur
          ? `<b>${esc(cur.title)}</b> · ${esc(this._time(cur.start))}–${esc(this._time(cur.stop))} · ${esc(this._t("minutesLeft", Math.max(0, Math.round((cur.stop - now) / 60))))}${nxt ? ` · ${esc(this._t("next"))}: ${esc(this._time(nxt.start))} ${esc(nxt.title)}` : ""}`
          : esc(this._t("nothing"));
      } else {
        prog.textContent = "";
      }
      const admin = this._data && this._data.is_admin;
      const actions = root.querySelector(".actions");
      const open = actions.querySelector(".menu");
      const had = root.activeElement && root.activeElement.dataset ? root.activeElement.dataset.act : null;
      const view = this._view;
      actions.innerHTML = `
        ${!this._config.compact ? `<button class="btn${view === "guide" ? " on" : ""}" data-act="guide" aria-pressed="${view === "guide"}">${view === "guide" ? ICON.grid : ICON.guide}${esc(view === "guide" ? this._t("channels") : this._t("guide"))}</button>` : ""}
        <button class="btn" data-act="fav"${c ? "" : " disabled"}>${ICON.star}${esc(c && this._favs.has(c.uid) ? this._t("unfavourite") : this._t("favourite"))}</button>
        <button class="btn" data-act="cast"${c ? "" : " disabled"} aria-haspopup="menu">${ICON.cast}${esc(this._t("playOn"))}</button>
        <button class="btn" data-act="full"${c ? "" : " disabled"}>${ICON.full}${esc(this._t("fullscreen"))}</button>
        ${admin && !this._config.compact ? `<button class="btn${view === "manage" ? " on" : ""}" data-act="manage" aria-pressed="${view === "manage"}">${ICON.gear}${esc(this._t("manage"))}</button>` : ""}`;
      if (open) actions.appendChild(open);
      if (had) { const el = actions.querySelector(`[data-act="${had}"]`); if (el && !el.disabled) el.focus({ preventScroll: true }); }
    }

    _status(text, err) {
      const s = this.shadowRoot.querySelector(".status");
      s.textContent = text || "";
      s.className = `status${err ? " err" : ""}`;
      clearTimeout(this._statusTimer);
      if (text && !err) this._statusTimer = setTimeout(() => { s.textContent = ""; }, 5000);
    }

    _action(ev) {
      const btn = ev.target.closest("button");
      if (!btn) return;
      const act = btn.dataset.act;
      if (btn.dataset.player) return this._cast(btn.dataset.player, btn.dataset.name);
      if (act === "guide") { this._view = this._view === "guide" ? "channels" : "guide"; this._render(); if (this._view === "guide") this._loadGuide(); return; }
      if (act === "manage") { this._view = this._view === "manage" ? "channels" : "manage"; if (this._view === "manage") this._loadCatalog(true); this._render(); return; }
      if (act === "fav" && this._current) {
        if (this._favs.has(this._current)) this._favs.delete(this._current); else this._favs.add(this._current);
        store.set(FAV_KEY, [...this._favs]);
        this._render();
        return;
      }
      if (act === "full") return this._fullscreen();
      if (act === "cast") return this._castMenu(btn);
    }

    _castMenu(anchor) {
      const actions = this.shadowRoot.querySelector(".actions");
      const old = actions.querySelector(".menu");
      if (old) { old.remove(); return; }
      const players = (this._data && this._data.players) || [];
      const menu = document.createElement("div");
      menu.className = "menu";
      menu.setAttribute("role", "menu");
      menu.innerHTML = players.length
        ? players.map((p) => `<button role="menuitem" data-player="${esc(p.entity_id)}" data-name="${esc(p.name)}"${p.available ? "" : " disabled"}>${esc(p.name)}${p.available ? "" : ` (${esc(this._t("unavailable"))})`}</button>`).join("")
        : `<div class="note">${esc(this._t("noPlayers"))}</div>`;
      actions.appendChild(menu);
      // under its own button, kept inside the card
      const left = Math.min(anchor.offsetLeft, Math.max(0, actions.clientWidth - menu.offsetWidth));
      menu.style.left = `${left}px`;
      menu.style.right = "auto";
      const first = menu.querySelector("button:not([disabled])");
      if (first) first.focus();
      const close = (e) => { if (!e.composedPath().includes(menu) && !e.composedPath().includes(anchor)) { menu.remove(); document.removeEventListener("click", close, true); } };
      setTimeout(() => document.addEventListener("click", close, true));
    }

    async _cast(entityId, name) {
      const menu = this.shadowRoot.querySelector(".menu");
      if (menu) menu.remove();
      if (!this._current) return;
      this._status(this._t("sending", name));
      try {
        await this._hass.callService("iptv_player", "play", { channel: this._current, player: entityId });
        this._status(this._t("sent", name));
        this.dispatchEvent(new CustomEvent("hass-notification", { detail: { message: this._t("sent", name) }, bubbles: true, composed: true }));
      } catch (e) {
        this._status(`${this._t("sendFailed")}: ${(e && (e.message || e.error)) || e}`, true);
      }
    }

    _fullscreen() {
      const stage = this.shadowRoot.querySelector(".stage");
      const v = this._video;
      if (document.fullscreenElement) { document.exitFullscreen().catch(() => {}); return; }
      if (stage.requestFullscreen) stage.requestFullscreen().catch(() => { if (v.webkitEnterFullscreen) v.webkitEnterFullscreen(); });
      else if (v.webkitEnterFullscreen) v.webkitEnterFullscreen();
    }

    _click(ev) {
      const tile = ev.target.closest(".tile, .g-ch");
      if (tile && tile.dataset.uid) {
        if (tile.dataset.uid === this._current && this._session && this._tv) { this._fullscreen(); return; }
        this._play(tile.dataset.uid);
        return;
      }
      const block = ev.target.closest(".prog-block");
      if (block) { this._programme(block.dataset.uid, Number(block.dataset.start)); return; }
      if (this._view === "manage") this._manageClick(ev);
    }

    /* ---- playing ---- */
    async _play(uid, preview) {
      if (preview) this._extra = preview;
      const c = this._byUid(uid);
      if (!c) return;
      this._current = uid;
      store.set(LAST_KEY, uid);
      this._attempts = 0;
      this._render();
      await this._open(c);
    }

    async _open(c) {
      this._stopPlayer(true);
      this._veil("spin", this._t("starting"));
      let s;
      try {
        s = await this._hass.callWS({ type: "iptv_player/stream", entry_id: c.entry_id, key: c.key });
      } catch (e) {
        this._veil("error", e && e.code === "busy" ? this._t("busy") : ((e && e.message) || ""));
        return;
      }
      if (this._current !== c.uid) { this._release(s.token); return; }
      this._session = { ...s, entry_id: c.entry_id, key: c.key, uid: c.uid };
      try {
        await this._attach(s);
      } catch (e) {
        this._veil("error", String((e && e.message) || e));
      }
    }

    async _attach(s) {
      const v = this._video;
      const nativeHls = !!v.canPlayType("application/vnd.apple.mpegurl");
      if (s.kind === "hls") {
        const Hls = await loadLib("hls").catch(() => null);
        if (Hls && Hls.isSupported()) {
          const hls = new Hls({ backBufferLength: 30, maxBufferLength: 24, liveDurationInfinity: true, enableWorker: true, manifestLoadingMaxRetry: 2, levelLoadingMaxRetry: 3, fragLoadingMaxRetry: 3 });
          this._player = { kind: "hls", obj: hls };
          hls.on(Hls.Events.ERROR, (_e, data) => {
            if (!data || !data.fatal) return;
            if (data.type === Hls.ErrorTypes.MEDIA_ERROR && this._attempts < 2) { this._attempts += 1; hls.recoverMediaError(); return; }
            this._recover(data.response && data.response.code);
          });
          hls.loadSource(s.url);
          hls.attachMedia(v);
        } else if (nativeHls) {
          this._player = { kind: "native" };
          v.src = s.url;
        } else {
          throw new Error("HLS cannot play in this browser");
        }
      } else {
        const mpegts = await loadLib("mpegts").catch(() => null);
        if (mpegts && mpegts.isSupported() && mpegts.getFeatureList().mseLivePlayback) {
          const p = mpegts.createPlayer({ type: "mpegts", isLive: true, url: s.url }, { enableWorker: false, liveBufferLatencyChasing: true, lazyLoad: false });
          this._player = { kind: "mpegts", obj: p };
          p.on(mpegts.Events.ERROR, (type) => {
            if (type === mpegts.ErrorTypes.MEDIA_ERROR) { this._nativeRaw(s); return; }   // not MPEG-TS: radio and the like
            this._recover();
          });
          p.attachMediaElement(v);
          p.load();
        } else {
          this._nativeRaw(s);
        }
      }
      try { await v.play(); } catch (e) { /* autoplay refused: the controls are there */ }
    }

    _nativeRaw(s) {
      this._destroyLib();
      this._player = { kind: "native" };
      this._video.src = s.url;
      this._video.play().catch(() => {});
    }

    _onVideoError() {
      if (!this._session || !this._player || this._player.kind !== "native") return;
      this._recover();
    }

    /* the relay ends a session 45 s after its last request (a paused player) and the provider's own addresses
       expire: open the channel again, twice at most, then say so */
    _recover(code) {
      const c = this._current && this._byUid(this._current);
      if (!c || this._attempts >= 2) {
        this._veil("error", code === 403 ? this._t("busy") : "");
        this._stopPlayer(true);
        return;
      }
      this._attempts += 1;
      this._status(this._t("retry"));
      clearTimeout(this._retryTimer);
      this._retryTimer = setTimeout(() => this._open(c), 1500 * this._attempts);
    }

    _destroyLib() {
      const p = this._player;
      if (p && p.obj) {
        try { if (p.kind === "hls") p.obj.destroy(); else { p.obj.pause(); p.obj.unload(); p.obj.detachMediaElement(); p.obj.destroy(); } } catch (e) { /* already gone */ }
      }
      this._player = null;
    }

    _stopPlayer(release) {
      this._destroyLib();
      const v = this._video;
      if (v) { try { v.pause(); v.removeAttribute("src"); v.load(); } catch (e) { /* nothing loaded */ } }
      if (release && this._session) this._release(this._session.token);
      if (release) this._session = null;
    }

    _release(token) {
      if (!token || !this._hass) return;
      this._hass.callWS({ type: "iptv_player/release", token }).catch(() => {});
    }

    _step(delta) {
      const list = this._channels();
      if (!list.length) return;
      const i = list.findIndex((c) => c.uid === this._current);
      const next = list[(i + delta + list.length) % list.length];
      this._play(next.uid);
      const tile = this.shadowRoot.querySelector(`[data-uid="${CSS.escape(next.uid)}"]`);
      if (tile) tile.focus();
    }

    /* ---- the remote: arrows move to the nearest tile that way, channel up/down change channel ---- */
    _keys(ev) {
      const k = ev.key;
      if (["ChannelUp", "PageUp", "MediaTrackNext"].includes(k)) { ev.preventDefault(); this._step(1); return; }
      if (["ChannelDown", "PageDown", "MediaTrackPrevious"].includes(k)) { ev.preventDefault(); this._step(-1); return; }
      if (k === "Escape" || k === "GoBack" || k === "BrowserBack") {
        if (this._view !== "channels" && !this.shadowRoot.querySelector("dialog[open]")) { ev.preventDefault(); this._view = "channels"; this._render(); }
        return;
      }
      if (!k.startsWith("Arrow")) return;
      const active = this.shadowRoot.activeElement;
      if (!active || active.tagName === "INPUT" || active.tagName === "VIDEO") return;
      const selector = this._view === "guide" ? ".prog-block, .g-ch" : ".tile, .chip, .btn";
      const items = [...this.shadowRoot.querySelectorAll(selector)].filter((el) => el.offsetParent !== null && !el.disabled);
      if (!items.includes(active)) return;
      const a = active.getBoundingClientRect();
      const ax = a.left + a.width / 2, ay = a.top + a.height / 2;
      let best = null, bestScore = Infinity;
      for (const el of items) {
        if (el === active) continue;
        const r = el.getBoundingClientRect();
        const x = r.left + r.width / 2, y = r.top + r.height / 2;
        const dx = x - ax, dy = y - ay;
        const ok = (k === "ArrowRight" && r.left >= a.right - 4) || (k === "ArrowLeft" && r.right <= a.left + 4)
          || (k === "ArrowDown" && r.top >= a.bottom - 4) || (k === "ArrowUp" && r.bottom <= a.top + 4);
        if (!ok) continue;
        const along = k === "ArrowLeft" || k === "ArrowRight" ? Math.abs(dx) : Math.abs(dy);
        const across = k === "ArrowLeft" || k === "ArrowRight" ? Math.abs(dy) : Math.abs(dx);
        const score = along + across * 2.5;
        if (score < bestScore) { bestScore = score; best = el; }
      }
      if (best) { ev.preventDefault(); best.focus(); best.scrollIntoView({ block: "nearest", inline: "nearest" }); }
    }

    /* ---- the guide ---- */
    async _loadGuide() {
      const list = this._channels().slice(0, 120);
      const now = Math.floor(Date.now() / 1000);
      const start = now - (now % 1800) - 1800;
      const end = start + 12 * 3600;
      this._guideWindow = { start, end };
      const byEntry = {};
      list.forEach((c) => { (byEntry[c.entry_id] = byEntry[c.entry_id] || []).push(c.key); });
      const out = {};
      await Promise.all(Object.entries(byEntry).map(async ([entry, keys]) => {
        try {
          const r = await this._hass.callWS({ type: "iptv_player/guide", entry_id: entry, keys, start, end });
          Object.entries(r.programmes || {}).forEach(([k, v]) => { out[`${entry}:${k}`] = v; });
        } catch (e) { /* that source is not loaded */ }
      }));
      this._guideData = out;
      if (this._view === "guide") this._renderGuide();
    }

    _renderGuide() {
      const body = this.shadowRoot.querySelector(".body");
      const list = this._channels().slice(0, 120);
      if (!list.length) { body.innerHTML = `<div class="msg">${esc(this._t("noChannels"))}</div>`; return; }
      const w = this._guideWindow;
      if (!w) { body.innerHTML = `<div class="msg">${esc(this._t("loading"))}</div>`; return; }
      const width = ((w.end - w.start) / 60) * PPM;
      const now = Date.now() / 1000;
      const marks = [];
      for (let t = w.start; t < w.end; t += 1800) marks.push(`<span style="left:${((t - w.start) / 60) * PPM}px">${esc(this._time(t))}</span>`);
      const rows = list.map((c) => {
        const progs = this._guideData[c.uid] || [];
        const blocks = progs.map((p) => {
          const left = Math.max(0, ((p.start - w.start) / 60) * PPM);
          const right = Math.min(width, ((p.stop - w.start) / 60) * PPM);
          if (right - left < 6) return "";
          const live = p.start <= now && now < p.stop;
          return `<button class="prog-block${live ? " live" : ""}" style="left:${left + 1}px;width:${right - left - 3}px" data-uid="${esc(c.uid)}" data-start="${p.start}" aria-label="${esc(c.name)}: ${esc(p.title)}, ${esc(this._time(p.start))}"><b>${esc(p.title)}</b><small>${esc(this._time(p.start))}</small></button>`;
        }).join("");
        return `<div class="g-row"><button class="g-ch" data-uid="${esc(c.uid)}">${this._logo(c)}<span>${esc(c.name)}</span></button><div class="g-progs" style="width:${width}px">${blocks}</div></div>`;
      }).join("");
      const scroller = body.querySelector(".guide");
      const keep = scroller ? { left: scroller.scrollLeft, top: scroller.scrollTop } : null;
      body.innerHTML = `<div class="guide"><div class="g-inner" style="width:${width + 170}px">
        <div class="g-head"><div class="g-corner"></div><div class="g-times" style="width:${width}px">${marks.join("")}</div></div>
        ${rows}<div class="g-now"></div></div></div>`;
      const g = body.querySelector(".guide");
      if (keep) { g.scrollLeft = keep.left; g.scrollTop = keep.top; } else g.scrollLeft = Math.max(0, ((now - w.start) / 60) * PPM - 60);
      this._placeNowLine();
    }

    _placeNowLine() {
      const line = this.shadowRoot.querySelector(".g-now");
      if (!line || !this._guideWindow) return;
      line.style.left = `${170 + ((Date.now() / 1000 - this._guideWindow.start) / 60) * PPM}px`;
    }

    async _programme(uid, start) {
      const c = this._byUid(uid);
      if (!c) return;
      let p = (this._guideData[uid] || []).find((x) => x.start === start);
      try {
        const r = await this._hass.callWS({ type: "iptv_player/guide", entry_id: c.entry_id, keys: [c.key], start, end: start + 60, details: true });
        p = ((r.programmes || {})[c.key] || []).find((x) => x.start === start) || p;
      } catch (e) { /* keep what the grid has */ }
      if (!p) return;
      const now = Date.now() / 1000;
      const live = p.start <= now && now < p.stop;
      const d = document.createElement("dialog");
      d.className = "sheet";
      d.innerHTML = `<div class="sheet-body"><h2>${esc(p.title)}</h2>
        <div class="when">${esc(c.name)} · ${esc(this._time(p.start))}–${esc(this._time(p.stop))}${p.sub ? ` · ${esc(p.sub)}` : ""}${p.category ? ` · ${esc(p.category)}` : ""}</div>
        ${p.desc ? `<p>${esc(p.desc)}</p>` : ""}
        <div class="sheet-actions">${live ? `<button class="btn on" data-watch="1">${ICON.play}${esc(this._t("watch"))}</button>` : ""}<button class="btn" data-close="1">${esc(this._t("close"))}</button></div></div>`;
      d.addEventListener("click", (ev) => {
        if (ev.target === d || ev.target.closest("[data-close]")) d.close();
        if (ev.target.closest("[data-watch]")) { d.close(); this._play(uid); }
      });
      d.addEventListener("close", () => d.remove());
      this.shadowRoot.appendChild(d);
      d.showModal();
      const first = d.querySelector("[data-watch], [data-close]");
      if (first) first.focus();
    }

    /* ---- Manage channels (admins) ---- */
    async _loadCatalog(reset) {
      const entries = (this._data && this._data.entries) || [];
      if (!entries.length) return;
      const m = this._manage;
      if (!m.entry || !entries.some((e) => e.entry_id === m.entry)) m.entry = entries[0].entry_id;
      if (reset) { m.channels = {}; m.search = null; }
      try {
        m.groups = await this._hass.callWS({ type: "iptv_player/catalog", entry_id: m.entry });
        for (const gid of m.open) m.channels[gid] = (await this._hass.callWS({ type: "iptv_player/catalog", entry_id: m.entry, group: gid })).channels;
        if (m.query.length >= 2) m.search = (await this._hass.callWS({ type: "iptv_player/catalog", entry_id: m.entry, query: m.query })).channels;
      } catch (e) {
        m.groups = { error: (e && e.message) || String(e) };
      }
      if (this._view === "manage") this._renderManage();
    }

    _renderManage() {
      const body = this.shadowRoot.querySelector(".body");
      const m = this._manage;
      const entries = (this._data && this._data.entries) || [];
      const cat = m.groups;
      if (!cat) { body.innerHTML = `<div class="msg">${esc(this._t("loading"))}</div>`; return; }
      if (cat.error) { body.innerHTML = `<div class="msg">${esc(cat.error)}</div>`; return; }
      const keepFocus = this.shadowRoot.activeElement;
      const focusKey = keepFocus && keepFocus.dataset ? keepFocus.dataset.focus : null;
      const q = m.query.toLowerCase();
      const facts = [];
      const shownAll = cat.groups.reduce((n, g) => n + g.shown, 0);
      facts.push(esc(this._t("shownOf", shownAll, cat.channels_total)));
      if (cat.account && cat.account.exp_date) facts.push(esc(this._t("expires", this._date(Number(cat.account.exp_date)))));
      if (cat.account) facts.push(esc(this._t("connections", cat.account.active_cons, cat.account.max_connections)));
      if (cat.catalog_at) facts.push(esc(this._t("listRead", `${this._date(cat.catalog_at)} ${this._time(cat.catalog_at)}`)));
      if (cat.skipped) facts.push(esc(this._t("skipped", cat.skipped)));
      if (cat.guide) facts.push(esc(this._t("matched", cat.guide.matched, cat.guide.shown)));
      const sources = (cat.guide && cat.guide.sources) || [];
      const groups = cat.groups.filter((g) => !q || g.name.toLowerCase().includes(q));
      const rows = groups.map((g, i) => {
        const open = m.open.has(g.id);
        const chans = open ? (m.channels[g.id] || null) : null;
        return `<div class="mrow group">
            <label><input type="checkbox" data-group="${esc(g.id)}" data-focus="g:${esc(g.id)}"${g.on ? " checked" : ""}><span>${esc(g.name)}</span></label>
            <span class="count">${esc(this._t("shownOf", g.shown, g.total))}</span>
            <button class="ibtn" data-gup="${esc(g.id)}" data-focus="gu:${esc(g.id)}" aria-label="${esc(this._t("moveUp"))}: ${esc(g.name)}"${i === 0 || q ? " disabled" : ""}>▲</button>
            <button class="ibtn" data-gdown="${esc(g.id)}" data-focus="gd:${esc(g.id)}" aria-label="${esc(this._t("moveDown"))}: ${esc(g.name)}"${i === groups.length - 1 || q ? " disabled" : ""}>▼</button>
            <button class="ibtn" data-gopen="${esc(g.id)}" data-focus="go:${esc(g.id)}" aria-expanded="${open}">${esc(open ? this._t("hide") : this._t("open"))}</button>
          </div>${open ? (chans ? chans.map((c, j) => this._manageChannel(c, j, chans.length, true)).join("") : `<div class="msg">${esc(this._t("loading"))}</div>`) : ""}`;
      }).join("");
      const found = m.search && q.length >= 2
        ? `<div class="mrow group"><span>${esc(this._t("search"))}: “${esc(m.query)}”</span></div>${m.search.length ? m.search.map((c, j) => this._manageChannel(c, j, m.search.length, false)).join("") : `<div class="msg">${esc(this._t("noMatch"))}</div>`}`
        : "";
      body.innerHTML = `<div class="manage">
        ${entries.length > 1 ? `<div class="tabs">${entries.map((e) => `<button class="chip${e.entry_id === m.entry ? " on" : ""}" data-entry="${esc(e.entry_id)}">${esc(e.title)}</button>`).join("")}</div>` : ""}
        <div class="m-top"><input type="search" placeholder="${esc(this._t("search"))}" aria-label="${esc(this._t("search"))}" value="${esc(m.query)}" data-focus="search"></div>
        <div class="m-facts">${facts.join(" · ")}<br>${esc(this._t("sources"))}: ${sources.map((s) => `${esc(s.label)} (${s.error ? `<span class="err">${esc(s.error)}</span>` : esc(this._t("channelsInGuide", s.channels))})`).join(", ") || "-"}</div>
        ${found}${rows}</div>`;
      const search = body.querySelector("input[type=search]");
      search.addEventListener("input", () => {
        m.query = search.value;
        clearTimeout(this._searchTimer);
        this._searchTimer = setTimeout(async () => {
          m.search = m.query.length >= 2 ? (await this._hass.callWS({ type: "iptv_player/catalog", entry_id: m.entry, query: m.query }).catch(() => ({ channels: [] }))).channels : null;
          this._renderManage();
        }, 350);
      });
      body.querySelectorAll("input[type=checkbox]").forEach((box) => box.addEventListener("change", () => this._toggle(box)));
      body.querySelectorAll("input[data-rename]").forEach((inp) => {
        inp.addEventListener("keydown", (ev) => { if (ev.key === "Enter") { ev.preventDefault(); inp.blur(); } if (ev.key === "Escape") { m.renameFor = null; this._renderManage(); } });
        inp.addEventListener("change", () => { m.renameFor = null; this._select([{ channel: inp.dataset.rename, name: inp.value }]); });
      });
      body.querySelectorAll("input[data-gsearch]").forEach((inp) => {
        inp.addEventListener("input", () => {
          clearTimeout(this._gsTimer);
          this._gsTimer = setTimeout(async () => {
            const r = await this._hass.callWS({ type: "iptv_player/guide_search", entry_id: m.entry, query: inp.value }).catch(() => ({ results: [] }));
            const box = inp.parentElement.querySelector(".gresults");
            box.innerHTML = (r.results || []).map((x) => `<button class="ibtn" data-gpick="${esc(inp.dataset.gsearch)}" data-gval="${esc(`${x.source}|${x.id}`)}">${esc(x.name)} · ${esc(x.id)} · ${esc(x.source)}</button>`).join("") || `<span class="count">${esc(this._t("noMatch"))}</span>`;
          }, 300);
        });
      });
      if (focusKey) { const el = body.querySelector(`[data-focus="${CSS.escape(focusKey)}"]`); if (el) el.focus({ preventScroll: true }); }
      const gs = body.querySelector("input[data-gsearch]");
      if (gs && m.guideFor && focusKey !== "search") gs.focus();
      const rn = body.querySelector("input[data-rename]");
      if (rn && m.renameFor) rn.focus();
    }

    _manageChannel(c, j, count, orderable) {
      const m = this._manage;
      const g = c.guide;
      const guideText = g ? `${g.id} · ${g.source} · ${this._t(`how_${g.how}`)}` : this._t("guideNone");
      const renaming = m.renameFor === c.key;
      const picking = m.guideFor === c.key;
      return `<div class="mrow channel">
          <label><input type="checkbox" data-channel="${esc(c.key)}" data-focus="c:${esc(c.key)}"${c.on ? " checked" : ""}>${c.logo ? this._logo({ name: c.tidy, logo: c.logo }) : ""}<span>${esc(c.display || c.tidy)}${c.display ? ` <span class="count">(${esc(c.name)})</span>` : ""}</span></label>
          ${c.own != null ? `<button class="ibtn" data-follow="${esc(c.key)}" data-focus="f:${esc(c.key)}" title="${esc(this._t("followGroup"))}">↺ ${esc(this._t("followGroup"))}</button>` : ""}
          <button class="ibtn" data-preview="${esc(c.key)}" data-focus="p:${esc(c.key)}">${esc(this._t("preview"))}</button>
          <button class="ibtn" data-rename-open="${esc(c.key)}" data-focus="r:${esc(c.key)}">${esc(this._t("rename"))}</button>
          ${orderable ? `<button class="ibtn" data-cup="${esc(c.key)}" data-group-of="${esc(c.group)}" data-focus="cu:${esc(c.key)}" aria-label="${esc(this._t("moveUp"))}"${j === 0 ? " disabled" : ""}>▲</button>
          <button class="ibtn" data-cdown="${esc(c.key)}" data-group-of="${esc(c.group)}" data-focus="cd:${esc(c.key)}" aria-label="${esc(this._t("moveDown"))}"${j === count - 1 ? " disabled" : ""}>▼</button>` : ""}
          <div class="gline">${esc(this._t("guide"))}: ${esc(guideText)} <button class="ibtn" data-guide-open="${esc(c.key)}" data-focus="gg:${esc(c.key)}">${esc(this._t("guideChange"))}</button>${c.guide_manual ? `<button class="ibtn" data-gauto="${esc(c.key)}">${esc(this._t("guideAuto"))}</button>` : ""}</div>
          ${renaming ? `<div class="gsearch"><input type="text" data-rename="${esc(c.key)}" value="${esc(c.display)}" placeholder="${esc(c.tidy)}" aria-label="${esc(this._t("rename"))}"></div>` : ""}
          ${picking ? `<div class="gsearch"><input type="text" data-gsearch="${esc(c.key)}" placeholder="${esc(this._t("guideSearch"))}" aria-label="${esc(this._t("guideSearch"))}"><div class="gresults"></div></div>` : ""}
        </div>`;
    }

    _toggle(box) {
      if (box.dataset.group) this._select([{ group: box.dataset.group, on: box.checked }]);
      else if (box.dataset.channel) this._select([{ channel: box.dataset.channel, on: box.checked }]);
    }

    async _select(changes, extra) {
      const m = this._manage;
      try {
        await this._hass.callWS({ type: "iptv_player/select", entry_id: m.entry, changes, ...(extra || {}) });
        this._status(this._t("saved"));
      } catch (e) {
        this._status(String((e && e.message) || e), true);
      }
      await this._loadCatalog(false);
      this._load();
    }

    _manageClick(ev) {
      const t = ev.target.closest("button");
      if (!t) return;
      const m = this._manage;
      const cat = m.groups;
      if (t.dataset.entry) { m.entry = t.dataset.entry; m.open.clear(); m.query = ""; this._loadCatalog(true); return; }
      if (t.dataset.gopen) {
        const gid = t.dataset.gopen;
        if (m.open.has(gid)) m.open.delete(gid); else m.open.add(gid);
        this._renderManage();
        if (m.open.has(gid) && !m.channels[gid]) this._loadCatalog(false);
        return;
      }
      if (t.dataset.gup || t.dataset.gdown) {
        const order = cat.groups.map((g) => g.id);
        const id = t.dataset.gup || t.dataset.gdown;
        const i = order.indexOf(id), j = i + (t.dataset.gup ? -1 : 1);
        if (i < 0 || j < 0 || j >= order.length) return;
        [order[i], order[j]] = [order[j], order[i]];
        this._select([], { group_order: order });
        return;
      }
      if (t.dataset.cup || t.dataset.cdown) {
        const gid = t.dataset.groupOf;
        const keys = (m.channels[gid] || []).map((c) => c.key);
        const id = t.dataset.cup || t.dataset.cdown;
        const i = keys.indexOf(id), j = i + (t.dataset.cup ? -1 : 1);
        if (i < 0 || j < 0 || j >= keys.length) return;
        [keys[i], keys[j]] = [keys[j], keys[i]];
        this._select([{ order: keys }]);
        return;
      }
      if (t.dataset.follow) { this._select([{ channel: t.dataset.follow, on: null }]); return; }
      if (t.dataset.gauto) { this._select([{ channel: t.dataset.gauto, guide: null }]); return; }
      if (t.dataset.gpick) { m.guideFor = null; this._select([{ channel: t.dataset.gpick, guide: t.dataset.gval }]); return; }
      if (t.dataset.guideOpen) { m.guideFor = m.guideFor === t.dataset.guideOpen ? null : t.dataset.guideOpen; m.renameFor = null; this._renderManage(); return; }
      if (t.dataset.renameOpen) { m.renameFor = m.renameFor === t.dataset.renameOpen ? null : t.dataset.renameOpen; m.guideFor = null; this._renderManage(); return; }
      if (t.dataset.preview) {
        const key = t.dataset.preview;
        const all = [...Object.values(m.channels).flat(), ...(m.search || [])];
        const c = all.find((x) => x.key === key);
        const uid = `${m.entry}:${key}`;
        this._play(uid, { uid, entry_id: m.entry, key, name: (c && (c.display || c.tidy)) || key });
        this.shadowRoot.querySelector(".stage").scrollIntoView({ block: "nearest" });
      }
    }
  }

  /* Home Assistant's frontend replaces the custom element registry's methods as it starts (its scoped-registry
   * polyfill keeps its own table), so an element defined before that point is reported as not existing afterwards.
   * This file is imported by the page alongside the frontend itself, so it can run first: register once the frontend's
   * root element is known, which is immediate when the file arrives as a dashboard resource. */
  function whenFrontendReady(fn) {
    const ready = () => !!customElements.get("home-assistant");
    if (ready()) { fn(); return; }
    let tries = 0;
    const timer = setInterval(() => { if (ready() || ++tries > 600) { clearInterval(timer); fn(); } }, 50);
  }
  whenFrontendReady(() => {
    if (!customElements.get("iptv-player-card")) customElements.define("iptv-player-card", IptvPlayerCard);
    window.customCards = window.customCards || [];
    if (!window.customCards.some((c) => c.type === "iptv-player-card")) {
      window.customCards.push({ type: "iptv-player-card", name: "IPTV Player", description: "Live TV with your chosen channels, now and next, a guide and Play on TV.", preview: false });
    }
  });
})();
