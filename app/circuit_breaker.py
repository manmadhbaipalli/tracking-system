"""Circuit breaker implementation for external service calls."""
import time
from enum import Enum
from typing import Any, Callable


class CircuitState(str, Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class CircuitBreakerError(Exception):
    """Raised when the circuit breaker is OPEN and calls are rejected."""


class CircuitBreaker:
    """
    Circuit breaker pattern implementation.

    States:
        CLOSED  -> normal operation; failures are counted.
        OPEN    -> calls are immediately rejected with a fallback.
        HALF_OPEN -> a single probe call is allowed to test recovery.
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        half_open_max_calls: int = 1,
    ) -> None:
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls

        self._state: CircuitState = CircuitState.CLOSED
        self._failure_count: int = 0
        self._success_count: int = 0
        self._last_failure_time: float | None = None
        self._half_open_calls: int = 0

    @property
    def state(self) -> CircuitState:
        if self._state == CircuitState.OPEN:
            if (
                self._last_failure_time is not None
                and (time.monotonic() - self._last_failure_time) >= self.recovery_timeout
            ):
                self._transition_to(CircuitState.HALF_OPEN)
        return self._state

    def _transition_to(self, new_state: CircuitState) -> None:
        self._state = new_state
        if new_state == CircuitState.CLOSED:
            self._failure_count = 0
            self._success_count = 0
            self._half_open_calls = 0
        elif new_state == CircuitState.HALF_OPEN:
            self._half_open_calls = 0

    def _on_success(self) -> None:
        if self._state == CircuitState.HALF_OPEN:
            self._success_count += 1
            if self._success_count >= self.half_open_max_calls:
                self._transition_to(CircuitState.CLOSED)
        else:
            self._failure_count = 0

    def _on_failure(self) -> None:
        self._failure_count += 1
        self._last_failure_time = time.monotonic()
        if self._state == CircuitState.HALF_OPEN:
            self._transition_to(CircuitState.OPEN)
        elif self._failure_count >= self.failure_threshold:
            self._transition_to(CircuitState.OPEN)

    def call(self, func: Callable, *args: Any, fallback: Any = None, **kwargs: Any) -> Any:
        """Execute *func* through the circuit breaker.

        If the circuit is OPEN, returns *fallback* (or raises CircuitBreakerError
        if no fallback is provided).

        Args:
            func: The callable to protect.
            *args: Positional arguments forwarded to *func*.
            fallback: Value returned when the circuit is OPEN.  If not provided
                and the circuit is OPEN, ``CircuitBreakerError`` is raised.
            **kwargs: Keyword arguments forwarded to *func*.

        Returns:
            The return value of *func*, or *fallback*.
        """
        current_state = self.state

        if current_state == CircuitState.OPEN:
            if fallback is not None:
                return fallback
            raise CircuitBreakerError(
                f"Circuit '{self.name}' is OPEN — service unavailable"
            )

        if current_state == CircuitState.HALF_OPEN:
            if self._half_open_calls >= self.half_open_max_calls:
                if fallback is not None:
                    return fallback
                raise CircuitBreakerError(
                    f"Circuit '{self.name}' is HALF_OPEN — probe limit reached"
                )
            self._half_open_calls += 1

        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result
        except Exception:
            self._on_failure()
            raise

    def reset(self) -> None:
        """Manually reset the circuit breaker to CLOSED state."""
        self._transition_to(CircuitState.CLOSED)
        self._last_failure_time = None
