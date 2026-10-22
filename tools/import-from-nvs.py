#!/usr/bin/env python3
"""Build web-gadget state files from an ESP32 gadget's NVS dump.

The ESP32 firmware keeps its pairing in NVS namespace ``homehub`` as
plaintext strings (access_token, refresh_token, username, api_url,
noise_host). Dump the NVS partition with esptool and convert it with
ESP-IDF's nvs_tool.py:

    esptool read_flash 0x11000 0x5000 nvs.bin        # offsets: see your partition table
    python3 $IDF_PATH/components/nvs_flash/nvs_partition_tool/nvs_tool.py \
        -d minimal -f json nvs.bin > nvs.json
    python3 tools/import-from-nvs.py nvs.json --mac 24:62:ab:f9:a6:6c --out ~/gadget-clone

This CLONES the ESP32's device identity: afterwards only one of the two
may run, because token refreshes rotate the pair and invalidate the
other copy. Values are never printed — only key names and lengths.
The Wi-Fi ssid/password keys in the dump are deliberately not copied.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time

FIELDS = ("access_token", "refresh_token", "username", "api_url", "noise_host")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("nvs_json", help="output of nvs_tool.py -d minimal -f json")
    ap.add_argument("--mac", required=True, help="the ESP32's MAC, e.g. 24:62:ab:f9:a6:6c")
    ap.add_argument("--out", default="gadget-clone", help="output directory")
    args = ap.parse_args()

    entries = json.loads(pathlib.Path(args.nvs_json).read_text())
    kv = {}
    for entry in entries:  # nvs_tool JSON: list of {namespace, key, encoding, data, state}
        if (entry.get("namespace") == "homehub" and entry.get("state") == "Written"
                and entry.get("encoding") == "string"):
            kv[entry["key"]] = entry["data"]
    if not kv.get("access_token") or not kv.get("refresh_token"):
        print(f"token keys not found; homehub keys present: {sorted(kv)}", file=sys.stderr)
        return 1

    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "identity.json").write_text(json.dumps({"mac": args.mac}))
    (out / "pairing.json").write_text(json.dumps({
        "access_token": kv["access_token"],
        "refresh_token": kv["refresh_token"],
        "token_type": "device",
        "username": kv.get("username", ""),
        "api_url": kv.get("api_url", ""),
        "api_url_v2": kv.get("api_url_v2", ""),
        "noise_host": kv.get("noise_host", ""),
        "access_token_saved_at": int(time.time()),
    }, indent=2))
    for name in ("identity.json", "pairing.json"):
        (out / name).chmod(0o600)
    print("wrote", out / "identity.json", "and", out / "pairing.json")
    print("field lengths:", {k: (len(str(kv[k])) if k in kv else None) for k in FIELDS})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
