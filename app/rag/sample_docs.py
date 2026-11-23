from pathlib import Path

PM_031 = """---
id: PM-2026-031
type: postmortem
title: Payments checkout outage caused by connection leak in refund handler
services: payments-api, payments-db
allowed_roles: sre, dba, developer
---
## Summary
On 2026-08-19 checkout failed for 47 minutes. The payments-db connection pool reached 100 of 100 connections and every new request timed out with POOL_EXHAUSTED errors.

## Root cause
Release payments-api v2.9.1 changed the refund handler. An error path acquired a database connection and never released it. Each failed refund leaked one connection until the pool was exhausted.

## Resolution
Payments-api was rolled back to v2.9.0, which freed the leaked connections. The permanent fix released connections in a finally block and a regression test was added.

## Lessons learned
Alert when connection pool usage passes 80 percent. Always compare the error start time with the latest deployment time before blaming the database.
"""

RB_DB_001 = """---
id: RB-DB-001
type: runbook
title: Runbook - PostgreSQL connection pool exhaustion
services: payments-db, orders-db
allowed_roles: sre, dba
---
## Symptoms
Errors such as POOL_EXHAUSTED or too many clients, connection count at max_connections, and rising latency while database CPU stays normal.

## Diagnosis
1. Check recent deployments of every service that uses the database.
2. Read application logs for connections acquired but not released.
3. Confirm database CPU is normal, which points to a leak and not to overload.

## Mitigation
1. Roll back the most recent deployment of the leaking service.
2. After the rollback confirm active connections fall below 60 percent of the pool.
3. Do not raise max_connections as a first step. It hides a leak and risks memory pressure.

## Escalation
If a rollback does not free connections within 10 minutes, page the database on-call engineer.
"""

RB_DEP_002 = """---
id: RB-DEP-002
type: runbook
title: Runbook - Rolling back a bad deployment
services: payments-api, orders-api
allowed_roles: sre, developer
---
## When to roll back
Roll back when errors start within 30 minutes after a deployment and the deployment touched the failing code path.

## Steps
1. Identify the previous healthy version from the deployments table.
2. Run the rollback pipeline for the service.
3. Watch the error rate for 10 minutes.

## Approval
Production rollbacks of P1 and P2 services need approval from the on-call engineer.
"""

RB_DB_009 = """---
id: RB-DB-009
type: runbook
title: DBA only - emergency session termination on payments-db
services: payments-db
allowed_roles: dba
---
## Emergency procedure
When the connection pool of payments-db is exhausted and a rollback is not possible, a DBA may terminate sessions that stay idle in transaction for more than 5 minutes using pg_terminate_backend.

## Raising the limit
As a last resort raise max_connections to 200. This needs a restart window and an approved change ticket.
"""

PM_044 = """---
id: PM-2026-044
type: postmortem
title: Orders database disk full from unrotated logs
services: orders-db
allowed_roles: sre, dba
---
## Summary
Orders-db stopped accepting writes for 25 minutes because the data disk reached 100 percent.

## Root cause
Application debug logs were written to the database volume and log rotation was disabled after a configuration change.

## Resolution
Old log files were deleted, rotation was enabled again, and a disk usage alert at 80 percent was added.
"""

PM_052 = """---
id: PM-2026-052
type: postmortem
title: Credentials exposed in application logs
services: payments-api
allowed_roles: security
---
## Summary
An API key for the payment provider was printed in payments-api debug logs and was visible to anyone with log access for six days.

## Root cause
A debug statement logged the full request headers including the authorization key.

## Resolution
The key was rotated, the debug statement was removed, and a secret scanner was added to the delivery pipeline.
"""

RB_GEN_005 = """---
id: RB-GEN-005
type: runbook
title: How to write an incident status update
services: general
allowed_roles: all
---
## Format
Every status update has four parts: impact, current status, next step, and the time of the next update.

## Tone
Use plain language. State what users see, not internal system names. Never include customer personal data.
"""

DOCS = {
    "pm-2026-031.md": ("postmortems", PM_031),
    "rb-db-001.md": ("runbooks", RB_DB_001),
    "rb-dep-002.md": ("runbooks", RB_DEP_002),
    "rb-db-009.md": ("runbooks", RB_DB_009),
    "pm-2026-044.md": ("postmortems", PM_044),
    "pm-2026-052.md": ("postmortems", PM_052),
    "rb-gen-005.md": ("runbooks", RB_GEN_005),
}


def write_sample_docs(base_dir):
    base = Path(base_dir)
    written = []
    for filename, (folder, content) in DOCS.items():
        target = base / folder
        target.mkdir(parents=True, exist_ok=True)
        path = target / filename
        path.write_text(content, encoding="utf-8")
        written.append(path)
    return written