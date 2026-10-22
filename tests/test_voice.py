"""Voice bridge acknowledgement handling.

Regression test: LinkSession wraps the chat acknowledgement as
{"ok", "status", "response"}; MuseTurn.acknowledge expects the body.
Passing the wrapper made every /say fail with "Muse chat
acknowledgement omitted the user message ID".
"""

import pytest

from webgadget.voice import _ack_body


def test_ack_body_unwraps_link_session_response():
    body = {"message_id": "m1", "session_id": "s1"}
    assert _ack_body({"ok": True, "status": 200, "response": body}) == body


def test_ack_body_unwraps_result_shaped_body():
    body = {"result": {"message_id": "m1"}}
    assert _ack_body({"ok": True, "status": 200, "response": body}) == body


@pytest.mark.parametrize("response", [
    {"ok": True, "status": 200, "response": None},
    {"ok": True, "status": 200, "response": "not a dict"},
    {"ok": True, "status": 200},
])
def test_ack_body_rejects_unreadable_responses(response):
    assert _ack_body(response) is None


# -- dedicated side chat wiring -------------------------------------------------

import asyncio

from webgadget.screen import ScreenState
from webgadget.voice import VoiceBridge

SID = "3f6f1b2c-0000-5000-8000-000000000001"  # UUID-shaped, like real chat ids
CANONICAL_SID = SID  # the server honours the requested id (observed live)


class FakeSession:
    registered_at = 1.0

    def __init__(self):
        self.sent = []
        self.subscribed_with = "unset"

    async def send_chat(self, message, session_id=None, *, output_modality=None):
        self.sent.append((message, session_id, output_modality))
        return {"ok": True, "status": 200,
                "response": {"message_id": "u1", "session_id": CANONICAL_SID}}

    async def subscribe_chat(self, session_id=None):
        self.subscribed_with = session_id
        events = [
            {"type": "event", "event": "delta.message_start",
             "payload": {"session_id": CANONICAL_SID, "message_id": "a1", "reply_to_message_id": "u1"}},
            {"type": "event", "event": "delta.text_append",
             "payload": {"session_id": CANONICAL_SID, "message_id": "a1", "text": "Hello there"}},
            {"type": "event", "event": "delta.message_done",
             "payload": {"session_id": CANONICAL_SID, "message_id": "a1"}},
            {"type": "event", "event": "task.status",
             "payload": {"session_id": CANONICAL_SID, "status": "completed", "reply_to_message_id": "u1"}},
        ]
        for event in events:
            yield event
        await asyncio.sleep(3600)  # stream stays open; the bridge cancels the pump

    async def stream_tts(self, message_id):
        yield b"fake-mp3"


def test_turn_uses_dedicated_side_chat():
    session = FakeSession()
    bridge = VoiceBridge(lambda: session, ScreenState(), chat_session_id=SID)

    async def run():
        return await asyncio.wait_for(bridge.say_text("hi"), 10)

    result = asyncio.run(run())
    assert result["ok"] is True
    assert result["reply"] == "Hello there"
    assert result["audio_id"] is not None
    assert session.sent == [("hi", SID, "voice")]
    # The subscription is scoped to the gadget's dedicated chat.
    assert session.subscribed_with == SID
