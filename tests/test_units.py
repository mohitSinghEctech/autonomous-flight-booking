"""Small pure pieces: no server, no database."""
import base64
import hashlib
import hmac

from app.api.events import SSEEvent
from app.api.sessions import apply_event, empty_state
from app.models import PaymentStatus
from app.providers.flights.duffel import parse_iso_duration
from app.providers.payment.cashfree import CashfreePaymentProvider, parse_webhook, to_payment_status


def test_sse_framing_is_one_line_of_json_and_a_blank_line():
    text = SSEEvent(event="status", data={"busy": True, "text": "a\nb"}, event_id=7).to_sse()
    assert text == 'id: 7\nevent: status\ndata: {"busy":true,"text":"a\\nb"}\n\n'


def test_duffel_durations():
    assert parse_iso_duration("PT3H29M") == 209
    assert parse_iso_duration("P1DT2H") == 1560
    assert parse_iso_duration("PT45M") == 45
    assert parse_iso_duration(None) is None
    assert parse_iso_duration("nonsense") is None


def test_cashfree_status_mapping():
    assert to_payment_status("SUCCESS") == PaymentStatus.PAID
    assert to_payment_status("PENDING") == PaymentStatus.PENDING
    assert to_payment_status("NOT_ATTEMPTED") == PaymentStatus.CREATED
    assert to_payment_status("USER_DROPPED") == PaymentStatus.FAILED
    assert to_payment_status(None) == PaymentStatus.FAILED


def test_cashfree_webhook_signature(monkeypatch):
    monkeypatch.setenv("CASHFREE_API_KEY", "secret")
    provider = CashfreePaymentProvider()
    raw, ts = b'{"a":1}', "1700000000"
    good = base64.b64encode(hmac.new(b"secret", ts.encode() + raw, hashlib.sha256).digest()).decode()

    assert provider.verify_webhook(raw, ts, good)
    assert not provider.verify_webhook(raw, ts, "forged")
    assert not provider.verify_webhook(raw + b" ", ts, good)            # body tampered


def test_parse_webhook_builds_a_stable_event_id():
    payload = {"type": "PAYMENT_SUCCESS_WEBHOOK",
               "data": {"order": {"order_id": "o1"}, "payment": {"cf_payment_id": 9, "payment_status": "SUCCESS"}}}
    event = parse_webhook(payload)
    assert event == {"order_id": "o1", "status": PaymentStatus.PAID,
                     "event_id": "PAYMENT_SUCCESS_WEBHOOK:9", "event_type": "PAYMENT_SUCCESS_WEBHOOK"}


def test_projection_follows_events_like_the_ui_reducer():
    state = empty_state()
    apply_event(state, "message", {"id": "c1", "role": "user", "text": "hi"})
    apply_event(state, "turn.started", {"turn_id": "t1", "title": "hi"})
    apply_event(state, "step", {"id": "s1", "turn_id": "t1", "title": "Searching", "status": "running"})
    apply_event(state, "step", {"id": "s1", "status": "done"})                       # partial update
    apply_event(state, "approval.required", {"approval_id": "a1", "kind": "book"})
    apply_event(state, "approval.resolved", {"approval_id": "other", "decision": "approved"})
    assert state["approval"]["approval_id"] == "a1"                                  # only its own id clears it
    apply_event(state, "approval.resolved", {"approval_id": "a1", "decision": "approved"})

    assert state["approval"] is None
    assert state["steps"] == [{"id": "s1", "turn_id": "t1", "title": "Searching", "status": "done"}]
    assert state["timeline"] == [{"type": "msg", "id": "c1"}, {"type": "turn", "id": "t1"}]
