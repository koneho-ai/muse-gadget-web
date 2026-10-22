import functools
import io
import os
import threading
from http.server import HTTPServer, SimpleHTTPRequestHandler

import pytest
from PIL import Image

from webgadget.executor import DisplayExecutor
from webgadget.screen import ScreenState


@pytest.fixture()
def state_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("MUSEGADGET_STATE_DIR", str(tmp_path))
    return tmp_path


@pytest.fixture()
def jpeg_server(tmp_path):
    img = Image.new("RGB", (64, 48), (200, 40, 90))
    buf = io.BytesIO()
    img.save(buf, "JPEG")
    (tmp_path / "pic.jpg").write_bytes(buf.getvalue())
    handler = functools.partial(SimpleHTTPRequestHandler, directory=str(tmp_path))
    server = HTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}/pic.jpg", buf.getvalue()
    server.shutdown()


def test_health(state_dir):
    ex = DisplayExecutor(ScreenState())
    result = ex.run("device.health", {})
    assert result["ok"] is True
    assert result["payload"]["overall"] == "ok"
    assert result["payload"]["battery_pct"] is None


def test_draw_url_and_animation(state_dir, jpeg_server):
    url, original = jpeg_server
    screen = ScreenState()
    ex = DisplayExecutor(screen)
    result = ex.run("display.draw_url", {"url": url})
    assert result["ok"] is True
    assert screen.mode == "image"
    assert screen.image == original
    assert screen.image_mime == "image/jpeg"
    assert ex.run("display.show_animation", {})["ok"] is True
    assert screen.mode == "animation"
    assert screen.image is None


def test_draw_url_rejects_bad_input(state_dir):
    ex = DisplayExecutor(ScreenState())
    assert ex.run("display.draw_url", {})["ok"] is False
    assert ex.run("display.draw_url", {"url": "ftp://x/y.jpg"})["ok"] is False


def test_volume_persists(state_dir):
    screen = ScreenState()
    ex = DisplayExecutor(screen)
    assert ex.run("voice.configure", {})["payload"]["volume"] == 80
    assert ex.run("voice.configure", {"volume": 25})["payload"]["volume"] == 25
    assert (state_dir / "webgadget.json").exists()
    ex2 = DisplayExecutor(ScreenState())
    assert ex2.run("voice.configure", {})["payload"]["volume"] == 25
    # Clamped to 0..100.
    assert ex.run("voice.configure", {"volume": 900})["payload"]["volume"] == 100


def test_unknown_command(state_dir):
    ex = DisplayExecutor(ScreenState())
    result = ex.run("system.run", {"command": "id"})
    assert result["ok"] is False
    assert "unsupported" in result["error"]
