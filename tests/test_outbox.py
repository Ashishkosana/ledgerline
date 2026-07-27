"""Stage 3: transactional outbox, relay, and consumer inbox dedup."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app import consumer, outbox
from app.models import OutboxEvent
from app.outbox import Event
from app.service import authorize, capture, create_payment


def _capture(session: Session, amount: int = 500) -> str:
    p = create_payment(session, key="create", amount_cents=amount)
    authorize(session, key="auth", payment_id=p.id)
    capture(session, key="cap", payment_id=p.id)
    return p.id


def _pending(session: Session) -> int:
    return session.query(OutboxEvent).filter_by(published=False).count()


def test_capture_writes_outbox_event_atomically(session: Session) -> None:
    _capture(session)
    # The event landed in the same commit as the state change + ledger rows.
    assert _pending(session) == 1


def test_relay_publishes_then_marks_sent(session: Session) -> None:
    _capture(session)
    delivered: list[Event] = []
    assert outbox.relay(session, delivered.append) == 1
    assert delivered[0]["type"] == "payment.captured"
    # A second relay finds nothing new -- publishing is not repeated.
    assert outbox.relay(session, delivered.append) == 0
    assert len(delivered) == 1


def test_crash_before_publish_does_not_lose_the_event(session: Session) -> None:
    _capture(session)
    # Simulate a crash: the business transaction committed, but the relay never ran.
    assert _pending(session) == 1
    # On restart the relay still finds and delivers it -- nothing is lost.
    delivered: list[Event] = []
    outbox.relay(session, delivered.append)
    assert len(delivered) == 1
    assert _pending(session) == 0


def test_consumer_dedups_a_redelivered_event(session: Session) -> None:
    _capture(session)
    events: list[Event] = []
    outbox.relay(session, events.append)
    handled: list[Event] = []
    assert consumer.process(session, events[0], handled.append) is True  # first delivery
    assert consumer.process(session, events[0], handled.append) is False  # duplicate
    assert len(handled) == 1  # the side effect ran exactly once
