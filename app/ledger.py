"""Double-entry ledger.

Every movement of money is recorded as a set of balanced rows whose signed amounts
sum to zero (positive = debit, negative = credit). Account balances are DERIVED by
summing the ledger, never stored directly, so the books are auditable and
self-correcting. `reconcile` proves the whole ledger still sums to zero.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import LedgerEntry


class UnbalancedTransaction(Exception):
    """Raised when a posting's debits and credits do not cancel to zero."""


def post(session: Session, *, payment_id: str, entries: list[tuple[str, int]]) -> str:
    """Stage a balanced posting. Does NOT commit; the caller's transaction owns that,
    so the money movement and the payment state change land together or not at all.
    """
    if sum(amount for _, amount in entries) != 0:
        raise UnbalancedTransaction(f"entries do not sum to zero: {entries}")
    txn_id = uuid.uuid4().hex
    for account, amount in entries:
        session.add(
            LedgerEntry(txn_id=txn_id, payment_id=payment_id, account=account, amount_cents=amount)
        )
    return txn_id


def balance(session: Session, account: str) -> int:
    """Current balance of an account, derived by summing its ledger rows."""
    total = session.scalar(
        select(func.coalesce(func.sum(LedgerEntry.amount_cents), 0)).where(
            LedgerEntry.account == account
        )
    )
    return int(total or 0)


def reconcile(session: Session) -> bool:
    """True if the whole ledger balances (all signed amounts sum to zero)."""
    total = session.scalar(select(func.coalesce(func.sum(LedgerEntry.amount_cents), 0)))
    return int(total or 0) == 0
