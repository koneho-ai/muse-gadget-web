# muse-gadget-web: a Muse gadget in Docker whose screen/speaker is a browser.
#
# The runtime never touches Bluetooth (pairing is a separate step — see
# docs/bluetooth.md), so the image needs no D-Bus at runtime; python3-dbus
# and python3-gi are present only so the `pair` profile can run the SDK's
# BlueZ pairing on a Linux Docker host that has Bluetooth.
#
# The venv uses --system-site-packages for the same reason the SDK's own
# installer does: dbus/gi/cryptography come from the distro.
FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update -qq \
 && apt-get install -y -qq --no-install-recommends \
      python3 python3-venv python3-pip python3-dbus python3-gi \
      python3-cryptography ca-certificates \
 && rm -rf /var/lib/apt/lists/*

COPY app /srv/app
COPY web /srv/web

RUN python3 -m venv --system-site-packages /opt/venv \
 && /opt/venv/bin/pip install --quiet --no-cache-dir -r /srv/app/requirements.txt

ENV PYTHONPATH=/srv/app \
    WEB_DIR=/srv/web \
    MUSEGADGET_STATE_DIR=/state \
    WEB_PORT=8321 \
    PYTHONUNBUFFERED=1
VOLUME ["/state"]
EXPOSE 8321

# No shell/file commands exist in this gadget, so unlike the stock Linux
# gadget there is no unprivileged command account to isolate; the process
# only holds the device credentials in /state (mode 0700 files).
ENTRYPOINT ["/opt/venv/bin/python", "-m", "webgadget"]
