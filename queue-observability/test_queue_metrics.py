"""Contract tests against the real SDK; no sleeps, exporter, or network.

Validation status: NOT RUN during preparation. Parent fills actual results.
"""

import contextlib
import io
import unittest

from opentelemetry.sdk.metrics.export import AggregationTemporality, Histogram, Sum

from queue_metrics import (
    COMPLETED,
    PROCESSING,
    RESIDENCE,
    QueueRecorder,
    main,
    make_local_provider,
)


class FakeClock:
    def __init__(self, now=0.0):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class QueueMetricsTests(unittest.TestCase):
    def setUp(self):
        self.provider, self.reader = make_local_provider()
        self.addCleanup(self.provider.shutdown)
        self.clock = FakeClock(100.0)
        self.recorder = QueueRecorder(
            self.provider.get_meter("queue-observability.tests"),
            clock=self.clock,
        )

    def snapshot(self):
        data = self.reader.get_metrics_data()
        metrics = {}
        if data is not None:
            for resource in data.resource_metrics:
                for scope in resource.scope_metrics:
                    for metric in scope.metrics:
                        self.assertNotIn(metric.name, metrics)
                        metrics[metric.name] = metric
        return metrics

    def point(self, metrics, name, outcome):
        matches = [
            point
            for point in metrics[name].data.data_points
            if dict(point.attributes) == {"outcome": outcome}
        ]
        self.assertEqual(len(matches), 1)
        return matches[0]

    def assert_histogram(self, metrics, name, outcome, count, total):
        self.assertIsInstance(metrics[name].data, Histogram)
        self.assertEqual(metrics[name].unit, "s")
        point = self.point(metrics, name, outcome)
        self.assertEqual(point.count, count)
        self.assertEqual(sum(point.bucket_counts), count)
        self.assertAlmostEqual(point.sum, total)
        return point

    def record(self, enqueued=100.0, started=102.0, finished=102.5, outcome="success"):
        self.recorder.record_completion(
            enqueued_at=enqueued,
            started_at=started,
            finished_at=finished,
            outcome=outcome,
        )

    def test_queue_residence_is_not_handler_processing(self):
        self.record()
        metrics = self.snapshot()
        self.assertEqual(set(metrics), {RESIDENCE, PROCESSING, COMPLETED})
        self.assert_histogram(metrics, RESIDENCE, "success", 1, 2.0)
        self.assert_histogram(metrics, PROCESSING, "success", 1, 0.5)

    def test_success_returns_handler_value_and_uses_injected_clock(self):
        enqueued = self.recorder.mark_enqueued()
        self.clock.advance(4.0)
        value = object()

        def handler():
            self.clock.advance(0.25)
            return value

        self.assertIs(self.recorder.run(enqueued, handler), value)
        metrics = self.snapshot()
        self.assert_histogram(metrics, RESIDENCE, "success", 1, 4.0)
        self.assert_histogram(metrics, PROCESSING, "success", 1, 0.25)
        self.assertEqual(self.point(metrics, COMPLETED, "success").value, 1)

    def test_failure_records_both_durations_and_reraises_same_error(self):
        enqueued = self.recorder.mark_enqueued()
        self.clock.advance(3.0)
        error = RuntimeError("request-938-private-message")

        def handler():
            self.clock.advance(0.75)
            raise error

        with self.assertRaises(RuntimeError) as caught:
            self.recorder.run(enqueued, handler)
        self.assertIs(caught.exception, error)
        metrics = self.snapshot()
        self.assert_histogram(metrics, RESIDENCE, "failure", 1, 3.0)
        self.assert_histogram(metrics, PROCESSING, "failure", 1, 0.75)
        self.assertEqual(self.point(metrics, COMPLETED, "failure").value, 1)

    def test_deterministic_totals_by_outcome(self):
        self.record(0.0, 2.0, 2.5)
        self.record(10.0, 10.0, 11.0)
        self.record(20.0, 23.0, 23.25, "failure")
        metrics = self.snapshot()
        self.assert_histogram(metrics, RESIDENCE, "success", 2, 2.0)
        self.assert_histogram(metrics, PROCESSING, "success", 2, 1.5)
        self.assert_histogram(metrics, RESIDENCE, "failure", 1, 3.0)
        self.assert_histogram(metrics, PROCESSING, "failure", 1, 0.25)
        self.assertIsInstance(metrics[COMPLETED].data, Sum)
        self.assertTrue(metrics[COMPLETED].data.is_monotonic)
        self.assertEqual(metrics[COMPLETED].unit, "{attempt}")
        self.assertEqual(self.point(metrics, COMPLETED, "success").value, 2)
        self.assertEqual(self.point(metrics, COMPLETED, "failure").value, 1)
        self.assertEqual(
            sum(p.value for p in metrics[COMPLETED].data.data_points), 3
        )

    def test_only_bounded_outcome_attributes_are_emitted(self):
        self.record()
        for index, error_type in enumerate((ValueError, RuntimeError, LookupError)):
            def handler(error_type=error_type, index=index):
                raise error_type(f"private-request-{index}")

            with self.assertRaises(error_type):
                self.recorder.run(99.0, handler)
        for metric in self.snapshot().values():
            self.assertEqual(
                {tuple(sorted(p.attributes.items())) for p in metric.data.data_points},
                {(("outcome", "success"),), (("outcome", "failure"),)},
            )

    def test_arbitrary_outcomes_are_rejected_without_partial_writes(self):
        for outcome in ("request-123", "timeout", "SUCCESS", "", None, True, []):
            with self.subTest(outcome=outcome):
                with self.assertRaises(ValueError):
                    self.record(outcome=outcome)
                self.assertEqual(self.snapshot(), {})

    def test_arbitrary_attribute_input_is_not_supported(self):
        with self.assertRaises(TypeError):
            self.recorder.record_completion(
                enqueued_at=0,
                started_at=1,
                finished_at=2,
                outcome="success",
                attributes={"request.id": "request-123"},
            )
        self.assertEqual(self.snapshot(), {})

    def test_zero_durations_are_valid_observations(self):
        self.record(0, 0, 0)
        metrics = self.snapshot()
        self.assert_histogram(metrics, RESIDENCE, "success", 1, 0)
        self.assert_histogram(metrics, PROCESSING, "success", 1, 0)
        self.assertEqual(self.point(metrics, COMPLETED, "success").value, 1)

    def test_negative_epoch_is_valid_when_durations_are_positive(self):
        self.record(-10, -8, -7.5)
        metrics = self.snapshot()
        self.assert_histogram(metrics, RESIDENCE, "success", 1, 2)
        self.assert_histogram(metrics, PROCESSING, "success", 1, 0.5)

    def test_invalid_timestamp_values_in_every_position_emit_nothing(self):
        for position in ("enqueued_at", "started_at", "finished_at"):
            for value in (float("nan"), float("inf"), -float("inf"), True, "1", None, 10**400):
                with self.subTest(position=position, value=value):
                    args = dict(
                        enqueued_at=100, started_at=102, finished_at=103, outcome="success"
                    )
                    args[position] = value
                    with self.assertRaises(ValueError):
                        self.recorder.record_completion(**args)
                    self.assertEqual(self.snapshot(), {})

    def test_reversed_boundaries_emit_no_partial_observations(self):
        for boundaries in ((10, 9, 11), (10, 11, 10)):
            with self.subTest(boundaries=boundaries):
                with self.assertRaises(ValueError):
                    self.record(*boundaries)
                self.assertEqual(self.snapshot(), {})

    def test_finite_timestamps_with_overflowing_duration_are_rejected(self):
        for boundaries in ((-1e308, 1e308, 1e308), (-1e308, -1e308, 1e308)):
            with self.subTest(boundaries=boundaries):
                with self.assertRaises(ValueError):
                    self.record(*boundaries)
                self.assertEqual(self.snapshot(), {})

    def test_never_started_and_dropped_work_emit_nothing(self):
        self.recorder.mark_enqueued()  # Pending submission.
        self.clock.advance(50)
        self.recorder.mark_enqueued()  # Simulated drop: no run/record call.
        self.assertEqual(self.snapshot(), {})

    def test_work_is_not_emitted_while_handler_is_running(self):
        def handler():
            self.assertEqual(self.snapshot(), {})
            self.clock.advance(1)

        self.recorder.run(self.recorder.mark_enqueued(), handler)
        self.assertEqual(self.point(self.snapshot(), COMPLETED, "success").value, 1)

    def test_cumulative_collection_does_not_double_count(self):
        self.record()
        first = self.snapshot()
        second = self.snapshot()
        for metrics in (first, second):
            for metric in metrics.values():
                self.assertEqual(
                    metric.data.aggregation_temporality, AggregationTemporality.CUMULATIVE
                )
            self.assert_histogram(metrics, RESIDENCE, "success", 1, 2)
            self.assertEqual(self.point(metrics, COMPLETED, "success").value, 1)
        self.record()
        third = self.snapshot()
        self.assert_histogram(third, RESIDENCE, "success", 2, 4)
        self.assert_histogram(third, PROCESSING, "success", 2, 1)
        self.assertEqual(self.point(third, COMPLETED, "success").value, 2)

    def test_invalid_start_prevents_handler_execution(self):
        calls = []
        with self.assertRaises(ValueError):
            self.recorder.run(101, lambda: calls.append("called"))
        self.assertEqual(calls, [])
        self.assertEqual(self.snapshot(), {})

    def test_invalid_finish_on_success_is_visible_and_emits_nothing(self):
        def handler():
            self.clock.now = 99

        with self.assertRaises(ValueError):
            self.recorder.run(100, handler)
        self.assertEqual(self.snapshot(), {})

    def test_handler_error_survives_invalid_finish_with_cause(self):
        error = LookupError("synthetic failure")

        def handler():
            self.clock.now = 99
            raise error

        with self.assertRaises(LookupError) as caught:
            self.recorder.run(100, handler)
        self.assertIs(caught.exception, error)
        self.assertIsInstance(caught.exception.__cause__, ValueError)
        self.assertEqual(self.snapshot(), {})

    def test_baseexception_interruption_is_excluded(self):
        def interrupted():
            raise KeyboardInterrupt()

        with self.assertRaises(KeyboardInterrupt):
            self.recorder.run(100, interrupted)
        self.assertEqual(self.snapshot(), {})

    def test_enqueue_clock_is_validated_without_emission(self):
        self.clock.now = float("nan")
        with self.assertRaises(ValueError):
            self.recorder.mark_enqueued()
        self.assertEqual(self.snapshot(), {})

    def test_demo_console_contract(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            main()
        self.assertEqual(
            output.getvalue().splitlines(),
            [
                "Synthetic completed attempts only; durations in seconds.",
                "sample.handler.duration outcome=failure count=1 sum=0.250s",
                "sample.handler.duration outcome=success count=2 sum=1.500s",
                "sample.queue.residence outcome=failure count=1 sum=3.000s",
                "sample.queue.residence outcome=success count=2 sum=2.000s",
                "sample.work.completed outcome=failure value=1",
                "sample.work.completed outcome=success value=2",
            ],
        )


if __name__ == "__main__":
    unittest.main()
