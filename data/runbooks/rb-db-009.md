---
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
