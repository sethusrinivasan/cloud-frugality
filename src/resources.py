"""
Active AWS resource inventory scanner for Cloud Frugality.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import os
import re

import boto3

log = logging.getLogger("cloud_frugality.resources")
REGION = os.environ.get("AWS_REGION_NAME") or os.environ.get("AWS_REGION", "us-east-1")


def parse_arn(arn: str) -> tuple[str, str]:
    parts = arn.split(":", 5)
    service = parts[2] if len(parts) > 2 else "unknown"
    tail = parts[5] if len(parts) > 5 else ""
    m = re.split(r"[/:]", tail, maxsplit=1)
    rtype = m[0] if m and m[0] else service
    return service, rtype


def sweep_resources(tagging_client) -> dict[str, dict]:
    found: dict[str, dict] = {}
    paginator = tagging_client.get_paginator("get_resources")
    for page in paginator.paginate(ResourcesPerPage=100):
        for item in page.get("ResourceTagMappingList", []):
            arn = item["ResourceARN"]
            service, rtype = parse_arn(arn)
            tags_list = item.get("Tags", [])
            tags_map = {t.get("Key"): t.get("Value") for t in tags_list if "Key" in t}
            app_name = tags_map.get("ApplicationName") or tags_map.get("Project") or "Frugality"
            found[arn] = {
                "arn": arn,
                "service": service,
                "resource_type": rtype,
                "region": REGION,
                "application_name": app_name,
                "tags": json.dumps(tags_map),
                "created_at": None,
            }
    return found


def enrich_creation_timestamps(records: dict[str, dict]) -> None:
    try:
        lam = boto3.client("lambda", region_name=REGION)
        for page in lam.get_paginator("list_functions").paginate():
            for fn in page.get("Functions", []):
                arn = fn.get("FunctionArn")
                if arn in records:
                    records[arn]["created_at"] = fn.get("LastModified")
    except Exception as exc:
        log.warning("Could not enrich Lambda creation timestamps: %s", exc)

    try:
        rds = boto3.client("rds", region_name=REGION)
        for page in rds.get_paginator("describe_db_instances").paginate():
            for db in page.get("DBInstances", []):
                arn = db.get("DBInstanceArn")
                if arn in records and db.get("InstanceCreateTime"):
                    records[arn]["created_at"] = db["InstanceCreateTime"].isoformat()
    except Exception as exc:
        log.warning("Could not enrich RDS creation timestamps: %s", exc)
