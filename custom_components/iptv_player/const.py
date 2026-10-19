"""Constants for IPTV Player. Nothing here imports Home Assistant, so the pure modules and their tests stay pure."""

DOMAIN = "iptv_player"
NAME = "IPTV Player"

# the card and the two player libraries, served by the integration from its www folder
URL_BASE = "/iptv_player"
CARD_FILE = "iptv-player-card.js"

# config entry data
CONF_KIND = "kind"                    # KIND_XTREAM | KIND_M3U
KIND_XTREAM = "xtream"
KIND_M3U = "m3u"
CONF_URL = "url"                      # Xtream: the panel address; M3U: the playlist address
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_NAME = "name"

# options
CONF_PROVIDER_GUIDE = "provider_guide"    # Xtream: read the provider's own xmltv.php
CONF_GUIDE_URLS = "guide_urls"            # more XMLTV addresses, one per line; matched by guide id, then by name
CONF_GUIDE_HOURS = "guide_hours"          # how far ahead the guide is kept
CONF_GUIDE_HOUR = "guide_hour"            # the local hour of the daily guide download
CONF_USER_AGENT = "user_agent"            # sent to the provider with every request
CONF_PLAYERS = "players"                  # media_player entities offered on Play on TV; empty: the house's Cast devices
CONF_OUTPUT = "output"                    # Xtream: m3u8 | ts

DEFAULT_GUIDE_HOURS = 36
DEFAULT_GUIDE_HOUR = 4
DEFAULT_USER_AGENT = "Mozilla/5.0"
DEFAULT_OUTPUT = "m3u8"
# epgshare01's free UK file fills the gaps in a provider's guide (Mark, 19 Oct 2026)
FREE_UK_GUIDE = "https://epgshare01.online/epgshare01/epg_ripper_UK1.xml.gz"

# how hard a provider is asked: requests one at a time and spaced, the account every 15 minutes, the channel list
# twice a day, the guide once a day
PROVIDER_GAP_SECONDS = 1.0
PROVIDER_TIMEOUT_SECONDS = 60
ACCOUNT_MINUTES = 15
CATALOG_HOURS = 12
GUIDE_MAX_AGE_HOURS = 20
GUIDE_MAX_DOWNLOAD_MB = 60                # epgshare01's ALL_SOURCES (201 MB) is refused, not downloaded
GUIDE_MAX_HEADER_URLS = 5                 # a playlist naming more guides than this is not followed (Free-TV names 100)
GUIDE_PAST_HOURS = 3
GUIDE_DESC_CHARS = 600

# the stream relay: /api/iptv_player/hls/<token>/... (no sign-in: the token is the key, as Home Assistant's own camera
# streams, so a Cast device can open it). A session ends 45 s after its last request or after 12 hours.
RELAY_URL = "/api/iptv_player/hls"
SESSION_IDLE_SECONDS = 45
SESSION_MAX_HOURS = 12
SESSIONS_MAX = 8
PLAYLIST_MAX_BYTES = 2 * 1024 * 1024
SEGMENT_CHUNK = 64 * 1024

# the logo proxy for http logos: /api/iptv_player/logo/<entry>/<key>, signed per websocket answer
LOGO_URL = "/api/iptv_player/logo"
SIGNED_URL_HOURS = 12

# storage
STORE_VERSION = 1

# events and websocket
EVENT_UPDATED = f"{DOMAIN}_updated"
WS_CHANNELS = f"{DOMAIN}/channels"
WS_GUIDE = f"{DOMAIN}/guide"
WS_CATALOG = f"{DOMAIN}/catalog"          # admins only
WS_SELECT = f"{DOMAIN}/select"            # admins only
WS_STREAM = f"{DOMAIN}/stream"
WS_RELEASE = f"{DOMAIN}/release"
WS_SUBSCRIBE = f"{DOMAIN}/subscribe"

# services
SERVICE_PLAY = "play"
SERVICE_REFRESH = "refresh"
ATTR_CHANNEL = "channel"
ATTR_PLAYER = "player"
ATTR_ENTRY_ID = "entry_id"
ATTR_GUIDE = "guide"

# playback kinds
PLAY_HLS = "hls"
PLAY_RAW = "raw"
