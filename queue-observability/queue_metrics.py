"""Synchronous, completion-only queue timing using real OpenTelemetry metrics.

Synthetic console demo; no queue server, concurrency, or network exporter.
Timestamps must share one monotonic clock domain and be expressed in seconds.
Validation is strict: invalid observations raise before any metric is written.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from typing import TypeVar

from opentelemetry.metrics import Meter
from opentelemetry.sdk.metrics import Counter, Histogram, MeterProvider
from opentelemetry.sdk.metrics.export import (
    AggregationTemporality,
    Histogram as HistogramData,
    InMemoryMetricReader,
    MetricsData,
    Sum,
)
from opentelemetry.sdk.resources import Resource


RESIDENCE = "sample.queue.residence"
PROCESSING = "sample.handler.duration"
COMPLETED = "sample.work.completed"
OUTCOMES = frozenset({"success", "failure"})
T = TypeVar("T")


def _timestamp(value: float, name: str) -> float:
    # bool is an int subclass but is not a meaningful clock reading.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number of seconds")
    try:
        converted = float(value)
    except OverflowError as error:
        raise ValueError(f"{name} is outside the supported numeric range") from error
    if not math.isfinite(converted):
        raise ValueError(f"{name} must be finite")
    # The epoch is arbitrary: a negative timestamp is not a negative duration.
    return converted


def _duration(start: float, end: float, name: str) -> float:
    duration = end - start
    if not math.isfinite(duration) or duration < 0:
        raise ValueError(f"{name} must be finite and non-negative")
    return duration


class QueueRecorder:
    """Record completed attempts, not all submissions or all handler starts.

    The caller owns enqueue timestamps and must record each attempt once.
    This class deliberately accepts no queue name, job ID, or custom labels.
    """

    def __init__(
        self, meter: Meter, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._clock = clock
        self._residence = meter.create_histogram(
            RESIDENCE,
            unit="s",
            description="Enqueue-to-start elapsed time for completed attempts only.",
        )
        self._processing = meter.create_histogram(
            PROCESSING,
            unit="s",
            description="Start-to-finish elapsed time for completed attempts only.",
        )
        self._completed = meter.create_counter(
            COMPLETED,
            unit="{attempt}",
            description="Completed handler attempts by bounded outcome.",
        )

    def mark_enqueued(self) -> float:
        """Capture an accepted enqueue boundary; emit no metric."""
        return _timestamp(self._clock(), "enqueued_at")

    def record_completion(
        self,
        *,
        enqueued_at: float,
        started_at: float,
        finished_at: float,
        outcome: str,
    ) -> None:
        """Validate all inputs, then emit two histograms and one counter.

        Invalid inputs cause no writes. The three SDK calls are not a
        transaction; an SDK failure or interrupted process can partially emit.
        """
        if type(outcome) is not str or outcome not in OUTCOMES:
            raise ValueError("outcome must be 'success' or 'failure'")
        enqueued = _timestamp(enqueued_at, "enqueued_at")
        started = _timestamp(started_at, "started_at")
        finished = _timestamp(finished_at, "finished_at")
        residence = _duration(enqueued, started, "queue residence")
        processing = _duration(started, finished, "handler duration")

        attributes = {"outcome": outcome}
        self._residence.record(residence, attributes=attributes)
        self._processing.record(processing, attributes=attributes)
        self._completed.add(1, attributes=attributes)

    def run(self, enqueued_at: float, handler: Callable[[], T]) -> T:
        """Run one synchronous attempt and propagate its return or Exception.

        Ordinary Exception means failure; BaseException interruptions are
        excluded. Telemetry failures propagate on success; during handler
        failure the original handler error wins, with telemetry error as cause.
        Do not pass async functions or generators: their work is deferred.
        """
        enqueued = _timestamp(enqueued_at, "enqueued_at")
        started = _timestamp(self._clock(), "started_at")
        _duration(enqueued, started, "queue residence")
        try:
            result = handler()
        except Exception as handler_error:
            try:
                finished = self._clock()
                self.record_completion(
                    enqueued_at=enqueued,
                    started_at=started,
                    finished_at=finished,
                    outcome="failure",
                )
            except Exception as instrumentation_error:
                raise handler_error from instrumentation_error
            raise
        else:
            finished = self._clock()
            self.record_completion(
                enqueued_at=enqueued,
                started_at=started,
                finished_at=finished,
                outcome="success",
            )
            return result


def make_local_provider() -> tuple[MeterProvider, InMemoryMetricReader]:
    """Build an isolated SDK pipeline, without global state or an exporter."""
    reader = InMemoryMetricReader(
        preferred_temporality={
            Counter: AggregationTemporality.CUMULATIVE,
            Histogram: AggregationTemporality.CUMULATIVE,
        }
    )
    provider = MeterProvider(
        metric_readers=[reader],
        resource=Resource({"service.name": "queue-observability-sample"}),
        shutdown_on_exit=False,
    )
    return provider, reader


def format_summary(data: MetricsData | None) -> list[str]:
    """Present bounded aggregates; omit nondeterministic SDK timestamps."""
    lines = []
    if data is None:
        return lines
    for resource in data.resource_metrics:
        for scope in resource.scope_metrics:
            for metric in scope.metrics:
                for point in metric.data.data_points:
                    outcome = point.attributes["outcome"]
                    prefix = f"{metric.name} outcome={outcome}"
                    if isinstance(metric.data, HistogramData):
                        lines.append(
                            f"{prefix} count={point.count} sum={point.sum:.3f}s"
                        )
                    elif isinstance(metric.data, Sum):
                        lines.append(f"{prefix} value={point.value}")
    return sorted(lines)


def main() -> None:
    # Each completed attempt consumes enqueue, start, and finish readings.
    readings = iter(
        (100.0, 102.0, 102.5, 200.0, 200.0, 201.0, 300.0, 303.0, 303.25, 400.0)
    )
    provider, reader = make_local_provider()
    try:
        recorder = QueueRecorder(
            provider.get_meter("queue-observability.sample", "1.0.0"),
            clock=lambda: next(readings),
        )
        recorder.run(recorder.mark_enqueued(), lambda: "first result")
        recorder.run(recorder.mark_enqueued(), lambda: "second result")

        def fail() -> None:
            raise RuntimeError("synthetic handler failure")

        try:
            recorder.run(recorder.mark_enqueued(), fail)
        except RuntimeError:
            pass  # Demo only: the caller has observed the expected failure.

        recorder.mark_enqueued()  # Dropped/never-started: intentionally unrecorded.
        print("Synthetic completed attempts only; durations in seconds.")
        for line in format_summary(reader.get_metrics_data()):
            print(line)
    finally:
        provider.shutdown()


if __name__ == "__main__":
    main()
