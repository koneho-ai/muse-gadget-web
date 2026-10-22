"""Pair this gadget from a Bluetooth-capable host, writing the shared
state directory the container runtime mounts.

    MUSEGADGET_STATE_DIR=./state MUSEGADGET_SDK_TOKEN=<redacted> \
        python -m webgadget.pair_cli

This is the SDK's own pairing flow (musegadget.pair) with console
messages — identical to `musegadget pair`, minus the shell/file gadget.
The container itself never needs Bluetooth: pair here once, then run
the container anywhere with the same state directory.
"""

from __future__ import annotations

import logging
import sys

from musegadget.pair import PairOutcome, SetupWindow, pair


def _on_open(window: SetupWindow) -> None:
    print(f"Bluetooth setup is open for {window.timeout_s // 60} minutes.")
    print(f"In the Muse app: Settings > Devices > Developer mode, then Add Device.")
    print(f"Pick: {window.ble_name}")
    if not window.has_sdk_token:
        print("Warning: no SDK token set — gadgets without one will stop pairing.")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    force = "--force" in sys.argv
    result = pair(on_open=_on_open, force=force)
    messages = {
        PairOutcome.PAIRED: "Paired. The state directory now holds pairing.json — start the container.",
        PairOutcome.ALREADY_PAIRED: "Already paired. Run with --force to pair again.",
        PairOutcome.WINDOW_CLOSED: "Setup window closed without pairing.",
    }
    if result.outcome is PairOutcome.INVALID_SDK_TOKEN:
        print(f"Can't pair: {result.sdk_token_problem}")
        return 1
    print(messages[result.outcome])
    return 0 if result.outcome in (PairOutcome.PAIRED, PairOutcome.ALREADY_PAIRED) else 1


if __name__ == "__main__":
    raise SystemExit(main())
