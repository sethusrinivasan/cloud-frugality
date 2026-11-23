# Cloud Frugality Testing & Validation Strategy

## 1. Overview & Anti-Drift Philosophy

Cloud Frugality adheres to strict anti-drift engineering principles:
- **Zero Hollow Mocks**: Tests execute against real database drivers and genuine storage protocols.
- **Strict Data Assertions**: Tests assert exact numeric ranges, schema contracts, and non-empty payloads.
- **Genuine Runtime Verification**: Live and local audits verify kernel process comm identity (`/proc/self/comm`), ensuring tests execute against real Python runtimes rather than proxy stubs.

---

## 2. Test Suites

### Unit & Analytical Testing (`pytest tests/`)
- `tests/test_billing.py`:
  - Validates credit exhaustion vs. calendar expiry binding constraints.
  - Tests zero-burn and missing data edge cases.
  - Tests daily cost baseline threshold classification (RED $> \$0.70$, YELLOW $70\%\text{--}100\%$, GREEN $< 70\%$).
  - Validates Option 1 (fixed budget) and Option 2 (monthly credit reset) calculation engines.
- `tests/test_store.py`:
  - Verifies service acronym generation rules (stripping Amazon/AWS, 3-letter fallback, well-known acronyms).
  - Tests S3 + DuckDB storage lifecycle in isolated temporary directories.
  - Validates DuckDB in-memory analytical SQL queries for window totals, top service sub-costs, 30-day sparklines, and tag roll-ups.
- `tests/test_web.py`:
  - Validates full HTML dashboard rendering: "Credits Remaining", ApplicationName breakdown, sparklines, acronym badges with tooltips, removal of Net/Credits columns, and sortable 10-row pagination.
  - Tests `/settings` GET and POST workflows.
  - Tests `/api/settings` and `/api/costs` JSON APIs.
  - Validates `/healthz` runtime identity.
- `tests/test_resources.py`:
  - Validates ARN parsing across AWS services (Lambda, RDS, S3).
  - Tests tag inventory sweep and pagination.

---

## 3. Local AWS Emulator Integration

Cloud Frugality natively supports local testing against the **AWS Emulator** (announced Nov 2026, `https://aws.amazon.com/about-aws/whats-new/2026/11/aws-emulator-now-available/`).

### How It Works
- The test harness (`tests/test_aws_emulator.py`) probes `https://127.0.0.1:9297/__admin/health`.
- If the emulator is not already running, the harness launches `~/.local/bin/aws-emulator` with telemetry disabled (`--telemetry off -a off`).
- Boto3 connects to the local TLS endpoint using path-style S3 addressing (`Config(s3={'addressing_style': 'path'})`).
- S3 buckets, object persistence, DuckDB queries, and Lambda handlers are verified end-to-end locally with **zero AWS cloud cost**.

### Faithful Reporting of Upstream Emulator Limitations
Cloud Frugality's test suite tests against the emulator without masking or spoofing upstream limitations:
1. **Cost Explorer (`ce:GetCostAndUsage`) 501 Bug**:
   - Calling `ce.get_cost_and_usage(...)` raises `botocore.exceptions.ClientError: NotImplemented: operation GetCostAndUsage is scaffolded but not implemented in this emulator`.
   - Correlated with upstream issue: [aws/aws-emulator#383](https://github.com/aws/aws-emulator/issues/383) (*"Cost Explorer: GetCostAndUsage, GetCostForecast and GetAnomalies return 501"*).
   - Our test `test_emulator_cost_explorer_not_implemented_bug` explicitly asserts this error so any future fix by the AWS Emulator team is automatically surfaced.
2. **S3 Region Location Constraint**:
   - Creating a bucket in `us-east-2` without `CreateBucketConfiguration={"LocationConstraint": "us-east-2"}` strictly fails with `IllegalLocationConstraintException`.
   - Verified by `test_emulator_s3_location_constraint_behavior`.
3. **Free Tier & STS Fidelity**:
   - `freetier:GetFreeTierUsage` returns mock data (verified by `test_emulator_free_tier_fidelity`).
   - `sts:GetCallerIdentity` returns account `000000000000` (verified by `test_emulator_sts_caller_identity`).

---

## 4. Execution Scripts

Root-level shell scripts provide straightforward local developer workflows:

```bash
# 1. Start local servers in background (Python :8090, Rust :8091)
./start.sh

# 2. Stop running servers cleanly
./stop.sh

# 3. Run complete automated validation (Rust tests + Python tests + AWS Emulator)
./run_tests.sh
# or convenience alias:
./test.sh

# 4. Deploy infrastructure to AWS via Pulumi
./deploy.sh

# 5. Refresh AWS cloud state and audit live microservice integrity
./refresh.sh
# or refresh and apply pending updates:
./refresh.sh --update
```
