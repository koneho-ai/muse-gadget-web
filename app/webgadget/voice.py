"""Turn-based voice for the browser gadget.

A turn: the page sends text or a WAV voice note; this bridge posts it on
the gadget's own Link session with ``output_modality="voice"``, follows
the chat event stream with MuseTurn, shows the reply text on the screen,
and streams the reply's TTS MP3 back to the page for playback. This is
the Linux SDK's voice plumbing (send_chat/send_voice + stream_tts) — not
the ESP32 boards' real-time ADPCM pipeline.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Awaitable, Callable

from musegadget.link_client import LinkSession
from musegadget.muse_turn import AgentStatus, MuseTurn, Reply

from .screen import ScreenState

log = logging.getLogger(__name__)

TURN_TIMEOUT_S = 240


def _ack_body(response: dict) -> dict | None:
    """Unwrap a LinkSession chat response to the acknowledgement body.

    ``LinkSession._post_chat`` wraps the decoded body as
    ``{"ok", "status", "response"}``, while ``MuseTurn.acknowledge``
    expects the body itself (ids at the top level or under ``result``).
    """
    body = response.get("response")
    return body if isinstance(body, dict) else None


def _error_detail(response: dict) -> str:
    """Best-effort human-readable reason from a rejected chat response."""
    body = response.get("response")
    if isinstance(body, dict):
        for key in ("error", "message", "detail"):
            value = body.get(key)
            if isinstance(value, str) and value:
                return value[:200]
            if isinstance(value, dict):
                inner = value.get("message") or value.get("error")
                if isinstance(inner, str) and inner:
                    return inner[:200]
        return ""
    if isinstance(body, str):
        return body[:200]
    return ""


class VoiceBridge:
    def __init__(self, session_getter: Callable[[], LinkSession | None], screen: ScreenState,
                 chat_session_id: str | None = None) -> None:
        self._session_getter = session_getter
        self._screen = screen
        self._busy = asyncio.Lock()
        # The gadget's dedicated side chat: every turn goes to this session
        # id (an unseen id starts the chat), never to the user's main chat.
        self._chat_session_id = chat_session_id

    def _session(self) -> LinkSession:
        session = self._session_getter()
        if session is None or session.registered_at is None:
            raise ConnectionError("the gadget is not connected to its Muse yet")
        return session

    async def say_text(self, message: str) -> dict:
        async def sender(session: LinkSession) -> dict:
            return await session.send_chat(message, self._chat_session_id, output_modality="voice")

        return await self._run_turn(sender)

    async def say_voice(self, wav_bytes: bytes) -> dict:
        async def sender(session: LinkSession) -> dict:
            return await session.send_voice(wav_bytes, self._chat_session_id, output_modality="voice")

        return await self._run_turn(sender)

    async def _run_turn(self, sender: Callable[[LinkSession], Awaitable[dict]]) -> dict:
        if self._busy.locked():
            return {"ok": False, "error": "a voice turn is already in progress"}
        async with self._busy:
            session = self._session()
            turn = MuseTurn(session_id=self._chat_session_id)
            self._screen.set_status("thinking")
            pump = asyncio.ensure_future(self._pump(session, turn))
            try:
                response = await sender(session)
                if not response.get("ok"):
                    detail = _error_detail(response)
                    log.warning("Muse rejected the message (HTTP %s): %s",
                                response.get("status"), detail or "no detail")
                    error = f"Muse rejected the message (HTTP {response.get('status')})"
                    if detail:
                        error += f": {detail}"
                    return {"ok": False, "error": error}
                body = _ack_body(response)
                if body is None:
                    return {"ok": False, "error": "Muse returned an unreadable acknowledgement"}
                self._apply(turn.acknowledge(body))
                deadline = time.monotonic() + TURN_TIMEOUT_S
                while not turn.complete(time.monotonic()):
                    if time.monotonic() > deadline:
                        return {"ok": False, "error": "timed out waiting for the reply"}
                    await asyncio.sleep(0.25)
            finally:
                pump.cancel()
            replies = [r for r in turn.replies.values() if r.text]
            reply = replies[-1] if replies else None
            audio_id = None
            if reply is not None:
                self._screen.set_reply(reply.text, "")
                try:
                    mp3 = bytearray()
                    async for chunk in session.stream_tts(reply.message_id):
                        mp3 += chunk
                    if mp3:
                        audio_id = self._screen.put_audio(bytes(mp3))
                except Exception:
                    log.warning("TTS stream failed", exc_info=True)
            return {"ok": True, "reply": reply.text if reply else "", "audio_id": audio_id}

    async def _pump(self, session: LinkSession, turn: MuseTurn) -> None:
        try:
            async for event in session.subscribe_chat(self._chat_session_id):
                self._apply(turn.feed(event))
        except asyncio.CancelledError:
            raise
        except Exception:
            log.debug("chat subscription ended", exc_info=True)

    def _apply(self, events) -> None:
        for event in events:
            if isinstance(event, AgentStatus):
                if event.activity_code:
                    self._screen.set_status(event.activity_code)
            elif isinstance(event, Reply):
                if event.text:
                    self._screen.set_reply(event.text, self._screen.status_text)
