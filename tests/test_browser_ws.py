"""The browser face's WebSocket: state pushes on connect and on change."""

import asyncio

from aiohttp.test_utils import TestClient, TestServer

from musegadget.identity import Identity
from webgadget.executor import DisplayExecutor
from webgadget.screen import ScreenState
from webgadget.server import WebGadgetServer
from webgadget.voice import VoiceBridge


def test_state_push_and_updates(tmp_path, monkeypatch):
    monkeypatch.setenv("MUSEGADGET_STATE_DIR", str(tmp_path))

    async def run():
        screen = ScreenState()
        executor = DisplayExecutor(screen)
        server = WebGadgetServer(
            screen=screen, executor=executor,
            voice=VoiceBridge(lambda: None, screen),
            identity=Identity("02:11:22:33:44:55"), port=0,
        )
        client = TestClient(TestServer(server.app))
        await client.start_server()
        try:
            ws = await client.ws_connect("/ws")
            first = await asyncio.wait_for(ws.receive_json(), 5)
            assert first["type"] == "state"
            assert first["link_state"] == "boot"
            screen.set_link_state("connected")
            seen = None
            for _ in range(10):
                msg = await asyncio.wait_for(ws.receive_json(), 5)
                if msg["link_state"] == "connected":
                    seen = msg
                    break
            assert seen is not None, "state change was not pushed"
            # Volume set through the API is reflected in the pushed state.
            resp = await client.post("/volume", json={"volume": 33})
            assert resp.status == 200
            for _ in range(10):
                msg = await asyncio.wait_for(ws.receive_json(), 5)
                if msg.get("volume") == 33:
                    break
            else:
                raise AssertionError("volume change was not pushed")
            await ws.close()
        finally:
            await client.close()

    asyncio.run(run())
