"""Phase 1 — Tests for retry.py.

TDD: These tests define the contract. Implementation in cathedral_keeper/retry.py
must satisfy all of them.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cathedral_keeper.retry import RetryFailure, retry_call


# ── Success Cases ────────────────────────────────────────────────────


def test_retry_succeeds_on_first_try():
    """If fn() succeeds immediately, return its result — no retry."""
    calls = []

    def fn():
        calls.append(1)
        return "ok"

    result = retry_call(fn, max_retries=2)
    assert result == "ok"
    assert len(calls) == 1


def test_retry_returns_actual_value():
    """Return value should be the exact object fn() returns."""
    result = retry_call(lambda: {"data": [1, 2, 3]}, max_retries=1)
    assert result == {"data": [1, 2, 3]}


def test_retry_returns_empty_dict_as_success():
    """Empty dict {} from fn() is a valid success — NOT a failure."""
    result = retry_call(lambda: {}, max_retries=1)
    assert result == {}
    assert not isinstance(result, RetryFailure)


def test_retry_returns_none_as_success():
    """None from fn() is a valid success — NOT a failure."""
    result = retry_call(lambda: None, max_retries=1)
    assert result is None
    assert not isinstance(result, RetryFailure)


# ── Transient Error Recovery ─────────────────────────────────────────


def test_retry_recovers_on_transient_error():
    """Should retry on transient errors and succeed if fn() recovers."""
    attempts = []

    def fn():
        attempts.append(1)
        if len(attempts) < 3:
            raise OSError("connection reset")
        return "recovered"

    result = retry_call(fn, max_retries=3, base_delay=0.01)
    assert result == "recovered"
    assert len(attempts) == 3


def test_retry_recovers_on_timeout():
    """TimeoutError is transient by default."""
    attempts = []

    def fn():
        attempts.append(1)
        if len(attempts) == 1:
            raise TimeoutError("timed out")
        return "ok"

    result = retry_call(fn, max_retries=2, base_delay=0.01)
    assert result == "ok"
    assert len(attempts) == 2


# ── Exhaustion Cases ─────────────────────────────────────────────────


def test_retry_returns_failure_after_exhaustion():
    """If all retries fail, return RetryFailure — never return {} or []."""
    def fn():
        raise OSError("persistent failure")

    result = retry_call(fn, max_retries=2, base_delay=0.01)
    assert isinstance(result, RetryFailure)
    assert result.attempts == 3  # initial + 2 retries
    assert "persistent failure" in result.last_error


def test_retry_failure_contains_error_info():
    """RetryFailure should carry enough info to diagnose the problem."""
    def fn():
        raise ConnectionError("refused")

    result = retry_call(fn, max_retries=1, base_delay=0.01,
                        transient_exceptions=(ConnectionError,))
    assert isinstance(result, RetryFailure)
    assert "ConnectionError" in result.last_error
    assert "refused" in result.last_error


# ── Non-Transient Errors ─────────────────────────────────────────────


def test_retry_no_retry_on_non_transient():
    """Non-transient exceptions should fail immediately without retry."""
    attempts = []

    def fn():
        attempts.append(1)
        raise ValueError("bad input")

    result = retry_call(fn, max_retries=3, base_delay=0.01)
    assert isinstance(result, RetryFailure)
    assert len(attempts) == 1  # no retries
    assert "ValueError" in result.last_error


def test_retry_custom_transient_exceptions():
    """Only configured exception types should be retried."""
    attempts = []

    class CustomTransient(Exception):
        pass

    def fn():
        attempts.append(1)
        if len(attempts) < 3:
            raise CustomTransient("temporary")
        return "ok"

    result = retry_call(
        fn, max_retries=3, base_delay=0.01,
        transient_exceptions=(CustomTransient,),
    )
    assert result == "ok"
    assert len(attempts) == 3


# ── Edge Cases ───────────────────────────────────────────────────────


def test_retry_zero_retries():
    """max_retries=0 means try once, no retries."""
    def fn():
        raise OSError("fail")

    result = retry_call(fn, max_retries=0, base_delay=0.01)
    assert isinstance(result, RetryFailure)
    assert result.attempts == 1


def test_retry_failure_is_distinguishable_from_dict():
    """RetryFailure must be distinguishable from any valid return type."""
    failure = RetryFailure(attempts=1, last_error="test")
    assert not isinstance(failure, dict)
    assert not isinstance(failure, list)
    assert isinstance(failure, RetryFailure)


# ── Runner ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    passed = 0
    failed = 0
    tests = [
        (name, obj)
        for name, obj in sorted(globals().items())
        if name.startswith("test_") and callable(obj)
    ]
    for name, fn in tests:
        try:
            fn()
            passed += 1
            print(f"  PASS  {name}")
        except AssertionError as e:
            failed += 1
            print(f"  FAIL  {name}: {e}")
        except Exception as e:
            failed += 1
            print(f"  ERROR {name}: {e}")

    print(f"\n{passed} passed, {failed} failed out of {len(tests)} tests")
    raise SystemExit(1 if failed else 0)
