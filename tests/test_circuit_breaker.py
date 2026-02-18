"""Tests for the CircuitBreaker implementation."""
import time

import pytest

from app.circuit_breaker import CircuitBreaker, CircuitBreakerError, CircuitState


def _failing():
    raise RuntimeError("service down")


def _succeeding(value=42):
    return value


# ---------------------------------------------------------------------------
# Basic state machine
# ---------------------------------------------------------------------------

class TestCircuitBreakerStates:
    def test_initial_state_is_closed(self):
        cb = CircuitBreaker("svc", failure_threshold=3)
        assert cb.state == CircuitState.CLOSED

    def test_successful_call_stays_closed(self):
        cb = CircuitBreaker("svc", failure_threshold=3)
        result = cb.call(_succeeding)
        assert result == 42
        assert cb.state == CircuitState.CLOSED

    def test_failures_below_threshold_stays_closed(self):
        cb = CircuitBreaker("svc", failure_threshold=3)
        for _ in range(2):
            with pytest.raises(RuntimeError):
                cb.call(_failing)
        assert cb.state == CircuitState.CLOSED

    def test_failures_at_threshold_opens_circuit(self):
        cb = CircuitBreaker("svc", failure_threshold=3)
        for _ in range(3):
            with pytest.raises(RuntimeError):
                cb.call(_failing)
        assert cb.state == CircuitState.OPEN

    def test_open_circuit_raises_without_fallback(self):
        cb = CircuitBreaker("svc", failure_threshold=1)
        with pytest.raises(RuntimeError):
            cb.call(_failing)
        assert cb.state == CircuitState.OPEN

        with pytest.raises(CircuitBreakerError):
            cb.call(_succeeding)

    def test_open_circuit_returns_fallback(self):
        cb = CircuitBreaker("svc", failure_threshold=1)
        with pytest.raises(RuntimeError):
            cb.call(_failing)

        result = cb.call(_succeeding, fallback="fallback_value")
        assert result == "fallback_value"

    def test_success_resets_failure_count(self):
        cb = CircuitBreaker("svc", failure_threshold=3)
        for _ in range(2):
            with pytest.raises(RuntimeError):
                cb.call(_failing)
        # Successful call should reset the counter
        cb.call(_succeeding)
        # Two more failures should still be within threshold
        for _ in range(2):
            with pytest.raises(RuntimeError):
                cb.call(_failing)
        assert cb.state == CircuitState.CLOSED


# ---------------------------------------------------------------------------
# Half-open state transitions
# ---------------------------------------------------------------------------

class TestHalfOpenState:
    def _open_circuit(self, cb: CircuitBreaker) -> None:
        for _ in range(cb.failure_threshold):
            with pytest.raises(RuntimeError):
                cb.call(_failing)
        assert cb.state == CircuitState.OPEN

    def test_transitions_to_half_open_after_timeout(self):
        cb = CircuitBreaker("svc", failure_threshold=1, recovery_timeout=0.05)
        self._open_circuit(cb)
        time.sleep(0.06)
        # Accessing .state should trigger the HALF_OPEN transition
        assert cb.state == CircuitState.HALF_OPEN

    def test_half_open_success_closes_circuit(self):
        cb = CircuitBreaker("svc", failure_threshold=1, recovery_timeout=0.05)
        self._open_circuit(cb)
        time.sleep(0.06)
        cb.call(_succeeding)
        assert cb.state == CircuitState.CLOSED

    def test_half_open_failure_reopens_circuit(self):
        cb = CircuitBreaker("svc", failure_threshold=1, recovery_timeout=0.05)
        self._open_circuit(cb)
        time.sleep(0.06)
        with pytest.raises(RuntimeError):
            cb.call(_failing)
        assert cb.state == CircuitState.OPEN

    def test_half_open_probe_limit(self):
        """Extra calls in HALF_OPEN state should use fallback or raise."""
        cb = CircuitBreaker(
            "svc",
            failure_threshold=1,
            recovery_timeout=0.05,
            half_open_max_calls=1,
        )
        self._open_circuit(cb)
        time.sleep(0.06)
        assert cb.state == CircuitState.HALF_OPEN

        # First probe call is allowed
        cb.call(_succeeding)  # This closes the circuit
        assert cb.state == CircuitState.CLOSED


# ---------------------------------------------------------------------------
# Manual reset
# ---------------------------------------------------------------------------

class TestCircuitBreakerReset:
    def test_manual_reset_closes_circuit(self):
        cb = CircuitBreaker("svc", failure_threshold=1)
        with pytest.raises(RuntimeError):
            cb.call(_failing)
        assert cb.state == CircuitState.OPEN

        cb.reset()
        assert cb.state == CircuitState.CLOSED

    def test_after_reset_failures_counted_fresh(self):
        cb = CircuitBreaker("svc", failure_threshold=2)
        with pytest.raises(RuntimeError):
            cb.call(_failing)
        cb.reset()
        # One failure after reset should not open (threshold=2)
        with pytest.raises(RuntimeError):
            cb.call(_failing)
        assert cb.state == CircuitState.CLOSED


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

class TestCircuitBreakerConfig:
    def test_custom_failure_threshold(self):
        cb = CircuitBreaker("svc", failure_threshold=5)
        for _ in range(4):
            with pytest.raises(RuntimeError):
                cb.call(_failing)
        assert cb.state == CircuitState.CLOSED
        with pytest.raises(RuntimeError):
            cb.call(_failing)
        assert cb.state == CircuitState.OPEN

    def test_fallback_value_none_raises(self):
        cb = CircuitBreaker("svc", failure_threshold=1)
        with pytest.raises(RuntimeError):
            cb.call(_failing)
        # No fallback → must raise CircuitBreakerError
        with pytest.raises(CircuitBreakerError):
            cb.call(_succeeding)

    def test_call_returns_function_result(self):
        cb = CircuitBreaker("svc")
        assert cb.call(_succeeding, 99) == 99

    def test_call_passes_kwargs(self):
        cb = CircuitBreaker("svc")
        assert cb.call(_succeeding, value=77) == 77
