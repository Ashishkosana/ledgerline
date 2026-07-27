"""A tiny in-process metrics counter.

Real deployments push these to Prometheus/OpenTelemetry; here it is a plain counter
so the pipeline is observable and the numbers are assertable in tests. `reset` exists
so each test starts from zero.
"""

from __future__ import annotations

from collections import Counter

_counters: Counter[str] = Counter()


def incr(name: str, n: int = 1) -> None:
    _counters[name] += n


def snapshot() -> dict[str, int]:
    return dict(_counters)


def reset() -> None:
    _counters.clear()
