"""Pairing without Bluetooth on the Docker host.

Why this exists: the Muse app mints the device tokens during pairing,
and it only speaks BLE GATT — there is no server API for a gadget to
provision itself with just an SDK token. But the SDK's setup logic
(``musegadget.ble_setup.SetupController``) is transport-agnostic: it
consumes reassembled message bytes and emits BLE-sized packets through a
small Transport interface. This module gives that controller a WebSocket
transport, and ``tools/ble_relay.py`` is the other half: a dumb pipe on
any Bluetooth-capable Linux machine that advertises the gadget's GATT
service and relays the packets, byte for byte, over the WebSocket.

The relay holds no state and no secrets: after the plaintext hello, all
records are AES-GCM encrypted end-to-end between the app and this
controller with keys from the pairing handshake itself.

The endpoint is disabled unless PAIRING_RELAY_SECRET is set; the relay
must present it in the ``X-Relay-Secret`` header. Run it on a trusted
network (LAN or tailnet) only — community pairing already assumes a
trusted setup network, exactly like the stock BLE flow.
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
from typing import Callable

from musegadget import __version__, config
from musegadget.ble_setup import SetupController
from musegadget.identity import Identity
from musegadget.pair import _SystemNetwork, _verify_and_save
from musegadget.pairing import PairingSession

log = logging.getLogger(__name__)

SECRET_ENV = "PAIRING_RELAY_SECRET"


def relay_secret() -> str:
    return os.environ.get(SECRET_ENV, "")


class RelayTransport:
    """SetupController Transport backed by a synchronous send callable.

    ``send_sync`` must deliver one packet (bytes) to the relay, in order,
    and is called from the controller's worker thread.
    """

    def __init__(self, send_sync: Callable[[bytes], None]) -> None:
        self._send_sync = send_sync
        self._mtu = 256
        self._lock = threading.Lock()
        self.on_disconnect_request: Callable[[], None] | None = None

    def mtu(self) -> int:
        with self._lock:
            return self._mtu

    def set_mtu(self, mtu: int) -> None:
        with self._lock:
            if 23 <= mtu <= 517:
                self._mtu = mtu

    def send_packets(self, packets: list[bytes]) -> None:
        for packet in packets:
            self._send_sync(packet)

    def disconnect(self, delay: float) -> None:
        callback = self.on_disconnect_request
        if callback is not None:
            threading.Timer(max(0.0, delay), callback).start()


class PairingRelaySession:
    """One relay connection: a SetupController wired to a RelayTransport."""

    def __init__(
        self,
        identity: Identity,
        sdk_token: str | None,
        send_sync: Callable[[bytes], None],
        provision: Callable = _verify_and_save,
        network=_SystemNetwork,
    ) -> None:
        self.transport = RelayTransport(send_sync)
        pairing = PairingSession(
            node_id=identity.node_id,
            device_id=identity.device_id,
            mac=identity.mac,
            firmware_version=__version__,
            sdk_token=sdk_token,
        )
        self._completed = threading.Event()
        self.controller = SetupController(
            pairing=pairing,
            identity=identity,
            version=__version__,
            transport=self.transport,
            network=network,
            provision=provision,
            on_complete=self._completed.set,
        )
        self.transport.on_disconnect_request = self.controller.on_disconnect

    @property
    def completed(self) -> bool:
        return self._completed.is_set()

    def start(self) -> None:
        self.controller.start()

    def stop(self) -> None:
        self.controller.stop()

    def on_packet(self, packet: bytes) -> None:
        self.controller.on_write(packet)

    def on_ble_disconnect(self) -> None:
        self.controller.on_disconnect()


def load_sdk_token() -> str | None:
    try:
        return config.sdk_token()
    except ValueError:
        log.warning("stored SDK token is invalid; pairing relay continues without it")
        return None
