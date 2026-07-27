"""Transactional outbox + relay.

The dual-write problem: if you commit a payment to the DB and THEN publish an event
to a broker as two separate steps, a crash in between leaves the money moved but the
event lost. The outbox fixes this: the event row is written in the SAME transaction
as the business change, so it exists if and only if that change committed.

A relay then reads unpublished rows and publishes them, marking each sent. Delivery
is at-least-once -- a crash after publish but before marking re-delivers on restart --
which the consumer's inbox (see app/consumer.py) dedups into effectively-once.
"""

from __future__ import annotations

import json
from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import OutboxEvent

Event = dict[str, object]


def enqueue(session: Session, *, event_type: str, payload: dict[str, object]) -> None:
    """Stage an event in the outbox. Does not commit; the caller's transaction does,
    so the event and the business change are atomic.
    """
    session.add(OutboxEvent(event_type=event_type, payload_json=json.dumps(payload)))


def relay(session: Session, publish: Callable[[Event], None]) -> int:
    """Publish every unpublished outbox row in order; return how many were delivered."""
    rows = session.scalars(
        select(OutboxEvent).where(OutboxEvent.published.is_(False)).order_by(OutboxEvent.id)
    ).all()
    delivered = 0
    for row in rows:
        event: Event = {
            "id": str(row.id),
            "type": row.event_type,
            "payload": json.loads(row.payload_json),
        }
        publish(event)  # if this or the process dies here, the row stays unpublished
        row.published = True
        session.commit()  # mark sent only after a successful publish
        delivered += 1
    return delivered
