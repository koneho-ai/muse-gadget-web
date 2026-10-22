"""HTTP + WebSocket server: the gadget's face and its pairing relay.

One port serves everything:
  GET  /              the device face (screen + speaker + mic)
  GET  /ws            live state pushes to the face
  GET  /img/current   the currently drawn image (bytes)
  GET  /audio/{id}    a TTS reply clip to play
  POST /say           {message} -> a spoken-reply turn
  POST /voice         raw WAV body -> a spoken-reply turn
  POST /volume        {volume} -> set speaker volume
  POST /face          back to the character (clears a drawn image)
  GET  /pairing/ws    BLE relay endpoint (see pairing_ws.py)
  GET  /healthz       liveness + link state
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path

from aiohttp import WSMsgType, web

from musegadget.identity import Identity

from .executor import DisplayExecutor
from .pairing_ws import PairingRelaySession, load_sdk_token, relay_secret
from .screen import ScreenState
from .voice import VoiceBridge

log = logging.getLogger(__name__)

MAX_VOICE_BYTES = 2 * 1024 * 1024


def find_web_dir() -> Path:
    env = os.environ.get("WEB_DIR")
    candidates = []
    if env:
        candidates.append(Path(env))
    here = Path(__file__).resolve()
    candidates += [here.parents[2] / "web", Path("/srv/web"), Path.cwd() / "web"]
    for candidate in candidates:
        if (candidate / "index.html").exists():
            return candidate
    return candidates[0]


class WebGadgetServer:
    def __init__(
        self,
        *,
        screen: ScreenState,
        executor: DisplayExecutor,
        voice: VoiceBridge,
        identity: Identity,
        port: int,
    ) -> None:
        self.screen = screen
        self.executor = executor
        self.voice = voice
        self.identity = identity
        self.port = port
        self.app = web.Application()
        self._browsers: set[web.WebSocketResponse] = set()
        self._pairing_session: PairingRelaySession | None = None
        routes = self.app.router
        routes.add_get("/", self._index)
        routes.add_get("/ws", self._browser_ws)
        routes.add_get("/img/current", self._image)
        routes.add_get("/audio/{id}", self._audio)
        routes.add_post("/say", self._say)
        routes.add_post("/voice", self._voice)
        routes.add_post("/volume", self._volume)
        routes.add_post("/face", self._face)
        routes.add_get("/pairing/ws", self._pairing_ws)
        routes.add_get("/healthz", self._healthz)
        routes.add_static("/static/", find_web_dir(), show_index=False)

    async def start(self) -> None:
        runner = web.AppRunner(self.app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", self.port)
        await site.start()
        log.info("web gadget face on http://0.0.0.0:%d", self.port)

    # -- face ------------------------------------------------------------------

    async def _index(self, request: web.Request) -> web.Response:
        return web.FileResponse(find_web_dir() / "index.html")

    async def _browser_ws(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(heartbeat=30)
        await ws.prepare(request)
        self._browsers.add(ws)
        self.executor.screens_attached = len(self._browsers)
        log.info("a screen attached (%d total)", len(self._browsers))
        pusher = asyncio.ensure_future(self._push_state(ws))
        try:
            async for _msg in ws:
                pass   # the face sends nothing but pings in v1
        finally:
            pusher.cancel()
            self._browsers.discard(ws)
            self.executor.screens_attached = len(self._browsers)
        return ws

    async def _push_state(self, ws: web.WebSocketResponse) -> None:
        last = -1
        try:
            while not ws.closed:
                snap = self.screen.snapshot()
                if snap["version"] != last:
                    last = snap["version"]
                    await ws.send_json({"type": "state", **snap})
                await asyncio.sleep(0.15)
        except (asyncio.CancelledError, ConnectionResetError):
            pass

    async def _image(self, request: web.Request) -> web.Response:
        if self.screen.image is None:
            raise web.HTTPNotFound()
        return web.Response(body=self.screen.image, content_type=self.screen.image_mime)

    async def _audio(self, request: web.Request) -> web.Response:
        item = self.screen.get_audio(request.match_info["id"])
        if item is None:
            raise web.HTTPNotFound()
        data, mime = item
        return web.Response(body=data, content_type=mime)

    # -- voice turns -------------------------------------------------------------

    async def _say(self, request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except json.JSONDecodeError:
            raise web.HTTPBadRequest(text="expected JSON")
        message = body.get("message") if isinstance(body, dict) else None
        if not isinstance(message, str) or not message.strip():
            raise web.HTTPBadRequest(text="message is required")
        try:
            result = await self.voice.say_text(message.strip())
        except ConnectionError as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=503)
        return web.json_response(result)

    async def _voice(self, request: web.Request) -> web.Response:
        data = await request.read()
        if not data or len(data) > MAX_VOICE_BYTES:
            raise web.HTTPBadRequest(text="expected a WAV voice note up to 2 MiB")
        try:
            result = await self.voice.say_voice(data)
        except ConnectionError as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=503)
        return web.json_response(result)

    async def _face(self, request: web.Request) -> web.Response:
        self.screen.show_animation()
        return web.json_response({"ok": True})

    async def _volume(self, request: web.Request) -> web.Response:
        try:
            body = await request.json()
            volume = int(body.get("volume"))
        except (json.JSONDecodeError, TypeError, ValueError, AttributeError):
            raise web.HTTPBadRequest(text="expected {volume: 0..100}")
        result = self.executor.run("voice.configure", {"volume": volume})
        return web.json_response(result)

    # -- pairing relay -----------------------------------------------------------

    async def _pairing_ws(self, request: web.Request) -> web.WebSocketResponse:
        secret = relay_secret()
        if not secret:
            raise web.HTTPServiceUnavailable(text="pairing relay is disabled (PAIRING_RELAY_SECRET is not set)")
        if request.headers.get("X-Relay-Secret") != secret:
            raise web.HTTPUnauthorized(text="bad relay secret")
        if self._pairing_session is not None:
            raise web.HTTPConflict(text="a pairing session is already in progress")
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        loop = asyncio.get_running_loop()

        def send_sync(packet: bytes) -> None:
            asyncio.run_coroutine_threadsafe(ws.send_bytes(packet), loop).result(timeout=15)

        session = PairingRelaySession(
            identity=self.identity,
            sdk_token=load_sdk_token(),
            send_sync=send_sync,
        )
        self._pairing_session = session
        session.start()
        log.info("pairing relay connected; gadget advertises as %s", self.identity.ble_name)
        try:
            async for msg in ws:
                if msg.type == WSMsgType.BINARY:
                    session.on_packet(msg.data)
                elif msg.type == WSMsgType.TEXT:
                    try:
                        control = json.loads(msg.data)
                    except json.JSONDecodeError:
                        continue
                    if control.get("type") == "mtu":
                        session.transport.set_mtu(int(control.get("mtu", 256)))
                    elif control.get("type") == "disconnect":
                        session.on_ble_disconnect()
        finally:
            session.stop()
            self._pairing_session = None
            log.info("pairing relay disconnected (paired: %s)", session.completed)
        return ws

    async def _healthz(self, request: web.Request) -> web.Response:
        return web.json_response({
            "ok": True,
            "link_state": self.screen.link_state,
            "screens_attached": len(self._browsers),
            "node_id": self.identity.node_id,
        })
