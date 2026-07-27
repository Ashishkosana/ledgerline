"""Payment service: drives the state machine and makes every mutating call
idempotent at the storage layer.

Idempotency mechanism (_idempotent): reserve the Idempotency-Key row FIRST, guarded
by a UNIQUE constraint. If the key already exists, the insert fails and we return the
payment the first request produced WITHOUT re-running the work. If the key is new, we
run the work in the same transaction and record which payment it produced. So a retry
never repeats the side effect, and an operation that raises never burns its key.

Money movements are posted to a double-entry ledger (app.ledger) inside that same
transaction, so a captured payment and its ledger rows commit together or not at all.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import ledger, outbox
from app.models import IdempotencyKey, Payment
from app.states import PaymentState, assert_transition


def _idempotent(session: Session, key: str, work: Callable[[], Payment]) -> Payment:
    """Run `work` (which mutates and returns a Payment) exactly once per `key`."""
    marker = IdempotencyKey(key=key, response_json="")
    session.add(marker)
    try:
        session.flush()  # force the INSERT now; a duplicate key raises here
    except IntegrityError:
        session.rollback()
        prior = session.query(IdempotencyKey).filter_by(key=key).one()
        payment_id = json.loads(prior.response_json)["payment_id"]
        return session.query(Payment).filter_by(id=payment_id).one()

    try:
        payment = work()
        marker.response_json = json.dumps({"payment_id": payment.id})
        session.commit()
        return payment
    except Exception:
        session.rollback()
        raise


def _load(session: Session, payment_id: str) -> Payment:
    return session.query(Payment).filter_by(id=payment_id).one()


def create_payment(
    session: Session, *, key: str, amount_cents: int, currency: str = "USD"
) -> Payment:
    """Create a payment in state 'created', idempotent on `key`."""

    def work() -> Payment:
        payment = Payment(
            id=uuid.uuid4().hex,
            amount_cents=amount_cents,
            currency=currency,
            state=PaymentState.CREATED.value,
        )
        session.add(payment)
        return payment

    return _idempotent(session, key, work)


def authorize(session: Session, *, key: str, payment_id: str) -> Payment:
    """created -> authorized."""

    def work() -> Payment:
        payment = _load(session, payment_id)
        assert_transition(PaymentState(payment.state), PaymentState.AUTHORIZED)
        payment.state = PaymentState.AUTHORIZED.value
        return payment

    return _idempotent(session, key, work)


def capture(session: Session, *, key: str, payment_id: str) -> Payment:
    """authorized -> captured. Posts the money into the ledger (debit cash, credit revenue)."""

    def work() -> Payment:
        payment = _load(session, payment_id)
        assert_transition(PaymentState(payment.state), PaymentState.CAPTURED)
        payment.state = PaymentState.CAPTURED.value
        ledger.post(
            session,
            payment_id=payment.id,
            entries=[("cash", payment.amount_cents), ("revenue", -payment.amount_cents)],
        )
        outbox.enqueue(
            session,
            event_type="payment.captured",
            payload={"payment_id": payment.id, "amount_cents": payment.amount_cents},
        )
        return payment

    return _idempotent(session, key, work)


def refund(session: Session, *, key: str, payment_id: str) -> Payment:
    """captured -> refunded. Reverses the ledger posting."""

    def work() -> Payment:
        payment = _load(session, payment_id)
        assert_transition(PaymentState(payment.state), PaymentState.REFUNDED)
        payment.state = PaymentState.REFUNDED.value
        ledger.post(
            session,
            payment_id=payment.id,
            entries=[("cash", -payment.amount_cents), ("revenue", payment.amount_cents)],
        )
        outbox.enqueue(
            session,
            event_type="payment.refunded",
            payload={"payment_id": payment.id, "amount_cents": payment.amount_cents},
        )
        return payment

    return _idempotent(session, key, work)
