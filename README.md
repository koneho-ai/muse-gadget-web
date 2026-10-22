# muse-gadget-web

A Muse gadget that runs in a **Docker container** and uses a **browser
page as its screen and speaker** — the same Link protocol and the same
agent-side commands as the physical boards, without the board.

Open the page on a tablet, a Facebook Portal, a spare phone, a TV
browser — anything that renders a web page becomes the gadget's face.

## What Muse can do with it

The gadget registers with the same commands as the ESP32 display boards:

| Command | Effect |
|---|---|
| `device.health` | Link state, uptime, whether a screen is attached |
| `display.draw_url` | Fetch an image (HTTPS fine — the *backend* fetches it, so private expiring links work) and show it full-screen on the page |
| `display.show_animation` | Back to the idle face |
| `voice.configure` | Speaker volume 0–100, persisted |

And from the page itself:

- **Ask by text or voice** — type, or tap the mic and talk. The turn goes
  out on the gadget's own Link session (`send_chat` / `send_voice` with
  `output_modality="voice"`); the reply text appears on the face and the
  reply is **spoken aloud** through the page (`stream_tts` MP3).

Voice is turn-based (push-to-talk), built on the Linux SDK's voice
plumbing — not the ESP32 boards' real-time voice pipeline.

## Architecture

```
Muse (agent) ──Link/Noise──► container backend (Python, vendored SDK)
                                  │  display.* / voice.* commands
                                  ▼
                              ScreenState ──WebSocket──► browser page
                                  ▲                        (face, speaker,
                                  └── /say /voice /volume    mic, volume)
```

- The protocol core is the SDK's Python Linux client, vendored under
  `app/musegadget/` (Apache-2.0, see `NOTICE.md`) with a small patch so
  the service advertises this gadget's commands instead of the stock
  `system.run` / `file.*` set. **There is deliberately no shell access.**
- The web face and API are one aiohttp server (`app/webgadget/server.py`)
  on port 8321.

## Pairing (the Bluetooth question)

Pairing is the one step that involves Bluetooth, because the Muse app
mints the device tokens and only speaks BLE. The container runtime never
touches Bluetooth. Your options, from `docs/bluetooth.md`:

1. **Pair profile** (Linux Docker host with Bluetooth):
   `docker compose --profile pair up pair`
2. **Pair on any Bluetooth host** (Docker Desktop, etc.):
   `tools/pair-on-host.sh`, then run the container with the same
   `state/` directory.
3. **BLE relay**: run `tools/ble_relay.py` on any Bluetooth-capable Linux
   machine on the LAN; it relays the GATT conversation to the
   container's own pairing controller over a WebSocket. The relay holds
   no keys or credentials.

Every gadget needs an **SDK token** from
[gadgets.muse.ai/settings/sdk-tokens](https://gadgets.muse.ai/settings/sdk-tokens).
It goes in `.env` / the state volume on the gadget host — never in git.

## Run

```sh
cp .env.example .env        # fill in MUSEGADGET_SDK_TOKEN (+ PAIRING_RELAY_SECRET if using the relay)
docker compose --profile pair up pair   # once (option 1), with the Muse app open
docker compose up -d gadget
# open http://<host>:8321
```

## Develop / test

```sh
python3 -m venv .venv && .venv/bin/pip install -r app/requirements.txt pytest
PYTHONPATH=app .venv/bin/python -m webgadget     # bare-metal run
.venv/bin/python -m pytest tests/                # executor, server, and a
                                                 # full scripted pairing over
                                                 # the relay transport
```

## Status (2026-10-22)

Implemented and tested locally (bare-metal; the development VM has no
Docker daemon): executor commands, the web face + API, voice-turn glue,
and the complete pairing protocol running over the relay transport
against a scripted mobile client. **Not yet done:** a first pairing with
a real phone (which also settles whether a moved pairing state directory
is accepted server-side), and a `docker build` on a Docker host.
