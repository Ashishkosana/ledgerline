"""The payment state machine.  >>> YOU IMPLEMENT THIS (Stage 1 core, part 1). <<<

A payment moves through a fixed lifecycle. Illegal jumps must be rejected.

    created ──authorize──▶ authorized ──capture──▶ captured ──refund──▶ refunded
       │                        │
       └────────fail───────────┴──────────fail──────────▶ failed

`refunded` and `failed` are terminal: nothing follows them.

Contract the tests hold you to (see tests/test_state_machine.py):
  - PaymentState: the five states below (given).
  - ALLOWED: fill in {state -> set of states reachable in ONE step}.
  - assert_transition(current, target): return None if the move is allowed,
    else raise IllegalTransition. Examples that MUST raise:
      created  -> captured    (never authorized)
      authorized -> refunded  (never captured)
      refunded -> captured    (terminal)
"""

from __future__ import annotations

import enum


class IllegalTransition(Exception):
    """Raised when a payment is asked to make a move the FSM forbids."""


class PaymentState(str, enum.Enum):
    CREATED = "created"
    AUTHORIZED = "authorized"
    CAPTURED = "captured"
    REFUNDED = "refunded"
    FAILED = "failed"


# The allowed one-step transitions, read straight off the diagram above.
# Terminal states (refunded, failed) have no outgoing arrows -> empty set.
ALLOWED: dict[PaymentState, set[PaymentState]] = {
    PaymentState.CREATED: {PaymentState.AUTHORIZED, PaymentState.FAILED},
    PaymentState.AUTHORIZED: {PaymentState.CAPTURED, PaymentState.FAILED},
    PaymentState.CAPTURED: {PaymentState.REFUNDED},
    PaymentState.REFUNDED: set(),
    PaymentState.FAILED: set(),
}


def assert_transition(current: PaymentState, target: PaymentState) -> None:
    """Return None if `current -> target` is allowed, else raise IllegalTransition."""
    if target not in ALLOWED[current]:
        raise IllegalTransition(f"{current.value} -> {target.value} is not allowed")
