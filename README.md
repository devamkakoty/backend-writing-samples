# Backend engineering: tested code, technical articles and automation

**Devam Kakoty**

Practical engineering samples for reliable data processing, observable queues
and review-first automation. The two technical articles pair clear explanations
with runnable implementations and deterministic tests; the n8n demonstration
adds a verified workflow execution and inspectable node outputs.

Original, self-published, AI-assisted portfolio work using synthetic inputs.

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

## Automation demonstration

**[Review-first notes workflow for n8n](https://github.com/devamkakoty/n8n-review-workflow-demo)**
turns a synthetic note into two pending-review proposals, then demonstrates
that replay creates no duplicates. It combines ordinary n8n HTTP Request nodes
with a dependency-free local Node.js API.

- **20 automated component tests:** replay/conflict handling, recoverable
  failures, disabled mode, bounded inputs and real loopback HTTP.
- **Verified execution in n8n 2.39.8:** imported workflow, all three executed
  nodes, two initial proposals and zero additional proposals on replay.
- **Inspectable proof:** workflow JSON, source, tests,
  [saved node outputs](https://github.com/devamkakoty/n8n-review-workflow-demo/blob/main/docs/execution-result.json)
  and a verification record.

This demonstration uses fixture model responses and an in-memory ledger.
It prepares proposals only; it does not send messages, change calendars or
claim a live client deployment.

## Reproduce the article examples

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
the accompanying executable tests and cited primary documentation. Test and
execution records state their exact scope. These are original portfolio
samples, not client deliverables or commissioned third-party publications.
No private customer, career or account records are included.
