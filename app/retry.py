"""Retry backoff.

When a consumer fails, retrying immediately just hammers a struggling dependency.
Exponential backoff spaces retries out (0.1s, 0.2s, 0.4s, ...) up to a cap, and
jitter spreads a fleet of retriers so they don't all wake at the same instant (the
"thundering herd"). The jitter fraction is passed in so this stays a pure, testable
function -- the caller supplies the randomness.
"""

from __future__ import annotations


def backoff_delay(
    attempt: int, *, base: float = 0.1, factor: float = 2.0, cap: float = 30.0, jitter: float = 0.0
) -> float:
    """Seconds to wait before retry `attempt` (1-based). Exponential, capped, plus an
    optional jitter fraction of the delay.
    """
    raw = min(base * (factor ** (attempt - 1)), cap)
    return raw + raw * jitter
