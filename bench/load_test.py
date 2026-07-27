"""Load + concurrency harness.

Two things it proves:
  1. No double-charge: fire N concurrent, identical (same idempotency key) requests
     and assert exactly ONE payment is created.
  2. Throughput: create M distinct payments across a thread pool and report
     payments/sec plus p50/p95 latency.

Run against Postgres for real row-level concurrency:

    docker compose up -d db
    LEDGERLINE_DB=postgresql+psycopg://ledgerline:ledgerline@localhost:5432/ledgerline \
        python bench/load_test.py
"""

from __future__ import annotations

import os
import statistics
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, func, select  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app import models  # noqa: E402,F401  (registers tables)
from app.db import Base  # noqa: E402
from app.models import Payment  # noqa: E402
from app.service import create_payment  # noqa: E402

URL = os.environ.get("LEDGERLINE_DB", "sqlite:///bench.db")
_kw = {"pool_size": 30, "max_overflow": 60} if not URL.startswith("sqlite") else {}
engine = create_engine(URL, future=True, **_kw)
Session = sessionmaker(bind=engine, expire_on_commit=False)


def _reset() -> None:
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)


def _one_create(key: str, amount: int = 500) -> float:
    session = Session()
    try:
        start = time.perf_counter()
        create_payment(session, key=key, amount_cents=amount)
        return time.perf_counter() - start
    finally:
        session.close()


def prove_no_double_charge(concurrency: int = 200) -> None:
    _reset()
    key = "same-" + uuid.uuid4().hex
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        list(pool.map(lambda _: _one_create(key), range(concurrency)))
    with Session() as s:
        count = s.scalar(select(func.count()).select_from(Payment))
    print(f"[no-double-charge] {concurrency} concurrent identical requests -> {count} payment(s)")
    assert count == 1, f"DOUBLE CHARGE DETECTED: {count} payments created!"


def measure_throughput(total: int = 1000, concurrency: int = 20) -> None:
    _reset()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        start = time.perf_counter()
        latencies_ms = [d * 1000 for d in pool.map(lambda i: _one_create(f"k{i}"), range(total))]
        elapsed = time.perf_counter() - start
    latencies_ms.sort()
    p50 = statistics.median(latencies_ms)
    p95 = latencies_ms[int(len(latencies_ms) * 0.95) - 1]
    print(
        f"[throughput] {total} payments in {elapsed:.2f}s -> {total / elapsed:.0f}/s "
        f"| p50 {p50:.1f}ms p95 {p95:.1f}ms"
    )


if __name__ == "__main__":
    print(f"DB: {URL}")
    prove_no_double_charge(200)
    measure_throughput(1000, 20)
    print("OK - zero double-charges, throughput measured")
