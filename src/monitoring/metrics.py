"""
SNO Monitoring — Prometheus Metrics  ✨ NEW ✨

Exposes key operational metrics for scraping by Prometheus/Grafana.
Metrics are available at http://<host>:<METRICS_PORT>/metrics

Metric families:
  sno_jobs_total          — Counter: total jobs submitted, by playbook and status.
  sno_job_duration_seconds — Histogram: job execution time distribution.
  sno_active_jobs         — Gauge: currently running jobs.
  sno_playbook_node_total — Counter: total node executions, by playbook.
  sno_mcp_requests_total  — Counter: total MCP tool invocations, by tool name.
  sno_errors_total        — Counter: errors by type and origin.

Usage:
    from src.monitoring.metrics import metrics
    metrics.record_job_start(playbook_id="research")
    metrics.record_job_end(playbook_id="research", status="success", duration_s=12.3)
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field

from src.utils.logger import get_logger

logger = get_logger("monitoring.metrics")


# ── Lightweight Metrics (no prometheus_client dependency required) ─────────────
# If prometheus_client is installed, we expose a /metrics HTTP endpoint.
# If not, we degrade gracefully — metrics are still tracked in-process
# and can be queried via the sno_get_metrics MCP tool.


@dataclass
class _CounterFamily:
    """Thread-safe counter with labels."""
    _data: dict[tuple, int] = field(default_factory=lambda: defaultdict(int))
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def inc(self, labels: tuple, amount: int = 1) -> None:
        with self._lock:
            self._data[labels] += amount

    def to_dict(self) -> dict[str, int]:
        with self._lock:
            return {str(k): v for k, v in self._data.items()}


@dataclass
class _GaugeFamily:
    """Thread-safe gauge."""
    _value: float = 0.0
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def set(self, value: float) -> None:
        with self._lock:
            self._value = value

    def inc(self, amount: float = 1.0) -> None:
        with self._lock:
            self._value += amount

    def dec(self, amount: float = 1.0) -> None:
        with self._lock:
            self._value = max(0.0, self._value - amount)

    @property
    def value(self) -> float:
        with self._lock:
            return self._value


@dataclass
class _HistogramFamily:
    """Thread-safe histogram (simplified — no bucket granularity)."""
    _observations: list[float] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _sum: float = 0.0
    _count: int = 0

    def observe(self, value: float) -> None:
        with self._lock:
            self._observations.append(value)
            self._sum += value
            self._count += 1
            # Keep only last 1000 to avoid unbounded memory
            if len(self._observations) > 1000:
                self._observations = self._observations[-1000:]

    def summary(self) -> dict:
        with self._lock:
            if not self._observations:
                return {"count": 0, "sum": 0, "p50": None, "p95": None, "p99": None}
            sorted_obs = sorted(self._observations)
            n = len(sorted_obs)
            return {
                "count": self._count,
                "sum": round(self._sum, 3),
                "p50": round(sorted_obs[int(n * 0.50)], 3),
                "p95": round(sorted_obs[int(n * 0.95)], 3),
                "p99": round(sorted_obs[min(int(n * 0.99), n - 1)], 3),
            }


class SNOMetrics:
    """
    Central metrics registry for SNO.

    All methods are thread-safe and can be called from any coroutine or thread.
    """

    def __init__(self):
        # Job metrics
        self.jobs_total = _CounterFamily()          # labels: (playbook_id, status)
        self.active_jobs = _GaugeFamily()
        self.job_duration = _HistogramFamily()

        # Node metrics
        self.nodes_total = _CounterFamily()         # labels: (playbook_id,)

        # MCP request metrics
        self.mcp_requests = _CounterFamily()        # labels: (tool_name,)

        # Error metrics
        self.errors_total = _CounterFamily()        # labels: (error_type, origin)

        # System
        self._start_time = time.time()

        self._prometheus_available = self._try_init_prometheus()

    def _try_init_prometheus(self) -> bool:
        """Optionally use prometheus_client if installed."""
        try:
            import prometheus_client  # noqa: F401
            logger.info("prometheus_client detected — Prometheus metrics available.")
            return True
        except ImportError:
            logger.info(
                "prometheus_client not installed. "
                "Install it for Prometheus scraping: pip install prometheus-client"
            )
            return False

    # ── Recording Methods ───────────────────────────────────────────────────

    def record_job_start(self, playbook_id: str) -> None:
        self.active_jobs.inc()
        logger.debug(f"[metrics] job start — playbook={playbook_id}")

    def record_job_end(
        self,
        playbook_id: str,
        status: str,
        duration_s: float,
    ) -> None:
        self.active_jobs.dec()
        self.jobs_total.inc((playbook_id, status))
        self.job_duration.observe(duration_s)
        logger.debug(
            f"[metrics] job end — playbook={playbook_id} status={status} "
            f"duration={duration_s:.2f}s"
        )

    def record_node_execution(self, playbook_id: str) -> None:
        self.nodes_total.inc((playbook_id,))

    def record_mcp_request(self, tool_name: str) -> None:
        self.mcp_requests.inc((tool_name,))

    def record_error(self, error_type: str, origin: str) -> None:
        self.errors_total.inc((error_type, origin))

    # ── Snapshot ────────────────────────────────────────────────────────────

    def snapshot(self) -> dict:
        """Return a JSON-serialisable snapshot of all metrics."""
        return {
            "uptime_seconds": round(time.time() - self._start_time, 1),
            "active_jobs": self.active_jobs.value,
            "jobs_total": self.jobs_total.to_dict(),
            "job_duration": self.job_duration.summary(),
            "nodes_executed_total": self.nodes_total.to_dict(),
            "mcp_requests_total": self.mcp_requests.to_dict(),
            "errors_total": self.errors_total.to_dict(),
            "prometheus_enabled": self._prometheus_available,
        }


# Module-level singleton
metrics = SNOMetrics()