---
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
