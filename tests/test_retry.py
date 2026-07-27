"""Stage 4: backoff math, retries, dead-letter queue, and metrics."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy.orm import Session

from app import consumer, metrics, outbox
from app.models import DeadLetter
from app.outbox import Event
from app.retry import backoff_delay
from app.service import authorize, capture, create_payment


@pytest.fixture(autouse=True)
def _reset_metrics() -> Iterator[None]:
    metrics.reset()
    yield
    metrics.reset()


def _first_event(session: Session) -> Event:
    p = create_payment(session, key="create", amount_cents=500)
    authorize(session, key="auth", payment_id=p.id)
    capture(session, key="cap", payment_id=p.id)
    events: list[Event] = []
    outbox.relay(session, events.append)
    return events[0]


def test_backoff_is_exponential_and_capped() -> None:
    assert backoff_delay(1, base=0.1, factor=2.0) == pytest.approx(0.1)
    assert backoff_delay(2, base=0.1, factor=2.0) == pytest.approx(0.2)
    assert backoff_delay(3, base=0.1, factor=2.0) == pytest.approx(0.4)
    assert backoff_delay(10, base=0.1, factor=2.0, cap=1.0) == pytest.approx(1.0)


def test_backoff_jitter_adds_a_fraction() -> None:
    assert backoff_delay(1, base=1.0, jitter=0.5) == pytest.approx(1.5)


def test_deliver_processes_on_success(session: Session) -> None:
    event = _first_event(session)
    handled: list[Event] = []
    assert consumer.deliver(session, event, handled.append) == "processed"
    assert len(handled) == 1
    assert metrics.snapshot().get("events.processed") == 1


def test_deliver_recovers_after_a_transient_failure(session: Session) -> None:
    event = _first_event(session)
    calls = {"n": 0}

    def flaky(_: Event) -> None:
        calls["n"] += 1
        if calls["n"] < 2:
            raise RuntimeError("transient")

    assert consumer.deliver(session, event, flaky, max_attempts=3) == "processed"
    assert calls["n"] == 2
    assert metrics.snapshot().get("events.failed") == 1


def test_deliver_dead_letters_after_max_attempts(session: Session) -> None:
    event = _first_event(session)

    def always_fail(_: Event) -> None:
        raise RuntimeError("boom")

    assert consumer.deliver(session, event, always_fail, max_attempts=3) == "dead_lettered"
    assert session.query(DeadLetter).count() == 1
    assert metrics.snapshot().get("events.failed") == 3
    assert metrics.snapshot().get("events.dead_lettered") == 1


def test_deliver_dedups_a_duplicate(session: Session) -> None:
    event = _first_event(session)
    consumer.deliver(session, event, lambda _: None)
    handled: list[Event] = []
    assert consumer.deliver(session, event, handled.append) == "duplicate"
    assert handled == []
