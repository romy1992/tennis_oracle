"""In-process metrics with optional Prometheus text exposition (no vendor lock-in)."""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Iterable

# Providers: none | memory | prometheus (prometheus = memory + /metrics scrape)


@dataclass
class _Histogram:
    count: int = 0
    total: float = 0.0
    buckets: dict[float, int] = field(default_factory=dict)

    def observe(self, value: float, bounds: Iterable[float]) -> None:
        self.count += 1
        self.total += value
        for bound in bounds:
            if value <= bound:
                self.buckets[bound] = self.buckets.get(bound, 0) + 1


_DEFAULT_LATENCY_BUCKETS = (
    0.005,
    0.01,
    0.025,
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
    2.5,
    5.0,
    10.0,
    30.0,
    60.0,
    120.0,
    300.0,
    float("inf"),
)


class MetricsRegistry:
    """Thread-safe counters and histograms for API / bot / pipeline."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[tuple[str, tuple[tuple[str, str], ...]], float] = defaultdict(float)
        self._histograms: dict[tuple[str, tuple[tuple[str, str], ...]], _Histogram] = {}
        self._started_at = time.time()

    def incr(
        self,
        name: str,
        *,
        value: float = 1.0,
        labels: dict[str, str] | None = None,
    ) -> None:
        key = (name, _labels_key(labels))
        with self._lock:
            self._counters[key] += value

    def observe(
        self,
        name: str,
        value: float,
        *,
        labels: dict[str, str] | None = None,
        buckets: Iterable[float] = _DEFAULT_LATENCY_BUCKETS,
    ) -> None:
        key = (name, _labels_key(labels))
        with self._lock:
            hist = self._histograms.get(key)
            if hist is None:
                hist = _Histogram(buckets={b: 0 for b in buckets})
                self._histograms[key] = hist
            hist.observe(value, hist.buckets.keys())

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            counters = [
                {
                    "name": name,
                    "labels": dict(labels),
                    "value": value,
                }
                for (name, labels), value in sorted(self._counters.items(), key=lambda x: x[0][0])
            ]
            histograms = []
            for (name, labels), hist in sorted(self._histograms.items(), key=lambda x: x[0][0]):
                histograms.append(
                    {
                        "name": name,
                        "labels": dict(labels),
                        "count": hist.count,
                        "sum": round(hist.total, 6),
                        "buckets": {str(k): v for k, v in sorted(hist.buckets.items())},
                    }
                )
        return {
            "uptime_seconds": round(time.time() - self._started_at, 3),
            "counters": counters,
            "histograms": histograms,
        }

    def render_prometheus(self) -> str:
        """Prometheus text exposition format 0.0.4."""
        lines: list[str] = []
        snap = self.snapshot()
        lines.append("# HELP process_uptime_seconds Process uptime in seconds.")
        lines.append("# TYPE process_uptime_seconds gauge")
        lines.append(f"process_uptime_seconds {snap['uptime_seconds']}")

        seen_help: set[str] = set()
        for item in snap["counters"]:  # type: ignore[index]
            name = str(item["name"])
            if name not in seen_help:
                lines.append(f"# HELP {name} Counter.")
                lines.append(f"# TYPE {name} counter")
                seen_help.add(name)
            lines.append(f"{name}{_prom_labels(item['labels'])} {item['value']}")

        seen_hist: set[str] = set()
        for item in snap["histograms"]:  # type: ignore[index]
            name = str(item["name"])
            if name not in seen_hist:
                lines.append(f"# HELP {name} Histogram.")
                lines.append(f"# TYPE {name} histogram")
                seen_hist.add(name)
            labels = dict(item["labels"])
            # buckets already store cumulative counts (observations <= bound).
            for bound_str, count in sorted(
                item["buckets"].items(),
                key=lambda kv: float(kv[0]),
            ):
                bound = float(bound_str)
                le = "+Inf" if bound == float("inf") else f"{bound:g}"
                bucket_labels = {**labels, "le": le}
                lines.append(f"{name}_bucket{_prom_labels(bucket_labels)} {int(count)}")
            lines.append(f"{name}_sum{_prom_labels(labels)} {item['sum']}")
            lines.append(f"{name}_count{_prom_labels(labels)} {item['count']}")
        return "\n".join(lines) + "\n"


def _labels_key(labels: dict[str, str] | None) -> tuple[tuple[str, str], ...]:
    if not labels:
        return ()
    return tuple(sorted((str(k), str(v)) for k, v in labels.items()))


def _prom_labels(labels: dict[str, str] | object) -> str:
    if not isinstance(labels, dict) or not labels:
        return ""
    parts = []
    for key, value in sorted(labels.items()):
        escaped = (
            str(value)
            .replace("\\", "\\\\")
            .replace("\n", "\\n")
            .replace('"', '\\"')
        )
        parts.append(f'{key}="{escaped}"')
    return "{" + ",".join(parts) + "}"


_REGISTRY = MetricsRegistry()
_PROVIDER = "memory"


def configure_metrics(provider: str = "memory") -> None:
    global _PROVIDER
    _PROVIDER = (provider or "none").strip().lower()


def metrics_enabled() -> bool:
    return _PROVIDER in {"memory", "prometheus"}


def metrics_provider() -> str:
    return _PROVIDER


def get_metrics() -> MetricsRegistry:
    return _REGISTRY


def record_counter(
    name: str,
    *,
    value: float = 1.0,
    labels: dict[str, str] | None = None,
) -> None:
    if not metrics_enabled():
        return
    _REGISTRY.incr(name, value=value, labels=labels)


def record_histogram(
    name: str,
    value: float,
    *,
    labels: dict[str, str] | None = None,
) -> None:
    if not metrics_enabled():
        return
    _REGISTRY.observe(name, value, labels=labels)
