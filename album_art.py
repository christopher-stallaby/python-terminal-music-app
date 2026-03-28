"""
album_art.py - Privacy-Respecting Album Art Fetcher

Responsibility:
 Search for album art using iTunes Search API (no auth required)
 Return image bytes for in-memory display only
 Cache results in memory to avoid redundant requests

Privacy guarantees:
 - No user data sent (only album/artist names)
 - No persistent storage (RAM cache only)
 - No tracking or analytics
"""

import httpx
from typing import Optional
from functools import lru_cache
from library import Album

# In-memory cache: album_key -> (image_bytes, expiry_time)
# Using a simple dict with size limit instead of external cache
_album_art_cache: dict[str, bytes] = {}
_MAX_CACHE_SIZE = 50  # Keep last 50 album arts in memory


async def fetch_album_art(artist: str, album: str) -> Optional[bytes]:
    """
    Fetch album art from iTunes Search API.

    Args:
        artist: Artist name
        album: Album name

    Returns:
        JPEG image bytes, or None if not found

    Privacy note:
        Only sends artist and album name to iTunes. No user
        identifiers, IP logging is standard CDN behavior only.
    """
    # Check cache first
    cache_key = f"{artist.lower()}||{album.lower()}"
    if cache_key in _album_art_cache:
        return _album_art_cache[cache_key]

    try:
        # iTunes Search API - no authentication required
        query = f"{artist} {album}"
        url = f"https://itunes.apple.com/search?term={query}&entity=album&limit=1"

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url)
            response.raise_for_status()

            data = response.json()

            if data.get("resultCount", 0) == 0:
                return None

            # Get the largest available image (1000x1000)
            artwork_url = data["results"][0].get("artworkUrl100", "")
            if not artwork_url:
                return None

            # Replace 100x100 with 1000x1000 for higher quality
            artwork_url = artwork_url.replace("100x100", "1000x1000")

            # Fetch the image
            img_response = await client.get(artwork_url)
            img_response.raise_for_status()
            image_bytes = img_response.content

            # Cache the result (with eviction if cache is full)
            if len(_album_art_cache) >= _MAX_CACHE_SIZE:
                # Remove oldest entry (simple FIFO)
                _album_art_cache.pop(next(iter(_album_art_cache)))

            _album_art_cache[cache_key] = image_bytes
            return image_bytes

    except Exception as e:
        print(f" ⚠️  Failed to fetch album art: {e}")
        return None


def clear_album_art_cache() -> None:
    """Clear the in-memory album art cache."""
    _album_art_cache.clear()
