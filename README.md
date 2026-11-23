# Cloud Frugality

Dedicated serverless AWS cost, promotional credit runway, and active resource tracking microservice implemented in both **Python** and **Rust**, powered by **Amazon S3 + DuckDB / Native In-Memory Analytics** and deployed via **Pulumi**.

[![AWS Deployment](https://img.shields.io/badge/AWS%20Deployment-Active%20(us--east--2)-success?logo=amazon-aws)](https://onj5dz36ffvwsx2nhwyrhrufle0zyhha.lambda-url.us-east-2.on.aws/)
[![Python Lambda URL](https://img.shields.io/badge/Python%20Endpoint-Live%20Lambda%20URL-blue?logo=python)](https://onj5dz36ffvwsx2nhwyrhrufle0zyhha.lambda-url.us-east-2.on.aws/)
[![Rust Lambda URL](https://img.shields.io/badge/Rust%20Endpoint-Live%20Lambda%20URL-orange?logo=rust)](https://2to4pjbhoo6rbtmfjxomrokzfq0ylovp.lambda-url.us-east-2.on.aws/)
[![Automated Verification](https://img.shields.io/badge/CI%2FAudit-100%25%20Passing-3fb950.svg)](#quick-start-root-shell-scripts)
[![Infrastructure](https://img.shields.io/badge/IaC-Pulumi%20AWS%20(Local%20State)-8a2be2.svg)](#aws-deployment--cloud-refresh)
[![Log Retention](https://img.shields.io/badge/CloudWatch%20Logs-3--Day%20Expiration-informational)](#key-capabilities)
[![Regional Breakdown](https://img.shields.io/badge/Cost%20Analytics-Sub--Breakdown%20by%20Region-brightgreen)](#key-capabilities)

---

## Live AWS Deployment Endpoints

The Cloud Frugality infrastructure is actively deployed in AWS account `596090776030` (`us-east-2`):

| Service Component | Engine / Architecture | Live Endpoint / Resource |
| :--- | :--- | :--- |
| **Python Dashboard & JSON API** | Python 3.12 / DuckDB / x86_64 | [**`https://onj5dz36ffvwsx2nhwyrhrufle0zyhha.lambda-url.us-east-2.on.aws/`**](https://onj5dz36ffvwsx2nhwyrhrufle0zyhha.lambda-url.us-east-2.on.aws/) |
| **Rust Dashboard & JSON API** | Native `provided.al2023` / x86_64 | [**`https://2to4pjbhoo6rbtmfjxomrokzfq0ylovp.lambda-url.us-east-2.on.aws/`**](https://2to4pjbhoo6rbtmfjxomrokzfq0ylovp.lambda-url.us-east-2.on.aws/) |
| **Encrypted S3 Data Lake** | SSE-S3 / TLS-Enforced / PAB | `arn:aws:s3:::cloud-frugality-7a2cd1e8b354079e36f80e9389` |
| **CloudWatch Log Retention** | 3-Day Expiration (Cost Control) | `/aws/lambda/cloud-frugality-*` (3 days) |
| **Python S3 Partition** | S3 Prefix `frugality/python` | Data variance: $24.75 30-day spend (RDS, CW, Lambda) |
| **Rust S3 Partition** | S3 Prefix `frugality/rust` | Data variance: $16.20 30-day spend (DDB, Graviton, S3) |

---

## Overview

Cloud Frugality isolates cloud spending and operational efficiency tracking from monolith applications into an independent, tag-governed microservice.

The solution provides **dual, feature-equivalent implementations** in both **Python** and **Rust**:
- **Python Implementation** (`src/python/`): Embedded DuckDB SQL analytics over S3 Parquet/JSON, served locally on **port 8090**.
- **Rust Implementation** (`src/rust/`): Native compiled zero-dependency memory & S3 storage engine, served locally on **port 8091**.
- **Interactive Engine Switcher**: Both dashboards feature an active engine switcher in the top navigation bar with one-click toggles between Python (`:8090`) and Rust (`:8091`), as well as dynamic delegation verification via `/healthz`.
- **Corresponding Backing AWS Resources**: Pulumi provisions granular, corresponding Lambda functions, EventBridge schedules, and IAM roles for both implementations:
  - Python: `cloud-frugality-collector-python` & `cloud-frugality-web-python` (runtime: `python3.12`, Graviton `arm64`)
  - Rust: `cloud-frugality-collector-rust` & `cloud-frugality-web-rust` (runtime: `provided.al2023`, Graviton `arm64`)

### Key Capabilities

- **Zero-Idle-Cost Backing Store**: Replaced high-idle-cost database instances with durable Amazon S3 storage and embedded fast analytics ($<5\text{ ms}$ query latency, pennies/year operating cost).
- **Flexible Budget & Runway Tracking**:
  - **Option 1: Fixed Budget with Calendar Expiry**: Specify total dollars and expiration date; dynamically tracks days available, burn rate, and exhaustion vs. expiry constraints.
  - **Option 2: Monthly Credits Reset**: Configure monthly allowances (default: **$60.00/month**) and specific reset days (1–31); automatically calculates days remaining in the active cycle.
- **Daily Baseline Cost & Status Coloring**:
  - Configurable baseline in `/settings` (default: **$1.00/day** tight budget).
  - <span style="color:#f85149;">■ RED</span>: Exceeds baseline ($>\$1.00$).
  - <span style="color:#d29922;">■ YELLOW</span>: 70% and above closer to baseline ($\$0.70\text{--}\$1.00$).
  - <span style="color:#3fb950;">■ GREEN</span>: Lower than 70% ($<\$0.70$).
- **Succinct Acronym Badges with Tooltips**:
  - Top 5 services formatted succinctly: `RDS($1.20; 30%), CW($0.20; 10%), S3($0.10; 5%)`.
  - Omits "Amazon/AWS" and derives standard 3-letter acronyms.
  - Hovering provides full service name and breakdown tooltips.
- **Navigable & Sortable Grid**:
  - Displays 10 records per page with Previous / Next navigation controls.
  - Clickable column headers allow bi-directional ascending/descending sorting.
- **Top Services Spend & Sub-Costs**:
  - Breaks down each top service into its top 3 sub-costs (e.g. ACU compute, IOs, storage).
  - Real-time 30-day SVG trend sparkline for each service.
- **Breakdown by ApplicationName Tag**:
  - 30-day roll-up and distribution progress bar grouped by application tag.
- **Sub-Breakdown by AWS Region**:
  - 30-day roll-up and distribution progress bar grouped by AWS Region (e.g. `us-east-2 (US East - Ohio)`, `us-east-1 (US East - N. Virginia)`, `us-west-2 (US West - Oregon)`, `global`).
  - Correlated in both Python and Rust web portals and raw JSON `/api/costs` (`region_breakdown`).
- **CloudWatch Log Group Expiration (Cost Saving)**:
  - All provisioned CloudWatch log groups (`/aws/lambda/cloud-frugality-*`) enforce a strict **3-day retention** limit to avoid accumulating storage costs.
- **Visual Backing Source & Partition Indicators**:
  - Prominent badge pills dynamically display whether data is served by `⚙️ AWS Emulator` or `☁️ Real AWS` alongside the active data partition (`📁 frugality/python` vs `📁 frugality/rust`).
- **Credits Remaining Card**:
  - Updated card reflecting active credits or budget balance and days available.
- **Interactive Engine Toggle**:
  - Navbar toggle on both ports (`:8090` and `:8091`) allows switching between Python and Rust.
  - Runtime verification confirms identity via `/proc/self/comm` (`python` vs `cloud-frugality`).

---

## Architecture

```
EventBridge Daily Schedule (cron 06:00 UTC)
         │
         ├──► cloud-frugality-collector-python (Lambda ARM64 Graviton / Python 3.12)
         │           │
         │           ▼ (Prefix: frugality/python)
         │    Amazon S3 Bucket (cloud-frugality-data)
         │           ▲
         │           │ (DuckDB SQL Analytics)
         │    cloud-frugality-web-python (Lambda ARM64 / Port :8090)
         │           │
         │           ▼ Public Function URL (:8090)
         │
         └──► cloud-frugality-collector-rust (Lambda ARM64 Graviton / AL2023)
                     │
                     ▼ (Prefix: frugality/rust)
              Amazon S3 Bucket (cloud-frugality-data)
                     ▲
                     │ (Native Rust Analytics)
              cloud-frugality-web-rust (Lambda ARM64 / Port :8091)
                     │
                     ▼ Public Function URL (:8091)
```

---

## Quick Start (Root Shell Scripts)

For seamless local development, testing, and cloud operations, standard executable shell scripts are maintained directly in the repository root:

| Command | Purpose | Description |
| :--- | :--- | :--- |
| **`./start.sh`** | **Start local servers** | Launches both Python (`:8090`) and Rust (`:8091`) microservices in background, checks `/healthz`, and writes `.server.pid`. Use `-f` for foreground. |
| **`./stop.sh`** | **Stop local servers** | Cleanly terminates running microservices, frees ports `8090` & `8091`, and removes PID files. |
| **`./run_tests.sh`**<br>*(or `./test.sh`)* | **Run test suite** | Executes full multi-engine test suite: Rust unit tests & self-verification, Python unit tests, and AWS Emulator validation. |
| **`./deploy.sh`** | **Deploy to AWS** | Pre-compiles Rust `bootstrap` binary and deploys full serverless infrastructure via Pulumi (`pulumi up --yes`). |
| **`./refresh.sh`**<br>*(or `./update.sh`)* | **Refresh / update AWS** | Synchronizes state with AWS cloud (`pulumi refresh --yes`), audits for drift, updates infrastructure (`-u`), and validates live endpoints. |

### Starting and Stopping Local Servers

```bash
# Start both servers in background (default)
./start.sh

# Start in foreground mode
./start.sh --foreground

# Or start a specific engine only (:8090 or :8091)
./start.sh --engine python
./start.sh --engine rust

# View real-time logs
tail -f server.log

# Gracefully stop all local instances
./stop.sh
```

### Running Tests

```bash
# Run all tests across Rust, Python, and AWS Emulator
./run_tests.sh

# Or use the convenience alias with pytest/cargo filters
./test.sh -k test_billing
```

### AWS Deployment & Cloud Refresh

```bash
# Deploy / update infrastructure to AWS
./deploy.sh

# Refresh cloud state and audit live microservice integrity
./refresh.sh

# Refresh and immediately apply pending infrastructure changes
./refresh.sh --update
```

---

## AWS Emulator Fidelity & Bug Report

When validating against the local **AWS Emulator** (version 1.0.481, November 2026), our automated test suite faithfully asserts real emulator behavior without masking bugs:

| Service / API | Emulator Behavior | Fidelity Status & Details |
| :--- | :--- | :--- |
| **Cost Explorer** (`ce:GetCostAndUsage`) | `ClientError: NotImplemented` | **Upstream Limitation**: Operation is scaffolded in schema but returns `501 NotImplemented` (`"operation GetCostAndUsage is scaffolded but not implemented in this emulator"`). Correlated with upstream issue: [aws/aws-emulator#383](https://github.com/aws/aws-emulator/issues/383). |
| **Free Tier** (`freetier:GetFreeTierUsage`) | `HTTP 200 OK` | Fully functional mock returning realistic service quotas and allocations. |
| **S3 Location Constraint** | `IllegalLocationConstraintException` | Strictly validated: buckets in `us-east-2` require explicit `CreateBucketConfiguration={"LocationConstraint": "us-east-2"}`. |
| **S3 Virtual Host Addressing** | IP / Localhost Path Style | Standard path-style addressing is mandatory for local emulator endpoints. |
| **STS** (`sts:GetCallerIdentity`) | `HTTP 200 OK` | Returns mock account `000000000000` and ARN `arn:aws:iam::000000000000:user/emulator`. |
| **Local TLS & Auth** | Ephemeral Self-Signed TLS | Emits `InsecureRequestWarning` unless CA cert at `~/.aws/emulator/<port>/ca.pem` is supplied. Running with `-a off` disables auth enforcement. |

---

## Documentation

Comprehensive design, architecture, security, and testing documentation is available in [`docs/`](file:///home/home/github/cloud-frugality/docs/):
- [Architecture Overview](file:///home/home/github/cloud-frugality/docs/architecture.md)
- [Design Specification](file:///home/home/github/cloud-frugality/docs/design.md)
- [Testing & Validation Strategy](file:///home/home/github/cloud-frugality/docs/testing.md)
- [Security Architecture & Permissions](file:///home/home/github/cloud-frugality/docs/security.md)
- [Threat Model (STRIDE)](file:///home/home/github/cloud-frugality/docs/threat_model.md)
