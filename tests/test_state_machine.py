"""The payment FSM contract. RED until app/states.py is implemented."""

from __future__ import annotations

import pytest

from app.states import IllegalTransition, assert_transition
from app.states import PaymentState as S


def test_created_can_authorize() -> None:
    assert_transition(S.CREATED, S.AUTHORIZED)  # must not raise


def test_authorized_can_capture() -> None:
    assert_transition(S.AUTHORIZED, S.CAPTURED)


def test_captured_can_refund() -> None:
    assert_transition(S.CAPTURED, S.REFUNDED)


def test_created_can_fail() -> None:
    assert_transition(S.CREATED, S.FAILED)


def test_authorized_can_fail() -> None:
    assert_transition(S.AUTHORIZED, S.FAILED)


def test_cannot_capture_without_authorizing() -> None:
    with pytest.raises(IllegalTransition):
        assert_transition(S.CREATED, S.CAPTURED)


def test_cannot_refund_without_capturing() -> None:
    with pytest.raises(IllegalTransition):
        assert_transition(S.AUTHORIZED, S.REFUNDED)


def test_cannot_leave_terminal_refunded() -> None:
    with pytest.raises(IllegalTransition):
        assert_transition(S.REFUNDED, S.CAPTURED)


def test_cannot_leave_terminal_failed() -> None:
    with pytest.raises(IllegalTransition):
        assert_transition(S.FAILED, S.AUTHORIZED)
