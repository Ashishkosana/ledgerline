"""Stage 2: the double-entry ledger and reconciliation."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app import ledger
from app.service import authorize, capture, create_payment, refund
from app.states import IllegalTransition


def _new_captured(session: Session, amount: int = 500) -> str:
    p = create_payment(session, key="create", amount_cents=amount)
    authorize(session, key="auth", payment_id=p.id)
    capture(session, key="cap", payment_id=p.id)
    return p.id


def test_capture_posts_balanced_entries(session: Session) -> None:
    _new_captured(session, amount=500)
    assert ledger.balance(session, "cash") == 500
    assert ledger.balance(session, "revenue") == -500
    assert ledger.reconcile(session) is True


def test_refund_reverses_the_posting(session: Session) -> None:
    pid = _new_captured(session, amount=500)
    refund(session, key="ref", payment_id=pid)
    assert ledger.balance(session, "cash") == 0
    assert ledger.balance(session, "revenue") == 0
    assert ledger.reconcile(session) is True


def test_capture_is_idempotent_for_the_ledger(session: Session) -> None:
    p = create_payment(session, key="create", amount_cents=500)
    authorize(session, key="auth", payment_id=p.id)
    capture(session, key="cap", payment_id=p.id)
    capture(session, key="cap", payment_id=p.id)  # replay with the SAME key
    assert ledger.balance(session, "cash") == 500  # posted once, not twice
    assert ledger.reconcile(session) is True


def test_capture_requires_authorize_first(session: Session) -> None:
    p = create_payment(session, key="create", amount_cents=500)
    with pytest.raises(IllegalTransition):
        capture(session, key="cap", payment_id=p.id)
    # a rejected op must not leave a partial ledger posting behind
    assert ledger.reconcile(session) is True
    assert ledger.balance(session, "cash") == 0


def test_unbalanced_posting_is_rejected(session: Session) -> None:
    with pytest.raises(ledger.UnbalancedTransaction):
        ledger.post(session, payment_id="x", entries=[("cash", 500), ("revenue", -400)])
