# The handler was fast. Why did the work wait?

**Devam Kakoty — original AI-assisted technical sample.** Synthetic inputs;
no production-deployment claim.

This is an original portfolio sample, not a commissioned
client article. The accompanying program is a synchronous instrumentation
exercise, not a deployed queue, worker pool, or benchmark.

## Start with two intervals, not one stopwatch

Imagine an accepted item waiting two seconds before its handler starts. The
handler then finishes in half a second. Reporting "processing took 2.5 seconds"
obscures the distinction between waiting for execution and executing the work.
Reporting only the half-second handler duration hides the wait entirely.

I give each completed attempt three boundaries:

- `enqueued_at`: when the queue accepts the item;
- `started_at`: immediately before invoking its handler;
- `finished_at`: immediately after the handler returns or raises.

Queue residence is `started_at - enqueued_at`. Handler duration is
`finished_at - started_at`. These are elapsed durations, not CPU time. A
handler's synchronous I/O wait belongs to handler duration, not queue residence.
Capture enqueue acceptance consistently: a timestamp taken before a blocking
enqueue would also include producer-side waiting and change the metric's meaning.

The sample leaves enqueue acceptance to its caller. `mark_enqueued()` captures
a timestamp without claiming to implement a queue. `run(timestamp, handler)`
provides the start and finish boundaries. The lower-level `record_completion()`
accepts all three explicitly, making the contract inspectable.

## The denominator matters as much as the timer

Both histograms are recorded only after an attempt finishes. Consequently,
their populations match: completed attempts, grouped by their eventual outcome.
An ordinary handler exception is a completion with outcome `failure`; a normal
return is `success`. Success here means "returned normally," not "a payment
settled" or "a downstream business operation succeeded."

Dropped and never-started work is explicitly excluded. Started but unfinished
work is also absent. The wrapper does not catch `BaseException`, so process
interruptions such as `KeyboardInterrupt` are outside this completion contract.

This makes paired totals easier to interpret, but introduces completion bias.
If a queue stops draining, its oldest work contributes no new residence
observations. A quiet histogram therefore cannot establish queue health.
An operational system would also need independently defined backlog, oldest-item
age, acceptance, and drop signals. This sample deliberately does not manufacture
those signals from completed work.

Residence is attributed to the completion interval, not the original enqueue
interval. That distinction matters when comparing short dashboard windows.
Each retry would be another attempt with its own boundaries; these metrics
cannot identify unique jobs or deduplicate repeated recording.

## A monotonic clock, with explicit input rules

The default clock is Python's `time.monotonic()`. Python documents that it is
unaffected by system-clock updates and has an undefined reference point; elapsed
differences are the useful quantities [1]. All three timestamps must come from
the same clock domain. Do not subtract a broker's Unix timestamp from a local
monotonic reading or persist these values for reuse after a reboot.

Validation rejects booleans, nonnumeric values, NaN, infinity, reversed
boundaries, and subtraction that overflows to infinity. All validation happens
before any metric write. Zero-length intervals are valid. Negative timestamp
values are also valid if their ordering produces nonnegative durations:
an arbitrary epoch is not itself an elapsed interval.

Finite, ordered numbers still cannot prove correct provenance. The caller must
ensure that the boundaries describe the same attempt and clock. Floating-point
seconds also have finite precision; this is not a sub-nanosecond timing claim.

## Real instruments, deliberately small labels

The implementation accepts an OpenTelemetry API `Meter` and creates two
histograms plus one counter. It uses the documented `Histogram.record()` and
`Counter.add()` methods [2]:

| Instrument | Unit | Meaning |
| --- | --- | --- |
| `sample.queue.residence` | `s` | Enqueue-to-start duration of completed attempts |
| `sample.handler.duration` | `s` | Start-to-finish duration of completed attempts |
| `sample.work.completed` | `{attempt}` | Completed attempts by outcome |

These are sample-owned names, not a claim of conformity with messaging semantic
conventions. Each instrument carries exactly one metric attribute, `outcome`,
whose allowlist is `success` or `failure`. Unknown outcomes are rejected rather
than copied into telemetry.

There is no custom-attributes argument. Request IDs, exception messages,
customer names, and payload contents do not become labels. Different exception
classes all produce `failure`. This bounds each instrument to two application
attribute combinations in this isolated pipeline; it does not promise a
global backend series count after resources or other instrumentation are added.

The wrapper preserves a handler's return value and re-raises its original
exception. If timing validation also fails while handling an exception, the
handler error remains primary and the instrumentation error becomes its cause.
On the success path, instrumentation errors propagate. This strict teaching
policy is intentional, not a production recommendation to fail requests
whenever telemetry malfunctions.

## Inspect the SDK without exporting anything

`make_local_provider()` constructs a real SDK `MeterProvider` with an
`InMemoryMetricReader`. The official SDK documentation describes the provider
and reader, including collection through `get_metrics_data()` [3][4].
There is no global provider replacement, periodic exporter, network endpoint,
or account configuration.

The reader explicitly requests cumulative temporality for counters and
histograms, using the SDK instrument classes as mapping keys [4].
Collection returns nested resource, scope, and metric data. The console
summary prints histogram counts and sums plus counter values, leaving out
SDK-generated timestamps. Repeated collection is not another observation;
cumulative snapshots must not be added together.

Live PyPI metadata verified during preparation reports API and SDK version
`1.44.0`, released July 16, 2026, requiring Python 3.10 or newer [5][6].
`requirements.txt` pins both direct dependencies. It is not a hash-locked
transitive environment. Dependency installation can require network access;
the installed demo itself needs no network exporter or signup.

## Deterministic checks instead of sleep-based timing

The tests inject a mutable fake clock and inspect the real reader's output.
They check separate duration sums, zero durations, cumulative totals, bounded
labels, success and failure counts, and propagation of the original exception.
Invalid timestamps and invalid outcomes must leave all instruments untouched.
Additional cases cover never-started work, observation during handler execution,
interruptions, and invalid finish readings.

The console demo uses scripted clock readings for two successful attempts and
one failed attempt. A fourth enqueue is deliberately never started.
The following output was observed in the local validation run. Its numbers
come from the scripted inputs, not measured worker-pool performance:

```text
Synthetic completed attempts only; durations in seconds.
sample.handler.duration outcome=failure count=1 sum=0.250s
sample.handler.duration outcome=success count=2 sum=1.500s
sample.queue.residence outcome=failure count=1 sum=3.000s
sample.queue.residence outcome=success count=2 sum=2.000s
sample.work.completed outcome=failure value=1
sample.work.completed outcome=success value=2
```

Run these commands from this directory after dependency preparation:

```powershell
python -B -m unittest -v test_queue_metrics
python -B queue_metrics.py
```

**Observed validation, September 20, 2026:** all **21 tests passed** on Windows
with **Python 3.13.3**, using `python -m unittest -v test_queue_metrics.py`.
The separate `python queue_metrics.py` execution exited successfully and
produced the seven lines shown above. Installed versions were
`opentelemetry-api==1.44.0`, `opentelemetry-sdk==1.44.0`,
`opentelemetry-semantic-conventions==0.65b0` and `typing_extensions==4.16.0`.
This validates the stated synthetic contract on one local environment, not
other interpreters, a network exporter or a deployed service.

## What this sample cannot establish

The recorder is synchronous: passing a coroutine or generator would time its
creation, not deferred work. It supplies no concurrency coordination,
deduplication, crash recovery, or deployment evidence. Three instrument writes
are not an atomic transaction, even though bad inputs are rejected beforehand.

Histogram sums and counts support means for matching populations. They do not
justify adding independently computed queue and handler percentiles. Bucket
tuning and production SLO design remain separate work. The useful result here
is narrower: distinguish waiting from handling, while stating exactly which
attempts the measurements leave out.

## Primary references

1. Python clock contract: https://docs.python.org/3/library/time.html#time.monotonic
2. OpenTelemetry metrics API: https://opentelemetry-python.readthedocs.io/en/latest/api/metrics.html
3. SDK provider: https://opentelemetry-python.readthedocs.io/en/latest/sdk/metrics.html
4. SDK reader, temporality, and metric data: https://opentelemetry-python.readthedocs.io/en/latest/sdk/metrics.export.html
5. API release and live metadata: https://pypi.org/project/opentelemetry-api/1.44.0/ ; https://pypi.org/pypi/opentelemetry-api/json
6. SDK release and live metadata: https://pypi.org/project/opentelemetry-sdk/1.44.0/ ; https://pypi.org/pypi/opentelemetry-sdk/json
