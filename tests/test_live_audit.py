"""
Live verification audit suite for Cloud Frugality.

Enforces zero drift and real operational integrity:
- Verifies real HTTP responses (HTML, JSON, /healthz)
- Checks /proc/self/comm genuine runtime identity
- Audits AWS Lambda tags to confirm tag "Frugality" is applied
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
import boto3

REGION = os.environ.get("AWS_REGION_NAME") or os.environ.get("AWS_REGION", "us-east-2")


def get_live_url() -> str:
    if os.environ.get("COST_WEB_URL"):
        return os.environ["COST_WEB_URL"].rstrip("/")

    cfn = boto3.client("cloudformation", region_name=REGION)
    res = cfn.describe_stacks(StackName="CloudFrugalityStack")
    outputs = res["Stacks"][0]["Outputs"]
    for out in outputs:
        if out["OutputKey"] == "CostWebUrl":
            return out["OutputValue"].rstrip("/")
    raise RuntimeError("CostWebUrl output not found in CloudFrugalityStack")


def test_live_web_dashboard():
    base_url = get_live_url()
    print(f"\n[AUDIT] Probing live HTML dashboard: {base_url}/")
    req = urllib.request.Request(f"{base_url}/", headers={"User-Agent": "AuditBot/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        status = resp.status
        body = resp.read().decode("utf-8")
        headers = dict(resp.headers)

    print(f"[AUDIT] Status: {status}, Content-Type: {headers.get('Content-Type')}")
    assert status == 200, f"Expected 200, got {status}"
    assert "text/html" in headers.get("Content-Type", ""), "Expected HTML content"
    assert "Cloud Frugality" in body, "Dashboard must show Cloud Frugality branding"
    assert "Tag: Frugality" in body, "Dashboard must display Frugality tag badge"
    assert "Last 30 Days" in body, "Dashboard must contain 30-day metrics"
    print("[AUDIT] PASS: Live HTML dashboard is genuine and contains full metrics.")


def test_live_json_api():
    base_url = get_live_url()
    print(f"\n[AUDIT] Probing live JSON API: {base_url}/api/costs")
    req = urllib.request.Request(f"{base_url}/api/costs", headers={"User-Agent": "AuditBot/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        status = resp.status
        data = json.loads(resp.read().decode("utf-8"))

    print(f"[AUDIT] Status: {status}")
    assert status == 200, f"Expected 200, got {status}"
    assert "window_gross_usd" in data, "window_gross_usd missing from JSON API"
    assert isinstance(data["window_gross_usd"], (int, float)), "window_gross_usd must be numeric"
    assert "resource_count" in data, "resource_count missing from JSON API"
    assert data["resource_count"] > 0, "resource_count must be > 0"
    assert "daily" in data and len(data["daily"]) > 0, "daily cost records must not be empty"
    assert "latency_breakdown" in data, "latency_breakdown must be present"
    print(f"[AUDIT] PASS: JSON API verified with {data['resource_count']} resources, ${data['window_gross_usd']} gross spend.")


def test_live_runtime_identity():
    base_url = get_live_url()
    print(f"\n[AUDIT] Probing live runtime identity: {base_url}/healthz")
    req = urllib.request.Request(f"{base_url}/healthz", headers={"User-Agent": "AuditBot/1.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        status = resp.status
        data = json.loads(resp.read().decode("utf-8"))

    print(f"[AUDIT] Healthz response: {data}")
    assert status == 200, f"Expected 200, got {status}"
    assert data.get("status") == "healthy", "Expected healthy status"
    assert data.get("service") == "cloud-frugality", "Expected cloud-frugality service"
    assert data.get("comm") in ("python", "python3", "python3.12"), f"Expected genuine python process comm, got {data.get('comm')}"
    assert "aarch64" in data.get("platform", "").lower(), f"Expected aarch64 Graviton platform, got {data.get('platform')}"
    assert data.get("tag") == "Frugality", "Expected Frugality tag in health identity"
    print("[AUDIT] PASS: Genuine runtime identity confirmed (/proc/self/comm is 'python').")


def test_aws_resource_tags():
    print(f"\n[AUDIT] Verifying AWS tags on deployed Lambda functions...")
    lam = boto3.client("lambda", region_name=REGION)
    for fn_name in ["cloud-frugality-collector", "cloud-frugality-web"]:
        tags = lam.list_tags(Resource=f"arn:aws:lambda:{REGION}:596090776030:function:{fn_name}")["Tags"]
        print(f"[AUDIT] Tags on {fn_name}: {tags}")
        assert "Frugality" in tags, f"Function {fn_name} is missing 'Frugality' tag"
        assert tags["Frugality"] == "true", f"Function {fn_name} 'Frugality' tag is not 'true'"
    print("[AUDIT] PASS: AWS resource tags confirmed on live infrastructure.")


if __name__ == "__main__":
    test_live_web_dashboard()
    test_live_json_api()
    test_live_runtime_identity()
    test_aws_resource_tags()
    print("\n[AUDIT] ALL LIVE TESTS PASSED SUCCESSFULLY ✔")
