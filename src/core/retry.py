"""
SNO Retry & Circuit Breaker — v2.0

Provides two primitives for fault-tolerant agentic node execution:

1. `retry_async` — decorator: exponential backoff + jitter for transient errors.
2. `CircuitBreaker` — stateful guard: stops hammering a failing external service.

Circuit Breaker states:
  CLOSED   → normal operation; tracks consecutive failures.
  OPEN     → all requests fail immediately; waits reset_timeout seconds.
  HALF_OPEN → sends ONE probe; if it succeeds → CLOSED, else → OPEN again.
"""
from __future__ import annotations

import asyncio
import dataclasses
import functools
import random
import time
from enum import Enum
from typing import Callable

from src.utils.logger import get_logger

logger = get_logger("core.retry")


# ── Circuit Breaker ─────────────────────────────────────────────────────────

class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclasses.dataclass
class CircuitBreaker:
    """
    Thread-safe* circuit breaker for protecting external integrations.

    (*asyncio-safe; not multi-thread-safe without an additional lock.)

    Args:
        name:               Identifier shown in logs.
        failure_threshold:  Consecutive failures before tripping OPEN.
        success_threshold:  Consecutive successes in HALF_OPEN before closing.
        reset_timeout:      Seconds to remain OPEN before probing (HALF_OPEN).
    """
    name: str
    failure_threshold: int = 5
    success_threshold: int = 2
    reset_timeout: float = 60.0

    _state: CircuitState = dataclasses.field(default=CircuitState.CLOSED, init=False)
    _failure_count: int = dataclasses.field(default=0, init=False)
    _success_count: int = dataclasses.field(default=0, init=False)
    _last_failure_time: float = dataclasses.field(default=0.0, init=False)

    @property
    def state(self) -> CircuitState:
        if (
            self._state == CircuitState.OPEN
            and time.monotonic() - self._last_failure_time >= self.reset_timeout
        ):
            logger.info(f"[{self.name}] → HALF_OPEN (probing recovery)")
            self._state = CircuitState.HALF_OPEN
        return self._state

    def is_allowed(self) -> bool:
        return self.state in (CircuitState.CLOSED, CircuitState.HALF_OPEN)

    def record_success(self) -> None:
        self._failure_count = 0
        if self._state == CircuitState.HALF_OPEN:
            self._success_count += 1
            if self._success_count >= self.success_threshold:
                logger.info(f"[{self.name}] → CLOSED (service recovered)")
                self._state = CircuitState.CLOSED
                self._success_count = 0

    def record_failure(self) -> None:
        self._failure_count += 1
        self._last_failure_time = time.monotonic()
        if (
            self._state == CircuitState.HALF_OPEN
            or self._failure_count >= self.failure_threshold
        ):
            logger.warning(
                f"[{self.name}] → OPEN "
                f"({self._failure_count} failures ≥ threshold {self.failure_threshold})"
            )
            self._state = CircuitState.OPEN
            self._failure_count = 0
            self._success_count = 0

    def reset(self) -> None:
        """Manually reset to CLOSED — useful in tests."""
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time = 0.0

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "state": self.state.value,
            "failure_count": self._failure_count,
            "failure_threshold": self.failure_threshold,
            "reset_timeout": self.reset_timeout,
        }


# ── Retry Decorator ──────────────────────────────────────────────────────────

def retry_async(
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    jitter: bool = True,
    exceptions: tuple[type[Exception], ...] = (Exception,),
    circuit_breaker: CircuitBreaker | None = None,
) -> Callable:
    """
    Async retry decorator with exponential backoff and optional circuit breaker.

    Args:
        max_attempts:    Maximum total attempts (1 = run once, no retry).
        base_delay:      Delay before second attempt (seconds).
        max_delay:       Hard ceiling on delay (seconds).
        jitter:          Multiply delay by a random factor in [0.75, 1.25].
        exceptions:      Only retry on these exception types.
        circuit_breaker: If provided, blocks calls when circuit is OPEN.

    Example:
        cb = CircuitBreaker(name="neo4j", failure_threshold=3)

        @retry_async(max_attempts=5, exceptions=(neo4j.exceptions.ServiceUnavailable,), circuit_breaker=cb)
        async def query_graph(cypher: str) -> list:
            ...
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            if circuit_breaker and not circuit_breaker.is_allowed():
                raise RuntimeError(
                    f"[CircuitBreaker:{circuit_breaker.name}] OPEN — request rejected"
                )

            last_exc: Exception | None = None
            for attempt in range(1, max_attempts + 1):
                try:
                    result = await func(*args, **kwargs)
                    if circuit_breaker:
                        circuit_breaker.record_success()
                    return result
                except exceptions as exc:
                    last_exc = exc
                    if circuit_breaker:
                        circuit_breaker.record_failure()

                    if attempt == max_attempts:
                        logger.error(
                            f"[{func.__qualname__}] All {max_attempts} attempts failed — "
                            f"giving up. Last error: {exc!r}"
                        )
                        break

                    delay = min(base_delay * (2 ** (attempt - 1)), max_delay)
                    if jitter:
                        delay *= 0.75 + random.random() * 0.5

                    logger.warning(
                        f"[{func.__qualname__}] Attempt {attempt}/{max_attempts} failed "
                        f"({exc!r}). Retrying in {delay:.2f}s…"
                    )
                    await asyncio.sleep(delay)

            raise last_exc  # type: ignore[misc]

        return wrapper
    return decorator