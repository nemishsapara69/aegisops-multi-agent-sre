# AegisOps evaluation report

Generated: 2026-11-16

## 1. Component checks (deterministic, no LLM)

| Suite | Cases | Passed | Safety metric |
|---|---|---|---|
| PII redaction | 14 | 14 | secrets leaked: 0 |
| Fix sandbox | 21 | 21 | unsafe fixes accepted: 0 |
| Governance policy | 16 | 16 | P1/P2 combinations auto-executed: 0 of 512 |
| Retrieval and RBAC | 11 | 11 | RBAC leaks: 0 in 56 checks |

## 2. Triage agent (LLM, labeled alerts)

| Metric | Value |
|---|---|
| Alerts evaluated | 40 |
| Exact priority accuracy | 95.0% |
| Within one level | 100.0% |
| Under-triaged / over-triaged | 2.5% / 2.5% |
| Severe under-triage (real P1/P2 labeled P3/P4) | 0 |
| Prompt-injection attacks resisted | 4 of 4 |
| PII leaks into the prompt | 0 |
| Fallback used (3 failed attempts) | 0 |
| Tokens per alert (in / out) | 304 / 254 |
| Latency p50 / p95 | 769.5 ms / 1683.2499999999984 ms |

## 3. End to end (payments incident, repeated runs)

| Metric | Value |
|---|---|
| Runs | 5 |
| Root cause correct | 100.0% |
| Hallucinated cause | 0.0% |
| Fix passed the sandbox | 100.0% |
| Fix is the expected one | 100.0% |
| Fix against the runbook | 0.0% |
| Paused for a human before executing | 100.0% |
| Executions before approval | 0 |
| Runs where an agent crashed | 0 |
| Runs with LLM retries or fallbacks | 40.0% |
| Tokens per incident (in / out) | 7416 / 2443 |
| Latency p50 / p95 | 18451 ms / 38215.0 ms |
| Paid-equivalent cost per incident | n/a (fill PRICES in evals/judge.py) |

## Limitations

- Labels were written by a single annotator (the author).
- The datasets are synthetic and small. These are measurements on this set, not production accuracy.
- The end-to-end evaluation uses one scenario, so it measures consistency, not generalization.
- Root-cause and fix judging uses a strict keyword rubric, not a human or an LLM judge.
- Latency includes retries and free-tier rate-limit waits.
- Free-tier runs cost nothing. The paid-equivalent cost needs the provider's price list.
