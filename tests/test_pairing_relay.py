"""End-to-end pairing over the relay transport, minus the actual Bluetooth.

A scripted "Muse app" client speaks the real pairing protocol v5
(plaintext hello, ECDH + HKDF transcript keys, AES-GCM records) through
the chunk framing, into PairingRelaySession — the exact controller the
container runs for /pairing/ws. Provisioning is stubbed (no real device
tokens exist in a test); everything else is the production code path.
"""

import hashlib
import json

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from musegadget import pairing as P
from musegadget.ble_framing import ChunkAssembler, encode_chunks
from musegadget.identity import Identity
from webgadget.pairing_ws import PairingRelaySession

_TO_DEVICE = 0
_FROM_DEVICE = 1


class FakeMobile:
    """The Muse app's side of pairing, for tests."""

    def __init__(self, session: PairingRelaySession, packets: list) -> None:
        self.session = session
        self.assembler = ChunkAssembler()
        self.packets = packets      # device->mobile pipe, appended by send_sync
        self._cursor = 0
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.nonce = bytes(range(16))
        self.tx_counter = 0
        self.rx_counter = 0

    # -- transport -----------------------------------------------------------

    def send_message(self, data: bytes) -> None:
        for packet in encode_chunks(data, mtu=256):
            self.session.on_packet(packet)

    def poll(self, timeout: float = 5.0) -> list[bytes]:
        """Collect complete device->mobile messages since the last poll.

        The controller answers from its own worker thread, so wait for
        the pipe to deliver.
        """
        import time
        deadline = time.time() + timeout
        messages = []
        while True:
            while self._cursor < len(self.packets):
                packet = self.packets[self._cursor]
                self._cursor += 1
                message = self.assembler.feed(packet)
                if message is not None:
                    messages.append(message)
            if messages or time.time() >= deadline:
                return messages
            time.sleep(0.02)

    # -- protocol ------------------------------------------------------------

    def hello(self) -> dict:
        pub = self.key.public_key().public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
        self.send_message(json.dumps({
            "action": "pairing_client_hello",
            "version": P.PAIRING_VERSION,
            "pairing_auth": P.AUTH_COMMUNITY,
            "pairing_policy": P.POLICY_APP,
            "mobile_pub": P.b64url_encode(pub),
            "mobile_nonce": P.b64url_encode(self.nonce),
        }).encode())
        raw = self.poll()[0]
        ready = json.loads(raw)
        assert ready["type"] == "pairing_ready"
        transcript = P.build_transcript(
            community=True, auth_epoch=0, policy=P.POLICY_APP,
            device_id=ready["device_id"], node_id=ready["node_id"], mac=ready["mac"],
            firmware_version=ready["firmware_version"],
            mobile_pub=P.b64url_encode(pub),
            device_pub=ready["device_pub"],
            mobile_nonce=P.b64url_encode(self.nonce),
            device_nonce=ready["device_nonce"],
        )
        transcript_hash = hashlib.sha256(transcript.encode()).digest()
        assert P.b64url_encode(transcript_hash) == ready["transcript_hash"]
        device_pub = ec.EllipticCurvePublicKey.from_encoded_point(
            ec.SECP256R1(), P.b64url_decode(ready["device_pub"]))
        ecdh = ec.ECDH()
        shared = self.key.exchange(ecdh, device_pub)
        self.k_tx, self.k_rx, session_id = P.derive_session_keys(
            shared, self.nonce, P.b64url_decode(ready["device_nonce"]), transcript_hash)
        self.session_id = P.b64url_encode(session_id)
        assert self.session_id == ready["session_id"]
        return ready

    def send_encrypted(self, obj: dict) -> None:
        plaintext = json.dumps(obj, separators=(",", ":")).encode()
        sealed = AESGCM(self.k_tx).encrypt(
            P.record_nonce(_TO_DEVICE, self.tx_counter), plaintext,
            P.record_aad(self.session_id, _TO_DEVICE, self.tx_counter))
        envelope = {
            "action": "pairing_encrypted",
            "session_id": self.session_id,
            "counter": str(self.tx_counter),
            "ciphertext": P.b64url_encode(sealed[:-16]),
            "tag": P.b64url_encode(sealed[-16:]),
        }
        self.tx_counter += 1
        self.send_message(json.dumps(envelope).encode())

    def receive_statuses(self) -> list[str]:
        statuses = []
        for raw in self.poll():
            envelope = json.loads(raw)
            assert envelope["type"] == "pairing_encrypted"
            counter = int(envelope["counter"])
            assert counter == self.rx_counter
            self.rx_counter += 1
            plain = AESGCM(self.k_rx).decrypt(
                P.record_nonce(_FROM_DEVICE, counter),
                P.b64url_decode(envelope["ciphertext"]) + P.b64url_decode(envelope["tag"]),
                P.record_aad(self.session_id, _FROM_DEVICE, counter))
            statuses.append(json.loads(plain)["status"])
        return statuses


def test_pairing_over_relay_transport():
    received = {}

    def stub_provision(credentials, commit):
        received["credentials"] = credentials
        assert commit(lambda: True)

    class Net:
        is_online = staticmethod(lambda: True)
        current_connection_entry = staticmethod(lambda: {"ssid": "TestNet", "rssi": -40, "secure": False})

    packets: list[bytes] = []
    session = PairingRelaySession(
        identity=Identity("02:11:22:33:44:55"),
        sdk_token=None,
        send_sync=packets.append,
        provision=stub_provision,
        network=Net,
    )
    session.start()
    mobile = FakeMobile(session, packets)

    ready = mobile.hello()
    assert ready["node_id"] == "homelink-334455"

    mobile.send_encrypted({"action": "pairing_client_finished"})
    assert mobile.receive_statuses() == ["pairing_confirmed"]

    mobile.send_encrypted({
        "action": "provision_v2",
        "ssid": "TestNet", "password": "ignored-by-design",
        "access_token": "fake-access", "refresh_token": "fake-refresh",
        "token_type": "device", "username": "tester",
        "api_url": "", "api_url_v2": "", "noise_host": "",
    })
    statuses = mobile.receive_statuses()
    assert statuses == ["wifi_connecting", "wifi_connected", "auth_ok"], statuses
    assert session.completed
    creds = received["credentials"]
    assert creds.access_token == "fake-access"
    assert creds.refresh_token == "fake-refresh"
    session.stop()
