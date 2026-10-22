#!/usr/bin/env python3
"""BLE relay for muse-gadget-web pairing — the Bluetooth workaround.

Run this on any Bluetooth-capable Linux machine on the same trusted
network as the gadget container (a Pi, a laptop, the NAS if it had BT).
It advertises the gadget's BLE GATT service and relays every packet,
byte for byte, over a WebSocket to the container's /pairing/ws, where
the SDK's transport-agnostic SetupController runs the real pairing.

The relay is a dumb pipe: it holds no identity, keys or credentials.
After the plaintext hello, pairing records are AES-GCM encrypted
end-to-end between the Muse app and the container.

Usage:
    PAIRING_RELAY_SECRET=<redacted> python3 tools/ble_relay.py \
        --url ws://gadget-host:8321/pairing/ws --name MuseGadgetA1B2C3

The name must be the gadget's BLE name (MuseGadget + the last six hex
digits of its node id); the container logs it when a relay connects, and
`GET /healthz` shows the node id. Host prep (BlueZ MTU + battery plugin)
matches the SDK's linux/AGENTS.md notes; see docs/bluetooth.md.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))

from websockets.sync.client import connect as ws_connect

from musegadget.ble_server import BleServer


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True, help="ws://host:8321/pairing/ws of the gadget container")
    parser.add_argument("--name", required=True, help="the gadget's BLE name, e.g. MuseGadgetA1B2C3")
    parser.add_argument("--secret", default=os.environ.get("PAIRING_RELAY_SECRET", ""),
                        help="shared secret (default: $PAIRING_RELAY_SECRET)")
    args = parser.parse_args()
    if not args.secret:
        parser.error("a relay secret is required (flag or PAIRING_RELAY_SECRET)")

    ws = ws_connect(args.url, additional_headers={"X-Relay-Secret": args.secret})
    print(f"relay connected to {args.url}; advertising as {args.name}", flush=True)

    def on_write(packet: bytes) -> None:
        try:
            ws.send(packet)
        except Exception:
            server.stop()

    def on_disconnect() -> None:
        try:
            ws.send(json.dumps({"type": "disconnect"}))
        except Exception:
            pass

    server = BleServer(args.name, on_write=on_write, on_disconnect=on_disconnect)

    def receive_loop() -> None:
        last_mtu = None
        try:
            for message in ws:
                if isinstance(message, bytes):
                    server.send_packets([message])
                mtu = server.mtu()
                if mtu != last_mtu:
                    last_mtu = mtu
                    ws.send(json.dumps({"type": "mtu", "mtu": mtu}))
        except Exception:
            pass
        finally:
            server.stop()

    threading.Thread(target=receive_loop, name="ws-recv", daemon=True).start()
    try:
        server.run()   # blocks; owns the Bluetooth adapter until stopped
    finally:
        ws.close()
    print("relay stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
