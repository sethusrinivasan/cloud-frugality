"""
tests/test_aws_emulator.py
Automated validation of Cloud Frugality against the local AWS Emulator (released Nov 2026).
Validates S3 data lake persistence, DuckDB query execution, settings management,
and web dashboard rendering with zero cloud costs.
"""
from __future__ import annotations

import json
import os
import ssl
import subprocess
import sys
import time
import urllib.request
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.abspath(os.path.join(HERE, "..", "src"))
sys.path.insert(0, SRC)

import boto3
from botocore.config import Config
from store import FrugalityStore
import web

EMULATOR_PORT = int(os.getenv("EMULATOR_PORT", "9297"))
EMULATOR_ENDPOINT = os.getenv("AWS_ENDPOINT_URL", f"https://127.0.0.1:{EMULATOR_PORT}")
CA_BUNDLE_PATH = os.path.expanduser(f"~/.aws/emulator/{EMULATOR_PORT}/ca.pem")
VERIFY_SSL = CA_BUNDLE_PATH if os.path.isfile(CA_BUNDLE_PATH) else False

_insecure_ctx = ssl.create_default_context()
_insecure_ctx.check_hostname = False
_insecure_ctx.verify_mode = ssl.CERT_NONE


def _http_get(url: str, timeout: float = 3.0) -> tuple[int, str]:
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, context=_insecure_ctx, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8")
    except Exception as exc:
        return 0, str(exc)


@pytest.fixture(scope="session")
def emulator_service():
    """Ensure local AWS Emulator is running and healthy."""
    # 1. Check if emulator is already listening
    status, body = _http_get(f"{EMULATOR_ENDPOINT}/__admin/health", timeout=2)
    if status == 200 and "ok" in body.lower():
        yield EMULATOR_ENDPOINT
        return

    # 2. Look for binary
    bin_path = os.path.expanduser("~/.local/bin/aws-emulator")
    if not os.path.isfile(bin_path):
        bin_path = os.path.expanduser("~/.aws-emulator/opt/aws-emulator/bin/aws-emulator")
    if not os.path.isfile(bin_path):
        pytest.skip(f"AWS Emulator binary not found at {bin_path} and endpoint not responding.")

    emu_env = os.environ.copy()
    emu_env["EMULATOR_TELEMETRY"] = "off"
    emu_env["AWS_CLI_TELEMETRY_OPTOUT"] = "1"
    emu_env["AWS_CSM_ENABLED"] = "false"

    cfg_dir = os.path.expanduser("~/.aws/emulator")
    os.makedirs(cfg_dir, exist_ok=True)
    cfg_file = os.path.join(cfg_dir, "config.toml")
    if not os.path.isfile(cfg_file):
        with open(cfg_file, "w") as f:
            f.write("[telemetry]\nenabled = false\n")

    proc = subprocess.Popen(
        [bin_path, "-b", "127.0.0.1", "-p", str(EMULATOR_PORT), "--telemetry", "off", "-a", "off"],
        env=emu_env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    started = False
    for _ in range(25):
        time.sleep(0.4)
        status, body = _http_get(f"{EMULATOR_ENDPOINT}/__admin/health", timeout=2)
        if status == 200 and "ok" in body.lower():
            started = True
            break

    if not started:
        proc.terminate()
        pytest.skip(f"Could not connect to AWS Emulator on {EMULATOR_ENDPOINT}")

    try:
        yield EMULATOR_ENDPOINT
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except Exception:
            proc.kill()


@pytest.fixture
def s3_client(emulator_service):
    return boto3.client(
        "s3",
        endpoint_url=emulator_service,
        region_name="us-east-2",
        aws_access_key_id="test",
        aws_secret_access_key="test",
        verify=VERIFY_SSL,
        config=Config(s3={"addressing_style": "path"}),
    )


def test_emulator_health(emulator_service):
    status, body = _http_get(f"{emulator_service}/__admin/health", timeout=5)
    assert status == 200
    assert "ok" in body.lower()


def test_s3_storage_and_duckdb_over_emulator(s3_client, monkeypatch):
    import shutil
    import tempfile
    temp_dir = tempfile.mkdtemp()
    bucket_name = "frugality-emulator-test-bucket"
    try:
        s3_client.create_bucket(
            Bucket=bucket_name,
            CreateBucketConfiguration={"LocationConstraint": "us-east-2"},
        )
    except Exception:
        pass  # Bucket might already exist

    monkeypatch.setenv("FRUGALITY_S3_BUCKET", bucket_name)
    monkeypatch.setenv("AWS_ENDPOINT_URL", EMULATOR_ENDPOINT)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
    monkeypatch.setenv("AWS_CA_BUNDLE", CA_BUNDLE_PATH if os.path.isfile(CA_BUNDLE_PATH) else "")

    store = FrugalityStore(bucket=bucket_name, local_dir=temp_dir)

    try:
        # 1. Test Settings persistence to S3
        store.save_settings({
            "budget_type": "monthly",
            "monthly_credit_amount": 350.0,
            "monthly_reset_day": 5,
            "daily_baseline_usd": 0.70,
        })

        # Verify object in S3 directly
        resp = s3_client.get_object(Bucket=bucket_name, Key=f"{store.prefix}/settings/config.json")
        saved_cfg = json.loads(resp["Body"].read().decode("utf-8"))
        assert saved_cfg["monthly_credit_amount"] == 350.0
        assert saved_cfg["monthly_reset_day"] == 5
        assert saved_cfg["daily_baseline_usd"] == 0.70

        # 2. Save Daily Costs & Test DuckDB Analytics
        store.save_daily_cost({
            "date": "2026-11-23",
            "gross_usd": 0.82,
            "net_usd": 0.0,
            "credit_usd": -0.82,
            "services": {
                "Amazon Relational Database Service": 0.60,
                "AmazonCloudWatch": 0.22,
            },
            "service_subcosts": {
                "Amazon Relational Database Service": {
                    "Aurora Serverless ACU": 0.45,
                    "Storage IO": 0.15,
                },
                "AmazonCloudWatch": {
                    "MetricStorage": 0.22,
                },
            },
            "app_tags": {
                "Frugality": 0.70,
                "Untagged": 0.12,
            },
        })

        summary = store.query_cost_summary(window_days=30)
        assert summary["window_gross_usd"] == 0.82
        assert summary["top_services"][0]["acronym"] == "RDS"
        assert summary["top_services"][0]["subcosts"][0]["subcost"] == "Aurora Serverless ACU"
        assert summary["daily"][0]["color_class"] == "cost-red"  # 0.82 > 0.70 baseline
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_emulator_web_dashboard_end_to_end(emulator_service, monkeypatch):
    monkeypatch.setenv("AWS_ENDPOINT_URL", emulator_service)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")

    # 1. Probing web dashboard
    res_dash = web.lambda_handler({"rawPath": "/", "httpMethod": "GET"}, None)
    assert res_dash["statusCode"] == 200
    assert "Cloud Frugality" in res_dash["body"]
    assert "Credits Remaining" in res_dash["body"]
    assert "Breakdown by ApplicationName tag (30-day roll-up, gross)" in res_dash["body"]
    assert "Top Services Spend" in res_dash["body"]
    assert "Trend (30d)" in res_dash["body"]

    # 2. Probing settings page
    res_settings = web.lambda_handler({"rawPath": "/settings", "httpMethod": "GET"}, None)
    assert res_settings["statusCode"] == 200
    assert "Option 1: Fixed Budget with Calendar Expiry" in res_settings["body"]
    assert "Option 2: Monthly Credits (Resets Every Month)" in res_settings["body"]

    # 3. Probing health check
    res_health = web.lambda_handler({"rawPath": "/healthz", "httpMethod": "GET"}, None)
    assert res_health["statusCode"] == 200
    health_data = json.loads(res_health["body"])
    assert health_data["status"] == "healthy"
    assert health_data["tag"] == "Frugality"


def test_emulator_cost_explorer_not_implemented_bug(emulator_service):
    """
    FAITHFUL EMULATOR BUG REPORT:
    The AWS Emulator (v1.0.481, Nov 2026) advertises Cost Explorer (ce) support,
    but calling GetCostAndUsage fails with:
    ClientError: NotImplemented - 'operation GetCostAndUsage is scaffolded but not implemented in this emulator'.
    This test verifies and documents this exact upstream emulator limitation so it is never masked.
    """
    import botocore.exceptions
    ce_client = boto3.client(
        "ce",
        endpoint_url=emulator_service,
        region_name="us-east-1",
        aws_access_key_id="test",
        aws_secret_access_key="test",
        verify=False,
    )
    with pytest.raises(botocore.exceptions.ClientError) as exc_info:
        ce_client.get_cost_and_usage(
            TimePeriod={"Start": "2026-11-01", "End": "2026-11-20"},
            Granularity="DAILY",
            Metrics=["UnblendedCost"],
        )
    err = exc_info.value.response.get("Error", {})
    assert err.get("Code") == "NotImplemented", f"Expected NotImplemented from emulator, got {err}"
    assert "scaffolded but not implemented" in err.get("Message", "").lower(), (
        f"Expected 'scaffolded but not implemented' message, got: {err.get('Message')}"
    )


def test_emulator_s3_location_constraint_behavior(emulator_service):
    """
    FAITHFUL EMULATOR BEHAVIOR TEST:
    The AWS Emulator strictly validates S3 LocationConstraint:
    Creating a bucket in non-default region (us-east-2) without LocationConstraint
    raises IllegalLocationConstraintException. Specifying LocationConstraint succeeds.
    """
    from botocore.exceptions import ClientError
    bucket_name = "frugality-loc-constraint-test"
    s3_reg2 = boto3.client(
        "s3",
        endpoint_url=emulator_service,
        region_name="us-east-2",
        aws_access_key_id="test",
        aws_secret_access_key="test",
        verify=False,
    )

    # 1. Without constraint -> raises IllegalLocationConstraintException
    with pytest.raises(ClientError) as exc_info:
        s3_reg2.create_bucket(Bucket=bucket_name)
    assert exc_info.value.response.get("Error", {}).get("Code") == "IllegalLocationConstraintException"

    # 2. With constraint -> succeeds
    resp = s3_reg2.create_bucket(
        Bucket=bucket_name,
        CreateBucketConfiguration={"LocationConstraint": "us-east-2"},
    )
    assert resp["ResponseMetadata"]["HTTPStatusCode"] in (200, 204)


def test_emulator_free_tier_fidelity(emulator_service):
    """
    FAITHFUL EMULATOR BEHAVIOR TEST:
    Verifies that the emulator's FreeTier mock service responds to GetFreeTierUsage
    and returns sample free tier allowances.
    """
    ft_client = boto3.client(
        "freetier",
        endpoint_url=emulator_service,
        region_name="us-east-1",
        aws_access_key_id="test",
        aws_secret_access_key="test",
        verify=False,
    )
    resp = ft_client.get_free_tier_usage()
    assert "freeTierUsages" in resp
    assert len(resp["freeTierUsages"]) > 0
    services = [u["service"] for u in resp["freeTierUsages"]]
    assert "AmazonEC2" in services
    assert "AmazonS3" in services


def test_emulator_sts_caller_identity(emulator_service):
    """
    FAITHFUL EMULATOR BEHAVIOR TEST:
    Verifies that STS on the emulator returns the default mock user identity:
    Account: '000000000000', Arn: 'arn:aws:iam::000000000000:user/emulator'.
    """
    sts_client = boto3.client(
        "sts",
        endpoint_url=emulator_service,
        region_name="us-east-1",
        aws_access_key_id="test",
        aws_secret_access_key="test",
        verify=False,
    )
    identity = sts_client.get_caller_identity()
    assert identity["Account"] == "000000000000"
    assert "emulator" in identity["Arn"]
