"""The commands the browser gadget advertises to Muse.

Mirrors the ESP32 boards' surface — ``device.health``,
``display.draw_url``, ``display.show_animation``, ``voice.configure`` —
with the browser page as the display and speaker. ``run`` is called on a
worker thread by the Link session, exactly like the SDK's own Executor.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

from musegadget import config

from . import __version__
from .fetch import fetch_image
from .screen import ScreenState

log = logging.getLogger(__name__)

COMMAND_SPECS = {
    "device.health": {
        "description": (
            "Report basic Link health for the browser gadget: whether a "
            "screen (browser page) is attached, the link state and uptime. "
            "Battery fields are null; this gadget has no battery."
        ),
        "required": {},
        "optional": {},
        "timeout_ms": 30000,
    },
    "display.draw_url": {
        "description": (
            "Download an image and show it full-screen on the gadget's "
            "browser page. The gadget fetches the URL itself (HTTPS is "
            "fine). The image replaces the animation until "
            "display.show_animation. Replies when the image is on screen."
        ),
        "required": {
            "url": {"type": "string", "description": "http:// or https:// URL of the image."},
        },
        "optional": {},
        "timeout_ms": 60000,
    },
    "display.show_animation": {
        "description": "Clear the image and bring back the animation and the agent's name.",
        "required": {},
        "optional": {},
        "timeout_ms": 30000,
    },
    "voice.configure": {
        "description": (
            "Set the speaker volume of the gadget's browser page, 0 to 100. "
            "Without volume, reports the current one."
        ),
        "required": {},
        "optional": {
            "volume": {"type": "integer", "description": "Speaker volume, 0 to 100; kept across restarts."},
        },
        "timeout_ms": 30000,
    },
}

_SETTINGS_FILE = "webgadget.json"


def ok(payload: dict) -> dict:
    return {"ok": True, "payload": payload}


def error(message: str) -> dict:
    return {"ok": False, "error": message}


class DisplayExecutor:
    """Implements the browser gadget's commands against a ScreenState."""

    COMMAND_SPECS = COMMAND_SPECS

    def __init__(self, screen: ScreenState) -> None:
        self.screen = screen
        self.started_at = time.time()
        self.screens_attached = 0   # maintained by the web server
        self._load_settings()

    # -- persistence (volume across restarts) --------------------------------

    def _load_settings(self) -> None:
        data = config.load_json(_SETTINGS_FILE) or {}
        volume = data.get("volume")
        if isinstance(volume, int):
            self.screen.set_volume(volume)

    def _save_settings(self) -> None:
        try:
            config.save_json(_SETTINGS_FILE, {"volume": self.screen.volume})
        except OSError:
            log.warning("could not persist settings", exc_info=True)

    # -- dispatch --------------------------------------------------------------

    def run(self, command: str, params: dict, timeout_ms: int | None = None) -> dict:
        try:
            if command == "device.health":
                return ok({
                    "overall": "ok",
                    "version": __version__,
                    "uptime_seconds": int(time.time() - self.started_at),
                    "link_state": self.screen.link_state,
                    "screens_attached": self.screens_attached,
                    "battery_pct": None,
                    "battery_mv": None,
                    "charging": None,
                    "usb_power": None,
                })
            if command == "display.draw_url":
                url = params.get("url")
                if not isinstance(url, str) or not url:
                    return error("url is required")
                data, mime = fetch_image(url)
                self.screen.set_image(data, mime)
                return ok({"bytes": len(data), "format": mime.rsplit("/", 1)[-1]})
            if command == "display.show_animation":
                self.screen.show_animation()
                return ok({})
            if command == "voice.configure":
                volume = params.get("volume")
                if volume is None:
                    return ok({"volume": self.screen.volume})
                self.screen.set_volume(int(volume))
                self._save_settings()
                return ok({"volume": self.screen.volume})
        except Exception as exc:
            log.exception("%s failed", command)
            return error(f"{type(exc).__name__}: {exc}")
        return error(f"unsupported command: {command}")
