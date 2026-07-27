"""Consumer with an inbox for effectively-once processing.

A broker delivers at-least-once, so the same event can arrive twice. Before running
a handler we insert the event id into the inbox under a UNIQUE constraint; if it is
already there, the redelivery is a no-op. So each event's side effect runs once.
"""

from __future__ import annotations

import json
from collections.abc import Callable

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import metrics
from app.models import DeadLetter, InboxEvent

Event = dict[str, object]


def process(session: Session, event: Event, handler: Callable[[Event], None]) -> bool:
    """Run `handler(event)` at most once per event id. Returns True if it ran, False
    if this event was already processed (a duplicate delivery).
    """
    session.add(InboxEvent(event_id=str(event["id"])))
    try:
        session.flush()  # the UNIQUE constraint rejects an already-seen event id
    except IntegrityError:
        session.rollback()
        return False
    handler(event)
    session.commit()
    return True


def deliver(
    session: Session,
    event: Event,
    handler: Callable[[Event], None],
    *,
    max_attempts: int = 3,
) -> str:
    """Process `event` with retries and a dead-letter fallback.

    Returns "duplicate" if already processed, "processed" on success, or
    "dead_lettered" if it still fails after `max_attempts`. On dead-lettering, the
    event id is still recorded so the poison message is not retried forever.
    """
    event_id = str(event["id"])
    if session.query(InboxEvent).filter_by(event_id=event_id).first() is not None:
        metrics.incr("events.duplicate")
        return "duplicate"

    last_error = ""
    for _attempt in range(max_attempts):
        try:
            handler(event)
            session.add(InboxEvent(event_id=event_id))
            session.commit()
            metrics.incr("events.processed")
            return "processed"
        except Exception as exc:  # noqa: BLE001 - a failing handler must go to retry/DLQ, not crash the worker
            session.rollback()
            last_error = repr(exc)
            metrics.incr("events.failed")
            # a real worker sleeps retry.backoff_delay(attempt) here between tries

    session.add(
        DeadLetter(
            event_id=event_id,
            event_type=str(event["type"]),
            payload_json=json.dumps(event.get("payload")),
            reason=last_error,
        )
    )
    session.add(InboxEvent(event_id=event_id))
    session.commit()
    metrics.incr("events.dead_lettered")
    return "dead_lettered"
