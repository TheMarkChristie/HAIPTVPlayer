"""Import the integration's pure modules (const, m3u, model, xmltv, hls) without Home Assistant installed.

The package's __init__ imports Home Assistant, so the package is registered by hand with its path and __init__ is
never run; the relative imports inside the modules then resolve as usual."""
import pathlib
import sys
import types

ROOT = pathlib.Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "iptv_player"

if "custom_components.iptv_player" not in sys.modules:
    top = types.ModuleType("custom_components")
    top.__path__ = [str(ROOT / "custom_components")]
    pkg = types.ModuleType("custom_components.iptv_player")
    pkg.__path__ = [str(COMPONENT)]
    sys.modules["custom_components"] = top
    sys.modules["custom_components.iptv_player"] = pkg

from custom_components.iptv_player import const, hls, m3u, model, xmltv  # noqa: E402,F401
