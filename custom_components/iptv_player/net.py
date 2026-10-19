"""Reading a whole answer with a size limit. aiohttp's StreamReader.read(n) returns what has arrived so far, not n
bytes, so a big playlist read that way comes back cut short (Free-TV's 537 KB list gave 78 of its 1,848 channels on
the Green, 19 Oct 2026)."""
from __future__ import annotations

from typing import Any


class TooBig(ValueError):
    pass


async def read_capped(resp: Any, limit: int) -> bytes:
    """The whole body, or TooBig once it passes limit bytes."""
    parts: list[bytes] = []
    size = 0
    async for chunk in resp.content.iter_chunked(64 * 1024):
        size += len(chunk)
        if size > limit:
            raise TooBig(f"over {limit // (1024 * 1024) or 1} MB")
        parts.append(chunk)
    return b"".join(parts)
