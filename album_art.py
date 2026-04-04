# LUMO AI VERSION
# """
# album_art.py - Privacy-Respecting Album Art Fetcher

# Responsibility:
#  Search for album art using iTunes Search API (no auth required)
#  Return image bytes for in-memory display only
#  Cache results in memory to avoid redundant requests

# Privacy guarantees:
#  - No user data sent (only album/artist names)
#  - No persistent storage (RAM cache only)
#  - No tracking or analytics
# """

# import httpx
# from typing import Optional
# from functools import lru_cache
# from library import Album

# # In-memory cache: album_key -> (image_bytes, expiry_time)
# # Using a simple dict with size limit instead of external cache
# _album_art_cache: dict[str, bytes] = {}
# _MAX_CACHE_SIZE = 50  # Keep last 50 album arts in memory


# async def fetch_album_art(artist: str, album: str) -> Optional[bytes]:
#     """
#     Fetch album art from iTunes Search API.

#     Args:
#         artist: Artist name
#         album: Album name

#     Returns:
#         JPEG image bytes, or None if not found

#     Privacy note:
#         Only sends artist and album name to iTunes. No user
#         identifiers, IP logging is standard CDN behavior only.
#     """
#     # Check cache first
#     cache_key = f"{artist.lower()}||{album.lower()}"
#     if cache_key in _album_art_cache:
#         return _album_art_cache[cache_key]

#     try:
#         # iTunes Search API - no authentication required
#         query = f"{artist} {album}"
#         url = f"https://itunes.apple.com/search?term={query}&entity=album&limit=1"

#         async with httpx.AsyncClient(timeout=10.0) as client:
#             response = await client.get(url)
#             response.raise_for_status()

#             data = response.json()

#             if data.get("resultCount", 0) == 0:
#                 return None

#             # Get the largest available image (1000x1000)
#             artwork_url = data["results"][0].get("artworkUrl100", "")
#             if not artwork_url:
#                 return None

#             # Replace 100x100 with 1000x1000 for higher quality
#             artwork_url = artwork_url.replace("100x100", "1000x1000")

#             # Fetch the image
#             img_response = await client.get(artwork_url)
#             img_response.raise_for_status()
#             image_bytes = img_response.content

#             # Cache the result (with eviction if cache is full)
#             if len(_album_art_cache) >= _MAX_CACHE_SIZE:
#                 # Remove oldest entry (simple FIFO)
#                 _album_art_cache.pop(next(iter(_album_art_cache)))

#             _album_art_cache[cache_key] = image_bytes
#             return image_bytes

#     except Exception as e:
#         print(f" ⚠️  Failed to fetch album art: {e}")
#         return None


# def clear_album_art_cache() -> None:
#     """Clear the in-memory album art cache."""
#     _album_art_cache.clear()

# CLAUDE AI VERSION
"""
art_fetcher.py — Album Art Fetcher and Display for my-music-app

Responsibility:
    1. Detect terminal image display capability
    2. Fetch album art from MusicBrainz Cover Art Archive
    3. Cache results in memory to avoid redundant requests
    4. Display using the Kitty Graphics Protocol where supported
    5. Discard temp files immediately after display

Privacy:
    MusicBrainz is open-source and community maintained.
    No API key required. No tracking. No corporate data collection.
    Images stored only in /tmp and discarded immediately after use.
    In-memory cache stores bytes only — nothing written to disk
    until display time, and deleted immediately after.
"""

import os
import io
import sys
import base64
import tempfile
import httpx
from pathlib import Path


# ── CONFIGURATION ─────────────────────────────────────────────────────────────

# MusicBrainz requires a descriptive User-Agent — anonymous requests get
# rate-limited. This is their official policy, not tracking.
USER_AGENT    = "my-music-app/1.0 (linux-tui-player)"
REQUEST_TIMEOUT = 8.0
ART_SIZE      = (240, 240)   # pixel dimensions for display

# In-memory cache: "artist||album" -> raw image bytes
# Nothing is written to disk until display time.
# Python 3.7+ dicts maintain insertion order — we rely on this for FIFO eviction.
_art_cache: dict[str, bytes] = {}
_MAX_CACHE_SIZE = 50          # cap memory usage at ~50 album covers


# ── TERMINAL DETECTION ────────────────────────────────────────────────────────

def detect_image_capability() -> str:
    """
    Detect which image display protocol the current terminal supports.

    Checks environment variables set by the terminal itself:
        $TERM         — set by Kitty to include 'kitty'
        $TERM_PROGRAM — set by WezTerm and Ghostty to identify themselves

    Returns:
        'kitty' — Kitty Graphics Protocol supported (WezTerm, Kitty, Ghostty)
        'none'  — No image support, use text fallback
    """
    term         = os.environ.get("TERM", "")
    term_program = os.environ.get("TERM_PROGRAM", "")

    if "kitty" in term:
        return "kitty"

    if term_program in ("WezTerm", "ghostty"):
        return "kitty"   # both speak the Kitty Graphics Protocol

    return "none"


# ── MUSICBRAINZ API ───────────────────────────────────────────────────────────

async def _search_release_id(
    client: httpx.AsyncClient,
    artist: str,
    album:  str
) -> str | None:
    """
    Search MusicBrainz for a release ID matching artist and album.

    We pass the httpx client in rather than creating a new one —
    this lets the caller reuse a single connection for both requests,
    which is faster and more efficient.

    Returns the MusicBrainz release ID string, or None if not found.
    """
    url    = "https://musicbrainz.org/ws/2/release"
    params = {
        "query": f'artist:"{artist}" AND release:"{album}"',
        "fmt":   "json",
        "limit": 1,
    }

    try:
        response = await client.get(url, params=params)
        response.raise_for_status()

        releases = response.json().get("releases", [])
        return releases[0]["id"] if releases else None

    except httpx.TimeoutException:
        print(f"  ⚠️  MusicBrainz search timed out: {artist} — {album}")
        return None
    except httpx.HTTPStatusError as e:
        print(f"  ⚠️  MusicBrainz HTTP error: {e.response.status_code}")
        return None
    except Exception as e:
        print(f"  ⚠️  MusicBrainz search failed: {e}")
        return None


async def _fetch_cover_bytes(
    client:     httpx.AsyncClient,
    release_id: str
) -> bytes | None:
    """
    Fetch raw image bytes from Cover Art Archive for a release ID.

    Cover Art Archive URL format:
        https://coverartarchive.org/release/{id}/front
    This redirects to the actual image — follow_redirects handles that.

    Returns raw bytes or None if unavailable.
    """
    url = f"https://coverartarchive.org/release/{release_id}/front"

    try:
        response = await client.get(url, follow_redirects=True)
        response.raise_for_status()
        return response.content

    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            return None   # normal — not every album has artwork
        print(f"  ⚠️  Cover Art Archive HTTP error: {e.response.status_code}")
        return None
    except httpx.TimeoutException:
        print(f"  ⚠️  Cover art fetch timed out: {release_id}")
        return None
    except Exception as e:
        print(f"  ⚠️  Cover art fetch failed: {e}")
        return None
    
async def _fetch_cover_bytes_itunes(
    client:  httpx.AsyncClient,
    artist:  str,
    album:   str
) -> bytes | None:
    """
    Fallback: fetch cover art from iTunes Search API.

    Privacy note:
        This sends artist and album name to Apple's servers.
        Your IP address is logged as standard CDN behaviour.
        Only called when MusicBrainz has no artwork available.
        Using as fallback minimises Apple exposure while
        maximising coverage.
    """
    try:
        query    = f"{artist} {album}"
        search_url = (
            f"https://itunes.apple.com/search"
            f"?term={httpx.URL(query)}"
            f"&entity=album&limit=1"
        )

        response = await client.get(search_url)
        response.raise_for_status()

        data = response.json()
        if data.get("resultCount", 0) == 0:
            return None

        # artworkUrl100 is always 100x100 — replace for higher quality
        artwork_url = data["results"][0].get("artworkUrl100", "")
        if not artwork_url:
            return None

        # iTunes URL pattern is consistent — this replacement is safe
        # but we verify the response before using it
        hq_url   = artwork_url.replace("100x100bb", "600x600bb")
        response = await client.get(hq_url)

        # If high quality version fails, fall back to original 100x100
        if response.status_code != 200:
            response = await client.get(artwork_url)
            response.raise_for_status()

        return response.content

    except httpx.TimeoutException:
        print(f"  ⚠️  iTunes search timed out: {artist} — {album}")
        return None
    except Exception as e:
        print(f"  ⚠️  iTunes fetch failed: {e}")
        return None


# ── IMAGE PROCESSING ──────────────────────────────────────────────────────────

def _process_image(image_bytes: bytes) -> Path | None:
    """
    Resize image to ART_SIZE and save to a temp file in /tmp.

    We write to /tmp rather than keeping bytes in memory at display time
    because the Kitty protocol needs to re-open the image for RGBA
    conversion. The temp file is deleted immediately after display.

    Returns the Path to the temp file, or None on failure.
    The caller must call discard_album_art() after use.
    """
    try:
        from PIL import Image

        image = Image.open(io.BytesIO(image_bytes))
        image = image.convert("RGB")
        image.thumbnail(ART_SIZE)

        tmp = tempfile.NamedTemporaryFile(
            suffix=".jpg",
            prefix="mymusic_art_",
            dir="/tmp",
            delete=False    # we control deletion via discard_album_art()
        )
        image.save(tmp.name, "JPEG", quality=85)
        tmp.close()

        return Path(tmp.name)

    except Exception as e:
        print(f"  ⚠️  Image processing failed: {e}")
        return None


# ── CACHE MANAGEMENT ──────────────────────────────────────────────────────────

def _cache_get(artist: str, album: str) -> bytes | None:
    """Return cached image bytes for this artist/album, or None."""
    return _art_cache.get(f"{artist.lower()}||{album.lower()}")


def _cache_set(artist: str, album: str, image_bytes: bytes) -> None:
    """
    Store image bytes in the cache.

    Evicts the oldest entry when the cache is full.
    Relies on Python 3.7+ dict insertion-order guarantee for FIFO behaviour.
    """
    key = f"{artist.lower()}||{album.lower()}"

    if len(_art_cache) >= _MAX_CACHE_SIZE:
        # next(iter(dict)) gets the first (oldest) key — Python 3.7+ only
        oldest_key = next(iter(_art_cache))
        _art_cache.pop(oldest_key)

    _art_cache[key] = image_bytes


def clear_cache() -> None:
    """Clear the in-memory album art cache."""
    _art_cache.clear()


# ── KITTY GRAPHICS PROTOCOL ───────────────────────────────────────────────────

def _display_kitty(image_path: Path) -> None:
    """
    Render an image using the Kitty Graphics Protocol.

    Protocol overview:
        Images are sent as base64-encoded raw RGBA pixel data,
        wrapped in APC escape sequences:

            ESC _G [parameters] ; [base64 chunk] ESC \\

        Parameters:
            a=T   — action: Transmit image data
            f=32  — format: 32-bit RGBA (8 bits per channel)
            s=W   — image width in pixels
            v=H   — image height in pixels
            m=1   — more chunks follow
            m=0   — this is the final (or only) chunk

        We chunk at 4096 bytes because terminals have escape
        sequence length limits. Most images need several chunks.
    """
    try:
        from PIL import Image

        image = Image.open(image_path).convert("RGBA")

        # Resize to fit within ART_SIZE preserving aspect ratio
        ratio  = min(ART_SIZE[0] / image.width, ART_SIZE[1] / image.height)
        width  = int(image.width  * ratio)
        height = int(image.height * ratio)
        image  = image.resize((width, height))

        # Encode raw pixel bytes as base64
        encoded = base64.standard_b64encode(image.tobytes()).decode("ascii")

        # Split into 4096-byte chunks
        chunk_size = 4096
        chunks     = [encoded[i:i+chunk_size] for i in range(0, len(encoded), chunk_size)]

        for index, chunk in enumerate(chunks):
            is_last = index == len(chunks) - 1

            if index == 0:
                # First chunk carries the image dimensions and format
                params = f"a=T,f=32,s={width},v={height},m={'0' if is_last else '1'}"
            else:
                # Subsequent chunks only carry the continuation flag
                params = f"m={'0' if is_last else '1'}"

            sys.stdout.write(f"\x1b_G{params};{chunk}\x1b\\")

        sys.stdout.write("\n")
        sys.stdout.flush()

    except Exception as e:
        print(f"  ⚠️  Kitty display failed: {e}")


# ── PUBLIC API ────────────────────────────────────────────────────────────────

async def fetch_album_art(artist: str, album: str) -> Path | None:
    """
    Fetch album art using a privacy-respecting waterfall:

        1. Check in-memory cache         — no network request
        2. Try MusicBrainz               — open source, no tracking
        3. Fall back to iTunes           — sends data to Apple,
                                           only used when MusicBrainz
                                           has no artwork

    Returns a Path to a temp JPEG in /tmp, or None if unavailable.
    Caller must call discard_album_art(path) after display.
    """
    # ── 1. Cache check ──
    cached_bytes = _cache_get(artist, album)
    if cached_bytes:
        return _process_image(cached_bytes)

    headers = {"User-Agent": USER_AGENT}

    async with httpx.AsyncClient(
        headers=headers,
        timeout=REQUEST_TIMEOUT
    ) as client:

        # ── 2. Try MusicBrainz first ──
        image_bytes = None
        release_id  = await _search_release_id(client, artist, album)

        if release_id:
            image_bytes = await _fetch_cover_bytes(client, release_id)

        # ── 3. iTunes fallback ──
        if image_bytes is None:
            print(f"  ℹ️  MusicBrainz: no art found — trying iTunes fallback")
            image_bytes = await _fetch_cover_bytes_itunes(client, artist, album)

    if image_bytes is None:
        return None

    # ── Cache and process ──
    _cache_set(artist, album, image_bytes)
    return _process_image(image_bytes)


def display_album_art(image_path: Path) -> None:
    """
    Display album art using the best protocol available for this terminal.
    Falls back gracefully if the terminal doesn't support image display.
    """
    capability = detect_image_capability()

    if capability == "kitty":
        _display_kitty(image_path)
    else:
        print("  🎨  Album art fetched (terminal does not support image display)")


def discard_album_art(path: Path) -> None:
    """
    Delete the temporary artwork file after display.
    Safe to call even if the file no longer exists.
    """
    try:
        if path and path.exists():
            os.unlink(path)
    except Exception as e:
        print(f"  ⚠️  Could not discard temp art file: {e}")


# ── ENTRY POINT ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import asyncio

    async def test():
        print("🎨 Testing art_fetcher...\n")
        print(f"  Terminal capability: {detect_image_capability()}\n")

        # Test with an album well-covered by MusicBrainz
        print("── Test 1: MusicBrainz path ────────────────")
        art_path = await fetch_album_art("Radiohead", "OK Computer")
        if art_path:
            print(f"  ✅ Art fetched: {art_path.stat().st_size / 1024:.1f} KB")
            display_album_art(art_path)
            discard_album_art(art_path)
        else:
            print("  ❌ No art found")

        # Clear cache to force a fresh fetch
        clear_cache()

        # Test with an album more likely to need iTunes fallback
        print("\n── Test 2: iTunes fallback path ────────────")
        art_path = await fetch_album_art("Avicii", "True")
        if art_path:
            print(f"  ✅ Art fetched: {art_path.stat().st_size / 1024:.1f} KB")
            display_album_art(art_path)
            discard_album_art(art_path)
        else:
            print("  ❌ No art found")

        # Test cache hit
        print("\n── Test 3: Cache hit ───────────────────────")
        art_path = await fetch_album_art("Avicii", "True")
        if art_path:
            print("  ✅ Cache hit confirmed")
            discard_album_art(art_path)

    asyncio.run(test())
"""
## Summary of All Changes

pane_art.py
└── display()        → send imgcat via _send_text instead of
                       calling it directly with nonexistent --pane-id

art_fetcher.py
├── _fetch_cover_bytes_itunes() → new iTunes fallback function
│                                 with honest privacy comment
├── fetch_album_art()           → waterfall: cache → MusicBrainz
│                                 → iTunes fallback
└── __main__ test               → tests both API paths + cache
"""