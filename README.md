# Cloud Frugality

Dedicated serverless cost, promotional credit runway, and active AWS resource tracking microservice with IAM Database Authentication and zero stored credentials.

## Overview

Cloud Frugality isolates cloud spending and operational efficiency tracking from monolith demo applications into an independent, tag-governed microservice.

### Key Capabilities
- **Pre-Credit Gross Consumption**: Records real AWS resource consumption from Cost Explorer (`Usage` records) rather than netting spend to zero against promotional credits.
- **Credit Balance & Runway Forecasting**: Tracks promotional credits and evaluates whether **exhaustion** (high burn rate) or **expiration** (calendar cutoff) is the binding constraint.
- **Active AWS Resource Inventory**: Periodically enumerates taggable resources across the AWS account via the Resource Groups Tagging API and enriches creation dates.
- **Strict IAM Database Authentication**: Connects natively to Aurora Serverless v2 PostgreSQL using short-lived IAM authentication tokens. No passwords, API keys, or Secrets Manager entries.
- **Mandatory Tagging**: Every provisioned resource carries the required `Frugality` tag (`Frugality: true`).

## Architecture

```
EventBridge Daily Schedule (cron 06:00 UTC)
         │
         ▼
cloud-frugality-collector (AWS Lambda Graviton arm64)
         │
         ├── AWS Cost Explorer (ce:GetCostAndUsage)
         ├── AWS Free Tier Plan State (freetier:GetAccountPlanState)
         └── Resource Groups Tagging (tag:GetResources)
         │
         ▼ (psycopg over TLS + IAM DB Auth)
Aurora Serverless v2 PostgreSQL (daily_cost & resource_inventory)
         ▲
         │ (psycopg over TLS + IAM DB Auth - Read Only)
cloud-frugality-web (AWS Lambda Graviton arm64)
         │
         ▼
Public HTTPS Function URL (/ & /api/costs & /healthz)
```

## Anti-Drift & Operational Integrity

Following lessons from systems reliability post-mortems (*When AI Agents Cheat: A Post-Mortem on Ghost Microservices, Specification Drift, and the Illusion of 100% Green CI*):

1. **Genuine Microservices**: Real, end-to-end Python handlers executing psycopg wire protocols against live databases—no static mocks or hollow 200 OK stubs.
2. **Process Comm Inspection**: The `/healthz` endpoint exposes genuine Linux kernel identity via `/proc/self/comm` to prove runtime integrity.
3. **Rigorous Test Assertions**: Tests strictly assert data structures, non-empty datasets, positive values, and valid schemas without test relaxation.
4. **AWS Tag Auditing**: Automated live audit confirms the presence of the `Frugality` tag on all deployed AWS Lambda functions.

## Deployment & Verification

```bash
# 1. Deploy Cloud Frugality CDK stack
./scripts/deploy.sh

# 2. Run offline tests & live verification audit
./scripts/verify_deployment.sh
```
