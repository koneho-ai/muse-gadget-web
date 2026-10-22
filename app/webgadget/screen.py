"""The gadget's screen: shared state between the command executor and the
web server.

The Link executor runs commands on worker threads; the web server runs on
the asyncio loop. This class is the bridge: plain fields guarded by a lock,
plus a monotonically increasing ``version`` the web layer polls/pushes on.
Audio replies are handed over as short-lived blobs addressed by id.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field


@dataclass
class ScreenState:
    mode: str = "animation"          # "animation" | "image"
    link_state: str = "boot"         # boot | connecting | connected | unpaired | error
    title: str = ""                  # agent name, once known
    image: bytes | None = None
    image_mime: str = "image/jpeg"
    image_version: int = 0
    reply_text: str = ""             # latest assistant reply shown on the face
    status_text: str = ""            # transient activity line ("thinking", ...)
    volume: int = 80
    version: int = 0
    _lock: threading.RLock = field(default_factory=threading.RLock)  # RLock: snapshot() calls latest_audio_id()
    _audio: dict = field(default_factory=dict)   # id -> (bytes, mime, created)

    # -- executor side (any thread) ------------------------------------------

    def set_image(self, data: bytes, mime: str) -> None:
        with self._lock:
            self.image = data
            self.image_mime = mime
            self.mode = "image"
            self.image_version += 1
            self.version += 1

    def show_animation(self) -> None:
        with self._lock:
            self.mode = "animation"
            self.image = None
            self.image_version += 1
            self.version += 1

    def set_link_state(self, state: str) -> None:
        with self._lock:
            if self.link_state != state:
                self.link_state = state
                self.version += 1

    def set_reply(self, text: str, status: str = "") -> None:
        with self._lock:
            self.reply_text = text
            self.status_text = status
            self.version += 1

    def set_status(self, status: str) -> None:
        with self._lock:
            self.status_text = status
            self.version += 1

    def set_volume(self, volume: int) -> int:
        with self._lock:
            self.volume = max(0, min(100, int(volume)))
            self.version += 1
            return self.volume

    def put_audio(self, data: bytes, mime: str = "audio/mpeg") -> str:
        audio_id = uuid.uuid4().hex[:16]
        with self._lock:
            self._audio[audio_id] = (data, mime, time.time())
            # Keep at most the last few clips.
            while len(self._audio) > 4:
                oldest = min(self._audio, key=lambda k: self._audio[k][2])
                del self._audio[oldest]
            self.version += 1
        return audio_id

    # -- web side --------------------------------------------------------------

    def get_audio(self, audio_id: str) -> tuple[bytes, str] | None:
        with self._lock:
            item = self._audio.get(audio_id)
            return (item[0], item[1]) if item else None

    def latest_audio_id(self) -> str | None:
        with self._lock:
            if not self._audio:
                return None
            return max(self._audio, key=lambda k: self._audio[k][2])

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "mode": self.mode,
                "link_state": self.link_state,
                "title": self.title,
                "image_version": self.image_version,
                "reply_text": self.reply_text,
                "status_text": self.status_text,
                "volume": self.volume,
                "version": self.version,
                "audio_id": self.latest_audio_id(),
            }
