# The Bluetooth problem, and how this project walks around it

## Why pairing needs Bluetooth at all

Tracing the Muse Gadget SDK's pairing (protocol v5, `musegadget/pairing.py`,
`ble_setup.py`, `pair.py` in the vendored SDK):

1. The Muse **app** discovers the gadget's BLE advertisement and connects
   over GATT.
2. Plaintext `pairing_client_hello` → the gadget answers `pairing_ready`
   (ECDH P-256 + nonces; keys derived from the handshake transcript with
   HKDF-SHA256).
3. AES-GCM encrypted records then carry `pairing_client_finished` (the
   app's consent), an optional `wifi_scan`, and `provision_v2` — which
   contains the **device access/refresh tokens the app mints from the
   user's account**.
4. The gadget verifies the tokens (`GET /fetch_vms`), saves
   `pairing.json`, and never touches Bluetooth again. The runtime speaks
   only the Noise Link protocol over the internet.

Two facts fall out of that:

- **There is no pure-API shortcut.** A gadget cannot provision itself
  with just an SDK token: the token is *reported to* the app during
  pairing (in the `pairing_confirmed` record) and later in token
  refreshes. The credentials are minted app-side, over BLE. Any design
  that skips the app skips the only credential issuer.
- **The setup logic is transport-agnostic.** The SDK's `SetupController`
  consumes reassembled message bytes and emits BLE-sized packets through
  a three-method `Transport` interface (`send_packets`, `mtu`,
  `disconnect`). BLE is just the pipe it ships with.

## The workarounds implemented here

### 1. Pair outside Docker, run inside Docker (no Bluetooth on the host)

Pairing state is portable files (`identity.json`, `pairing.json`, mode
0600) in one state directory. So:

- `docker compose --profile pair up pair` — one-shot pairing container
  using the host's BlueZ via its system D-Bus socket (Linux Docker hosts
  with Bluetooth), **or**
- `tools/pair-on-host.sh` — runs the same SDK pairing natively on a
  Bluetooth-capable **Linux** host against `./state`. Not macOS or
  Windows: the SDK's BLE server is BlueZ/D-Bus code, and Docker
  Desktop's VM has no Bluetooth to pass through in the first place —
  on those hosts use the relay in section 2, or run the gadget
  container on a Linux Bluetooth host instead, **or**
- pair on any machine, then copy the state directory/volume to the
  Docker host.

The runtime container imports no BLE code at all
(`musegadget.ble_server` is imported lazily, only by the pairing path —
verified in the SDK source).

### 2. BLE relay: Bluetooth at the edge, pairing in the container

For hosts where even a one-shot pairing container is awkward,
`tools/ble_relay.py` runs on any Bluetooth-capable Linux machine on the
same trusted network. It advertises the gadget's GATT service (using the
SDK's own `BleServer`) and relays every packet byte-for-byte over a
WebSocket to the container's `GET /pairing/ws`, where a `SetupController`
wired to a WebSocket `Transport` (`app/webgadget/pairing_ws.py`) runs the
real pairing against the container's own identity and state.

Properties:

- The relay is a dumb pipe: no identity, no keys, no credentials. After
  the plaintext hello, all records are encrypted end-to-end between the
  app and the container with handshake keys — the relay sees ciphertext,
  exactly what a passive BLE observer sees.
- The endpoint is disabled unless `PAIRING_RELAY_SECRET` is set, and the
  relay must present it in the `X-Relay-Secret` header.
- Community pairing (`pairing_auth: "none"`, `confirm_app` policy)
  already assumes a trusted setup environment — it cannot stop an
  active man-in-the-middle, on BLE or on a relay. Pair on a trusted
  network (LAN or tailnet), like the stock flow assumes a trusted room.

Verified here: the full protocol — hello, transcript-matched
`pairing_ready`, encrypted `pairing_client_finished` →
`pairing_confirmed`, encrypted `provision_v2` → `auth_ok` — runs over
the relay transport against a scripted mobile client
(`tests/test_pairing_relay.py`). The BlueZ half of the relay uses the
SDK's own GATT server unchanged; it still needs a first run against a
real phone + adapter to be called proven.

### Host prep for anything that does BLE (pair container or relay)

From the SDK's `linux/AGENTS.md`:

- `/etc/bluetooth/main.conf`: `ExchangeMTU = 256` under `[GATT]`
  (Android pairing otherwise dies at the Wi-Fi step).
- Disable BlueZ's battery plugin (it asks phones to bond; the gadget
  never bonds, and iOS pairing can drop).

## What remains genuinely untested

- Whether the Muse servers accept a pairing whose state directory was
  moved to a different host/IP afterwards. The design says the state is
  just files and the runtime is a plain outbound client; the first real
  pairing will confirm it.
- The relay against a real phone (see above).
