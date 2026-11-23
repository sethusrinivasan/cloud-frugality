# Cloud Frugality Security Architecture

## 1. Zero Stored Credentials

Cloud Frugality eliminates stored API keys, long-lived AWS IAM user access keys, database passwords, and Secrets Manager entries:
- Lambda functions run under assumed IAM roles via AWS STS short-lived tokens.
- All requests between services use TLS 1.3 encryption.
- No secrets or credentials exist in source code, configuration files, or build artifacts.

---

## 2. Granular Least-Privilege IAM Roles

### Collector Execution Role (`cloud-frugality-collector-*`)
The collector requires write access to the S3 data lake and read-only access to AWS billing and tagging APIs:

| Action | Target Resource | Justification |
| :--- | :--- | :--- |
| `s3:PutObject`, `s3:GetObject`, `s3:ListBucket` | `arn:aws:s3:::cloud-frugality-*` & `/*` | Stores daily costs, tag distributions, and inventory |
| `ce:GetCostAndUsage`, `ce:GetCostForecast`, `ce:GetDimensionValues` | `*` | Harvests spend and usage breakdown by service and tag |
| `freetier:GetAccountPlanState`, `freetier:GetFreeTierUsage` | `*` | Harvests promotional credit allowance and remaining balance |
| `tag:GetResources` | `*` | Sweeps active tagged account resources |
| `lambda:ListFunctions`, `rds:DescribeDBInstances` | `*` | Enriches inventory creation timestamps |
| `logs:CreateLogStream`, `logs:PutLogEvents` | `/aws/lambda/cloud-frugality-collector:*` | Emits structured operational logs |

### Web Portal Execution Role (`cloud-frugality-web-*`)
The web portal serves read queries and configuration updates. It has **zero** Cost Explorer or FreeTier permissions:

| Action | Target Resource | Justification |
| :--- | :--- | :--- |
| `s3:GetObject`, `s3:ListBucket` | `arn:aws:s3:::cloud-frugality-*` & `/*` | Queries data lake via embedded DuckDB engine |
| `s3:PutObject` | `arn:aws:s3:::cloud-frugality-*/frugality/settings/*` | Restricts write access strictly to configuration files |
| `logs:CreateLogStream`, `logs:PutLogEvents` | `/aws/lambda/cloud-frugality-web:*` | Emits structured operational logs |

---

## 3. Storage Lake Security (Amazon S3)

- **Default Encryption**: Server-Side Encryption with Amazon S3 managed keys (`AES256` / SSE-S3) enforced on all objects.
- **Public Access Block**: All four S3 Block Public Access flags are enabled (`block_public_acls`, `block_public_policy`, `ignore_public_acls`, `restrict_public_buckets`).
- **Enforced TLS Transport**: The bucket policy explicitly denies any request where `aws:SecureTransport` is `false`.

---

## 4. Lambda Function URL Security

- **Restricted HTTP Methods**: CORS configuration allows only `GET` and `POST` methods.
- **Header Sanitization**: Form inputs and JSON payloads are parsed with type-safety checks and boundary constraints (e.g., reset day clamped between 1 and 31).
