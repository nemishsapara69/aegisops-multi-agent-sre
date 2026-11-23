---
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
