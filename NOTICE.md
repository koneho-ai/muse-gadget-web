# Notices

`app/musegadget/` is a vendored copy of the Linux client from the
[Muse Gadget SDK](https://github.com/facebookincubator/muse-gadget-sdk)
(Meta Platforms, Inc. and affiliates), Apache License 2.0 — see the
license headers in each file and `LICENSE` in this repository.

Local changes to the vendored code are marked `muse-gadget-web patch`:

- `service.py`: the executor may advertise its own command set via a
  `COMMAND_SPECS` attribute, and `Service.current_session` exposes the
  live `LinkSession` for the voice bridge.
- `cli.py` and `__main__.py` were dropped; entrypoints live in
  `app/webgadget/` (`main`, `pair_cli`).

Everything under `app/webgadget/`, `web/`, `tools/`, `tests/` and `docs/`
is original to this project, also Apache License 2.0.
