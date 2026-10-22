"""Server-side image fetching for ``display.draw_url``.

Unlike the ESP32 boards, the gadget backend has real memory, so HTTPS and
private expiring links work. The image is fetched here, verified to be an
image a browser can show, and handed to the screen as bytes — the browser
never fetches the URL itself.
"""

from __future__ import annotations

import io
import urllib.request

MAX_IMAGE_BYTES = 16 * 1024 * 1024
MAX_AUDIO_BYTES = 32 * 1024 * 1024
_TIMEOUT_S = 20
_UA = "muse-gadget-web/0.1 (+https://github.com/koneho-ai/muse-gadget-web)"


def fetch_image(url: str) -> tuple[bytes, str]:
    """Return ``(bytes, mime)`` for an image URL. Raises ValueError/OSError."""
    if not (url.startswith("https://") or url.startswith("http://")):
        raise ValueError("url must be http:// or https://")
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:
        data = resp.read(MAX_IMAGE_BYTES + 1)
    if len(data) > MAX_IMAGE_BYTES:
        raise ValueError("image is larger than 16 MiB")
    # Verify with Pillow; normalise the mime from the actual format so a
    # mislabelled Content-Type cannot break the browser side.
    from PIL import Image

    with Image.open(io.BytesIO(data)) as img:
        fmt = (img.format or "").upper()
    mime = {
        "JPEG": "image/jpeg",
        "PNG": "image/png",
        "GIF": "image/gif",
        "WEBP": "image/webp",
        "BMP": "image/bmp",
    }.get(fmt)
    if mime is None:
        raise ValueError(f"unsupported image format: {fmt or 'unknown'}")
    return data, mime


_AUDIO_MIMES = {
    "audio/mpeg", "audio/mp3", "audio/mp4", "audio/x-m4a", "audio/aac",
    "audio/wav", "audio/x-wav", "audio/wave", "audio/ogg", "audio/webm",
}


def _sniff_audio(data: bytes) -> str | None:
    if data.startswith(b"ID3") or data[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"):
        return "audio/mpeg"
    if data.startswith(b"RIFF") and data[8:12] == b"WAVE":
        return "audio/wav"
    if data.startswith(b"OggS"):
        return "audio/ogg"
    if data.startswith(b"\x1aE\xdf\xa3"):
        return "audio/webm"
    if data[4:8] == b"ftyp":
        return "audio/mp4"
    return None


def fetch_audio(url: str) -> tuple[bytes, str]:
    """Return ``(bytes, mime)`` for an audio URL. Raises ValueError/OSError."""
    if not (url.startswith("https://") or url.startswith("http://")):
        raise ValueError("url must be http:// or https://")
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:
        declared = (resp.headers.get_content_type() or "").lower()
        data = resp.read(MAX_AUDIO_BYTES + 1)
    if len(data) > MAX_AUDIO_BYTES:
        raise ValueError("audio is larger than 32 MiB")
    mime = declared if declared in _AUDIO_MIMES else _sniff_audio(data)
    if mime is None:
        raise ValueError(f"unsupported audio type: {declared or 'unknown'}")
    return data, mime
