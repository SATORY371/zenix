"""Resource downloader: download images from Unsplash or Pixabay.

Environment variables:
- UNSPLASH_ACCESS_KEY
- PIXABAY_API_KEY

Returns relative local path under `images/` on success, or None on failure.
"""
from pathlib import Path
import os
import requests
import logging
from typing import Optional

log = logging.getLogger("zenix.resource_downloader")

ROOT_DIR = Path(__file__).resolve().parent.parent
IMAGES_DIR = ROOT_DIR / "images"
IMAGES_DIR.mkdir(parents=True, exist_ok=True)

UNSPLASH_SEARCH = "https://api.unsplash.com/search/photos"
PIXABAY_SEARCH = "https://pixabay.com/api/"

UNSPLASH_KEY = os.getenv("UNSPLASH_ACCESS_KEY", "")
PIXABAY_KEY = os.getenv("PIXABAY_API_KEY", "")


def _download_url_to_file(url: str, dest: Path) -> bool:
    try:
        resp = requests.get(url, timeout=30, stream=True, headers={"User-Agent": "ZENIX/2.0"})
        if resp.status_code != 200:
            log.warning("Image download failed status=%s url=%s", resp.status_code, url)
            return False
        with open(dest, "wb") as f:
            for chunk in resp.iter_content(1024 * 16):
                if chunk:
                    f.write(chunk)
        return True
    except Exception as exc:
        log.exception("Error downloading image: %s", exc)
        return False


def download_from_unsplash(keywords: str) -> Optional[str]:
    if not UNSPLASH_KEY:
        return None
    params = {"query": keywords, "per_page": 1}
    headers = {"Authorization": f"Client-ID {UNSPLASH_KEY}", "Accept-Version": "v1"}
    try:
        r = requests.get(UNSPLASH_SEARCH, params=params, headers=headers, timeout=15)
        if r.status_code != 200:
            log.warning("Unsplash search failed: %s", r.status_code)
            return None
        data = r.json()
        results = data.get("results") or []
        if not results:
            return None
        photo = results[0]
        # Prefer full or regular
        url = photo.get("urls", {}).get("regular") or photo.get("urls", {}).get("full")
        return url
    except Exception as exc:
        log.exception("Unsplash error: %s", exc)
        return None


def download_from_pixabay(keywords: str) -> Optional[str]:
    if not PIXABAY_KEY:
        return None
    params = {"key": PIXABAY_KEY, "q": keywords, "image_type": "photo", "per_page": 3}
    try:
        r = requests.get(PIXABAY_SEARCH, params=params, timeout=15, headers={"User-Agent": "ZENIX/2.0"})
        if r.status_code != 200:
            log.warning("Pixabay search failed: %s", r.status_code)
            return None
        data = r.json()
        hits = data.get("hits") or []
        if not hits:
            return None
        hit = hits[0]
        url = hit.get("largeImageURL") or hit.get("webformatURL") or hit.get("previewURL")
        return url
    except Exception as exc:
        log.exception("Pixabay error: %s", exc)
        return None


def download_image(keywords: str, output_filename: str) -> Optional[str]:
    """Attempt to download an image for keywords and save as output_filename under images/.

    Returns relative path like "images/filename.jpg" or None on failure.
    """
    safe_name = Path(output_filename).name
    dest = IMAGES_DIR / safe_name

    # Try Unsplash
    url = download_from_unsplash(keywords)
    if url:
        if _download_url_to_file(url, dest):
            return str(Path("images") / safe_name)

    # Try Pixabay
    url = download_from_pixabay(keywords)
    if url:
        if _download_url_to_file(url, dest):
            return str(Path("images") / safe_name)

    # As fallback, try an unauthenticated Unsplash HTML scrape small image (not recommended)
    log.warning("No image found for keywords: %s", keywords)
    return None
