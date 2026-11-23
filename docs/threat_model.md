# Cloud Frugality Threat Model (STRIDE)

## 1. Scope & System Boundaries

This threat model evaluates Cloud Frugality assets, trust boundaries, and potential threat actors based on the STRIDE framework:
- **Public Entry Point**: Public HTTPS Function URL (`/`, `/settings`, `/api/costs`, `/healthz`).
- **Processing Layer**: AWS Lambda functions (Graviton ARM64 execution environment).
- **Storage Layer**: Amazon S3 bucket storing cost, inventory, and configuration records.
- **External Dependencies**: AWS Cost Explorer API, AWS FreeTier API, Resource Groups Tagging API.

---

## 2. STRIDE Threat Analysis

| Threat Category | Potential Threat Scenario | Impact | Mitigation in Cloud Frugality |
| :--- | :--- | :--- | :--- |
| **Spoofing** | Attacker impersonates the Lambda handler or calls internal storage APIs directly. | Unauthorized data modification or false cost reports. | - Lambda functions execute under IAM execution roles with temporary AWS credentials.<br/>- S3 bucket policy denies unauthenticated or non-TLS requests. |
| **Tampering** | Attacker modifies historical daily spend records or injects arbitrary configuration values. | Distortion of credit runway and burn forecasting. | - The Web Lambda execution role is strictly restricted to writing only to `frugality/settings/*`; it cannot tamper with `daily_costs.json` or `inventory.json`.<br/>- Strong type validation clamps all numerical inputs (amounts $\ge 0$, reset days between 1 and 31). |
| **Repudiation** | An administrator alters budget limits or thresholds without an audit trail. | Inability to track changes or account for cost spikes. | - CloudWatch Log Groups capture execution events, invocation parameters, and identity.<br/>- Process identity exposed via `/proc/self/comm` confirms runtime state. |
| **Information Disclosure** | Unauthorized third parties access AWS account internal infrastructure details or credentials. | Exposure of account topology or resource ARNs. | - Zero credentials or secrets stored in code or S3.<br/>- Healthz and cost APIs expose aggregated metrics and resource counts without leaking sensitive environmental tokens. |
| **Denial of Service** | Volumetric HTTP requests flood the public Function URL, exhausting concurrency. | Service degradation or temporary throttling. | - Reserved concurrent execution limits protect account quotas.<br/>- DuckDB analytics execute in-memory in $<5\text{ ms}$, ensuring near-instant response times without blocking database connections. |
| **Elevation of Privilege** | Compromised Web Lambda attempts to delete buckets or alter account infrastructure. | Lateral movement across cloud assets. | - Least-privilege IAM policies grant only `s3:GetObject` and scoped `s3:PutObject`. No IAM, CloudFormation, or admin capabilities granted. |

---

## 3. Residual Risk & Recommendations

1. **Function URL Authentication**:
   - *Current State*: The Function URL is currently configured with `auth_type: NONE` for transparent public reporting and demo access.
   - *Recommendation*: For enterprise environments, configure IAM Authentication (`AWS_IAM`) or attach an AWS WAF WebACL to restrict traffic to corporate CIDR blocks.
2. **S3 Object Versioning & Object Lock**:
   - *Recommendation*: Enable S3 Object Versioning and Object Lock on production buckets to ensure immutable audit trails of cost records.
