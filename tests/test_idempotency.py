"""The storage-layer idempotency contract. RED until app/service.py is implemented."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import Payment
from app.service import create_payment


def _count(session: Session) -> int:
    return session.query(Payment).count()


def test_create_payment_persists(session: Session) -> None:
    p = create_payment(session, key="k1", amount_cents=500, currency="USD")
    assert p.state == "created"
    assert p.amount_cents == 500
    assert _count(session) == 1


def test_replayed_key_does_not_double_create(session: Session) -> None:
    a = create_payment(session, key="k1", amount_cents=500, currency="USD")
    b = create_payment(session, key="k1", amount_cents=500, currency="USD")
    # Same key -> same payment, and exactly one row exists.
    assert a.id == b.id
    assert _count(session) == 1


def test_distinct_keys_create_distinct_payments(session: Session) -> None:
    create_payment(session, key="k1", amount_cents=500, currency="USD")
    create_payment(session, key="k2", amount_cents=700, currency="USD")
    assert _count(session) == 2
