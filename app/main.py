"""FastAPI web server: puts HTTP endpoints in front of the payment service.

Run it:
    uvicorn app.main:app --reload

Then open http://localhost:8000/docs in your browser to try the endpoints.
The endpoints call into app/service.py, so they start working once that is
implemented (until then, POST /payments returns a 500 NotImplementedError).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import service
from app.db import get_session, init_db
from app.models import Payment
from app.states import IllegalTransition


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    init_db()  # create the tables on startup
    yield


app = FastAPI(title="ledgerline", description="Exactly-once payments service", lifespan=lifespan)


@app.exception_handler(IllegalTransition)
async def _illegal(_: Request, exc: IllegalTransition) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": str(exc)})


class CreatePaymentIn(BaseModel):
    amount_cents: int
    currency: str = "USD"


class PaymentOut(BaseModel):
    id: str
    amount_cents: int
    currency: str
    state: str


def _out(p: Payment) -> PaymentOut:
    return PaymentOut(id=p.id, amount_cents=p.amount_cents, currency=p.currency, state=p.state)


@app.post("/payments", response_model=PaymentOut)
def create_payment(
    body: CreatePaymentIn,
    idempotency_key: str = Header(...),
    session: Session = Depends(get_session),
) -> PaymentOut:
    p = service.create_payment(
        session, key=idempotency_key, amount_cents=body.amount_cents, currency=body.currency
    )
    return _out(p)


@app.get("/payments/{payment_id}", response_model=PaymentOut)
def get_payment(payment_id: str, session: Session = Depends(get_session)) -> PaymentOut:
    p = session.get(Payment, payment_id)
    if p is None:
        raise HTTPException(status_code=404, detail="payment not found")
    return _out(p)


@app.post("/payments/{payment_id}/{action}", response_model=PaymentOut)
def transition(
    payment_id: str,
    action: str,
    idempotency_key: str = Header(...),
    session: Session = Depends(get_session),
) -> PaymentOut:
    actions: dict[str, Callable[..., Payment]] = {
        "authorize": service.authorize,
        "capture": service.capture,
        "refund": service.refund,
    }
    fn = actions.get(action)
    if fn is None:
        raise HTTPException(status_code=404, detail=f"unknown action: {action}")
    return _out(fn(session, key=idempotency_key, payment_id=payment_id))
