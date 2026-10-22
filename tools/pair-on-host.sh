#!/bin/sh
# Pair the browser gadget from this (Bluetooth-capable) host, writing the
# shared state directory the container mounts. Bluetooth never touches
# the Docker host: pair here once, then run the container anywhere with
# the same ./state directory. See docs/bluetooth.md.
#
# Needs on this host: python3 with cryptography + websockets, and (on
# Linux) BlueZ running with dbus/gi available to python3.
set -eu
cd "$(dirname "$0")/.."
export MUSEGADGET_STATE_DIR="${MUSEGADGET_STATE_DIR:-$PWD/state}"
export PYTHONPATH="$PWD/app${PYTHONPATH:+:$PYTHONPATH}"
if [ -z "${MUSEGADGET_SDK_TOKEN:-}" ]; then
  echo "Set MUSEGADGET_SDK_TOKEN to your SDK token from https://gadgets.muse.ai/settings/sdk-tokens" >&2
  exit 1
fi
exec python3 -m webgadget.pair_cli "$@"
