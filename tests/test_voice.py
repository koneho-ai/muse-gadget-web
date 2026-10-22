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
