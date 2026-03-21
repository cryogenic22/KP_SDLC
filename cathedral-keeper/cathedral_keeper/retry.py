"""Phase 1 — Retry wrapper for external calls.

Pattern from CtxPack's _retry_api_call. All subprocess/API calls in CK
and QG should use this to handle transient failures (e.g., QG subprocess
crash, git timeout) without silently returning empty results.

Key design decision: on final failure, returns a sentinel that callers
MUST check — never returns {} or [] which look like "no findings."
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable, Optional, TypeVar

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class RetryFailure:
    """Sentinel that distinguishes 'call failed' from 'call returned empty'.

    Callers must check:
        result = retry_call(fn)
        if isinstance(result, RetryFailure):
            # handle failure — do NOT treat as "no findings"
    """

    attempts: int
    last_error: str


def retry_call(
    fn: Callable[[], T],
    *,
    max_retries: int = 2,
    base_delay: float = 0.5,
    transient_exceptions: tuple = (OSError, TimeoutError, ConnectionError),
) -> T | RetryFailure:
    """Call fn() with exponential backoff on transient errors.

    Args:
        fn: Zero-argument callable to retry.
        max_retries: Maximum number of retries after first failure.
        base_delay: Base delay in seconds (doubles each retry).
        transient_exceptions: Exception types considered transient.

    Returns:
        The result of fn() on success, or RetryFailure on exhaustion.
    """
    last_err = ""
    for attempt in range(max_retries + 1):
        try:
            return fn()
        except transient_exceptions as e:
            last_err = f"{type(e).__name__}: {e}"
            if attempt < max_retries:
                time.sleep(base_delay * (2 ** attempt))
        except Exception as e:
            # Non-transient error — don't retry
            return RetryFailure(attempts=attempt + 1, last_error=f"{type(e).__name__}: {e}")

    return RetryFailure(attempts=max_retries + 1, last_error=last_err)
