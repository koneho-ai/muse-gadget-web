"""Container entrypoint: run the Link service and the web face together.

The runtime never imports the BLE modules — pairing either happened
elsewhere (state dir carried in) or arrives over the pairing relay
WebSocket. See docs/bluetooth.md.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal

from musegadget import config, identity
from musegadget.service import Service

from .executor import DisplayExecutor
from .screen import ScreenState
from .server import WebGadgetServer
from .voice import VoiceBridge

log = logging.getLogger("webgadget")


def _ensure_ca_bundle() -> None:
    """Point OpenSSL at certifi's CA bundle when the platform default is
    missing or empty. macOS framework Pythons ship with no CA store wired
    into ssl ("unable to get local issuer certificate"); Debian in the
    container is unaffected. No-op when SSL_CERT_FILE is already set."""
    if os.environ.get("SSL_CERT_FILE"):
        return
    try:
        import certifi
    except ImportError:
        return
    os.environ["SSL_CERT_FILE"] = certifi.where()


def _sdk_token() -> str | None:
    try:
        return config.sdk_token()
    except ValueError:
        log.warning("the SDK token is invalid; continuing without it")
        return None


async def _watch_link_state(service: Service, screen: ScreenState) -> None:
    """Mirror the service's connection state onto the screen."""
    while True:
        if config.load_json(config.PAIRING_FILE) is None:
            screen.set_link_state("unpaired")
        else:
            session = service.current_session
            screen.set_link_state(
                "connected" if session is not None and session.registered_at else "connecting"
            )
        await asyncio.sleep(2)


async def amain() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    _ensure_ca_bundle()
    port = int(os.environ.get("WEB_PORT", "8321"))
    display_name = os.environ.get("DISPLAY_NAME", "Muse Gadget (Web)")
    ident = identity.load_or_create()
    screen = ScreenState()
    screen.title = display_name
    executor = DisplayExecutor(screen)
    service = Service(
        identity=ident,
        executor=executor,       # type: ignore[arg-type]  (duck-typed Executor)
        sdk_token=_sdk_token(),
        display_name=display_name,
    )
    # All gadget chat goes to one dedicated side chat. The id is a
    # deterministic UUIDv5 of the node id — chat ids in this system are
    # UUIDs (a slug id is rejected with HTTP 400) — so the same side
    # chat is reused across restarts and state wipes.
    import uuid

    voice = VoiceBridge(
        lambda: service.current_session, screen,
        chat_session_id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"muse-gadget:{ident.node_id}")),
    )
    server = WebGadgetServer(
        screen=screen, executor=executor, voice=voice, identity=ident, port=port,
    )
    await server.start()
    log.info("gadget %s (%s) starting", ident.ble_name, ident.node_id)

    loop = asyncio.get_running_loop()
    for signum in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(signum, service.stop)
    watcher = asyncio.ensure_future(_watch_link_state(service, screen))
    try:
        await service.run()
    finally:
        watcher.cancel()


def run() -> None:
    asyncio.run(amain())


if __name__ == "__main__":
    run()
