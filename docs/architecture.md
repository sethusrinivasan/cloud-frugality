# Cloud Frugality Architecture

## 1. System Overview

Cloud Frugality is a dedicated, serverless AWS cost, promotional credit runway, and active resource tracking microservice designed for maximum operational efficiency, zero specification drift, and near-zero infrastructure operating costs.

### Architectural Evolution: Aurora PostgreSQL to Amazon S3 + DuckDB

Previously, Cloud Frugality relied on an Amazon Aurora Serverless v2 PostgreSQL cluster. While Aurora provided relational capabilities and IAM Database Authentication, it introduced:
- Constant baseline idle costs (~$0.12/hour for 0.5 ACU minimum, or ~$90/month minimum even when idle).
- Cold resume latencies (several seconds when resuming from 0 to 0.5 ACU).
- Complex VPC networking, subnets, and RDS IAM DB auth token generation overhead.

In this architecture, Cloud Frugality transitions to **Amazon S3 + DuckDB**:
- **Zero Idle Cost**: Amazon S3 charges purely for storage ($0.023/GB/month) and requests. Data for a small organization costs pennies per year.
- **Embedded Analytics**: DuckDB executes directly inside the AWS Lambda runtime memory space. Queries over daily costs, 30-day roll-ups, service trends, and tag distributions execute in under **5 milliseconds**.
- **No VPC Bottlenecks**: Functions execute in standard AWS Lambda environments without requiring VPC attachment, private subnets, or NAT Gateways.
- **Stateless & Scalable**: S3 serves as the durable columnar data lake, while DuckDB delivers SQL query capabilities.

---

## 2. Component Diagram

```mermaid
flowchart TD
    subgraph Scheduling
        EB["EventBridge Schedule<br/>cron(0 6 * * ? *)"]
    end

    subgraph Data Collection
        Collector["cloud-frugality-collector<br/>(AWS Lambda ARM64 Graviton)"]
        CE["AWS Cost Explorer API<br/>(Usage, Services, Sub-costs, Tags)"]
        FT["AWS FreeTier API<br/>(Account Plan State)"]
        TagAPI["Resource Groups Tagging API<br/>(Account Inventory)"]
    end

    subgraph Storage Lake
        S3["Amazon S3 Bucket<br/>(frugality-data-bucket)<br/>SSE-S3 + Public Access Block + TLS Policy"]
        DailyJSON["s3://.../frugality/daily_costs.json"]
        SettingsJSON["s3://.../frugality/settings/config.json"]
        InvJSON["s3://.../frugality/inventory.json"]
    end

    subgraph Public Portal & Analytics
        Web["cloud-frugality-web<br/>(AWS Lambda ARM64 Graviton)"]
        DuckDB["Embedded DuckDB Engine<br/>(:memory: SQL over S3/Local Datasets)"]
        FnURL["Public HTTPS Function URL<br/>(/, /settings, /api/costs, /healthz)"]
        User["User Browser / Automated Audit"]
    end

    EB -->|Daily Trigger| Collector
    Collector -->|Harvest Spend| CE
    Collector -->|Harvest Runway| FT
    Collector -->|Harvest Resources| TagAPI
    Collector -->|Persist Parquet/JSON| S3

    S3 --> DailyJSON
    S3 --> SettingsJSON
    S3 --> InvJSON

    User -->|HTTPS Request| FnURL
    FnURL --> Web
    Web --> DuckDB
    DuckDB -->|Query Datasets| S3
    Web -->|Settings Update| SettingsJSON
```

---

## 3. Data Flow & Execution Sequence

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant FnURL as Lambda Function URL
    participant Web as cloud-frugality-web
    participant DuckDB as Embedded DuckDB
    participant S3 as Amazon S3 Bucket

    User->>FnURL: GET / (Dashboard)
    FnURL->>Web: Invoke Lambda handler
    Web->>S3: Read settings/config.json & daily_costs.json
    Web->>DuckDB: Load daily costs & execute SQL analytics
    Note over DuckDB: Computes 30d gross/net, top services with sparkline trends,<br/>top 3 sub-costs, ApplicationName tag roll-up,<br/>and budget days available
    DuckDB-->>Web: Analytical summary
    Web-->>User: Rendered HTML dashboard with sortable 10-row grid & sparklines

    User->>FnURL: POST /settings (Update Budget or Baseline)
    FnURL->>Web: Invoke Lambda handler
    Web->>S3: PutObject frugality/settings/config.json
    Web-->>User: Return updated settings confirmation
```

---

## 4. Operational Boundaries & Infrastructure as Code

- **Pulumi AWS Provider**: Replaced CDK/Terraform with Pulumi Python (`infra/`). Declaratively manages S3 buckets, granular IAM policies, Lambda functions, log groups, and EventBridge rules.
- **Local AWS Emulation**: Integrates with the local `aws-emulator` binary (AWS Emulator Nov 2026 release) on `https://127.0.0.1:9297`, enabling 100% offline verification with zero cloud costs.
- **Tag Governance**: Every infrastructure component is tagged with `Frugality: true` and audited automatically.
