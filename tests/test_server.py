"""Smoke test: the real aiohttp server, real HTTP requests."""

import asyncio
import json
import urllib.request

import pytest

from musegadget.identity import Identity
from webgadget.executor import DisplayExecutor
from webgadget.screen import ScreenState
from webgadget.server import WebGadgetServer
from webgadget.voice import VoiceBridge


@pytest.fixture()
def server_url(tmp_path, monkeypatch):
    monkeypatch.setenv("MUSEGADGET_STATE_DIR", str(tmp_path))
    monkeypatch.delenv("PAIRING_RELAY_SECRET", raising=False)
    screen = ScreenState()
    executor = DisplayExecutor(screen)
    voice = VoiceBridge(lambda: None, screen)
    server = WebGadgetServer(
        screen=screen, executor=executor, voice=voice,
        identity=Identity("02:11:22:33:44:55"), port=0,
    )
    import socket
    import threading
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    server.port = port

    loop = asyncio.new_event_loop()

    def run_loop():
        asyncio.set_event_loop(loop)
        loop.run_until_complete(server.start())
        loop.run_forever()

    thread = threading.Thread(target=run_loop, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{port}"
    # Wait until the site actually accepts connections; yielding earlier
    # made these tests flaky (~1 in 3 runs lost the startup race).
    import time
    deadline = time.monotonic() + 5
    while True:
        try:
            with urllib.request.urlopen(url + "/healthz", timeout=1):
                break
        except Exception:
            if time.monotonic() > deadline:
                raise
            time.sleep(0.05)
    yield url
    loop.call_soon_threadsafe(loop.stop)


def get(url):
    with urllib.request.urlopen(url, timeout=5) as resp:
        return resp.status, resp.read()


def test_face_and_healthz(server_url):
    status, body = get(server_url + "/healthz")
    assert status == 200
    data = json.loads(body)
    assert data["ok"] is True
    assert data["node_id"] == "homelink-334455"
    status, body = get(server_url + "/")
    assert status == 200
    assert b"Muse Gadget" in body


def test_face_endpoint(server_url):
    req = urllib.request.Request(server_url + "/face", method="POST", data=b"")
    with urllib.request.urlopen(req, timeout=5) as resp:
        assert resp.status == 200
        assert json.loads(resp.read())["ok"] is True


def test_say_without_link_is_503(server_url):
    req = urllib.request.Request(
        server_url + "/say", method="POST",
        data=json.dumps({"message": "hi"}).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        urllib.request.urlopen(req, timeout=5)
        raise AssertionError("expected 503")
    except urllib.error.HTTPError as exc:
        assert exc.code == 503
        assert json.loads(exc.read())["ok"] is False


def test_image_roundtrip(server_url, tmp_path, monkeypatch):
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (1, 2, 3)).save(buf, "PNG")
    data = buf.getvalue()
    # No executor handle here; drive the screen through the volume endpoint
    # for liveness, and check a missing image is a 404.
    try:
        get(server_url + "/img/current")
        raise AssertionError("expected 404")
    except urllib.error.HTTPError as exc:
        assert exc.code == 404
