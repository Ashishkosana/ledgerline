# ledgerline

A payments backend that stays **correct under failure**: it never charges a
customer twice on a retry, and never loses track of a payment when a downstream
step fails. The failure-handling machinery that Stripe usually hides is built
here from scratch.

## Demo

![ledgerline API (Swagger UI)](docs/api.png)

Idempotency in action -- the same `Idempotency-Key` sent twice returns the *same*
payment, so a retried request never double-charges:

```text
POST /payments  key=demoA  -> {"id":"91d5c520...","amount_cents":500,"state":"created"}
POST /payments  key=demoA  -> {"id":"91d5c520...","amount_cents":500,"state":"created"}   # same key -> SAME payment
POST /payments  key=demoB  -> {"id":"17b9e1ac...","amount_cents":500,"state":"created"}   # new key  -> new payment
```

## The problem it solves

Money software has two classic failure modes:

1. **The double-charge.** A client's network stalls, the app retries, and the
   customer is charged twice for one purchase.
2. **The lost payment (dual-write problem).** The database saves the payment, but
   the follow-up event ("email the receipt, notify shipping") fails to publish, so
   the money moved and the rest of the system never heard about it.

`ledgerline` builds the protection against both, from first principles.

## What it does

- **Payment state machine** — a payment moves `created → authorized → captured →
  refunded` (or `failed`), and illegal jumps are rejected. You cannot refund a
  payment that was never captured.
- **Storage-layer idempotency** — every request carries an idempotency key; the
  database's UNIQUE constraint refuses the same key twice. A retry is handed back
  the original payment instead of creating a second one. The database is the
  referee, so even two identical requests racing at the same instant charge once.

## Architecture

```
app/
  db.py       connection + session (plumbing)
  models.py   tables: payments, idempotency_keys (plumbing)
  states.py   the state machine (the rules)
  service.py  create/authorize/capture/refund + idempotency (the logic)
  main.py     FastAPI web server (the /docs API)
tests/        automated proof the logic is correct
```

Data flows `db → models → states → service → main`.

## Build stages

- **Stage 1 — payment state machine + storage-layer idempotency.** ✅ Done.
  12 tests, `mypy --strict` clean, `ruff` clean.
- **Stage 2 — double-entry ledger + reconciliation.** ✅ Done. Capture/refund post
  balanced debit/credit rows inside the same transaction; balances are derived by
  summing the ledger, and `reconcile()` proves the whole ledger sums to zero.
- **Stage 3 — transactional outbox + relay + consumer inbox dedup.** ✅ Done. The
  event row is written in the same transaction as the business change; a relay
  publishes unpublished rows; the consumer dedups redeliveries via a UNIQUE inbox.
  A chaos test asserts a crash between commit and publish loses nothing.
- **Stage 4 — dead-letter queue, backoff, observability + load/chaos benchmarks.**
  ✅ Done. A retry-aware consumer dead-letters poison messages after N attempts,
  exponential backoff with jitter spaces retries, and a metrics counter makes the
  pipeline observable.

## Benchmarks (Postgres, `bench/load_test.py`)

```
no-double-charge : 200 concurrent identical requests -> 1 payment created
throughput       : 1000 payments in 0.69s -> ~1460/s, p50 13ms, p95 20ms
```

Run them yourself:

```bash
docker compose up -d db     # Postgres on host port 5433
LEDGERLINE_DB="postgresql+psycopg://ledgerline:ledgerline@localhost:5433/ledgerline" \
    python bench/load_test.py
```

## Run

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

pytest                          # prove the logic (all green)
uvicorn app.main:app --reload   # run the server -> http://localhost:8000/docs
```

Try the idempotency live: `POST /payments` twice with the same `Idempotency-Key`
header and watch the same payment come back.

## Stack

Python 3.12, FastAPI, SQLAlchemy 2.0, Pydantic v2. SQLite for local dev; Postgres
(via `docker-compose.yml`) for the concurrency demo. Typed, tested, CI-ready.
