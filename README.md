# Backend engineering: executable technical articles

**Devam Kakoty**

Two original, self-published, AI-assisted technical samples. Each article is
paired with small runnable source files and deterministic tests. All examples
use synthetic inputs; these are not claims about client work, deployed systems,
measured production savings, or previous editorial commissions.

## Articles

1. **[Deterministic CSV joins: account for every row before pairing
   records](join-audit/article.md)** — define one-to-one join ambiguity,
   retain source-record positions, and reject malformed input instead of
   silently choosing duplicate winners. Standard-library Python.
2. **[Separate queue residence from processing duration with
   OpenTelemetry](queue-observability/article.md)** — measure two different
   delays with monotonic timestamps, explicit measurement boundaries and
   bounded labels; inspect actual SDK aggregation without an account or
   network exporter.

## Reproduce

Use Python 3.11 or later. Exact tested versions and results are recorded in
each article after validation; a compatibility target is not a claim that
every supported interpreter has been tested.

```powershell
cd join-audit
python -B -m unittest -v test_join_audit.py
cd ../queue-observability
python -m pip install -r requirements.txt
python -B -m unittest -v test_queue_metrics.py
python -B queue_metrics.py
```

The second sample should be installed in an isolated Python environment.
No cloud account, paid API, telemetry destination or customer data is required.

## Provenance and scope

The code and articles were prepared with AI assistance and checked against
the accompanying executable tests and cited primary documentation. They are
new portfolio samples, not historical third-party publications. The tests
support their stated local behavior, not complete correctness or production
readiness. No client deliverables or private career/account records are included.

No publisher has commissioned or accepted these articles. Later commissioned
work, editorial requirements, compensation and publication rights would be
agreed separately.
