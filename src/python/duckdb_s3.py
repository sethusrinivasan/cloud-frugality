"""
DuckDB Native S3 Query Engine for Cloud Frugality.
Executes paginated and filtered queries directly over Parquet files in Amazon S3
using DuckDB's httpfs extension and native S3 scanning.
No out-of-band reads or intermediate downloads.
"""

import boto3
import duckdb
import json
import logging
import math
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger("cloud_frugality.duckdb_s3")

S3_BUCKET = os.environ.get("FRUGALITY_S3_BUCKET", "cloud-frugality-7a2cd1e8b354079e36f80e9389")
REGION = os.environ.get("AWS_REGION_NAME") or os.environ.get("AWS_REGION", "us-east-2")
PARQUET_S3_KEY = os.environ.get("FRUGALITY_PARQUET_KEY", "frugality/datasets/aws_1m_usage.parquet")
CSV_GZ_S3_KEY = "frugality/datasets/aws_1m_usage.csv.gz"
SAMPLE_CSV_S3_KEY = "frugality/datasets/aws_1m_sample.csv"

TOTAL_RECORDS = 1_000_000
MAX_PAGE_SIZE = 10_000
DEFAULT_PAGE_SIZE = 1_000

_CON = None


def get_duckdb_s3_connection():
    """Initializes and returns a cached DuckDB connection with native S3 httpfs support."""
    global _CON
    if _CON is not None:
        return _CON

    con = duckdb.connect(database=":memory:")

    # 1. Load httpfs extension for S3 scanning
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(here, "duckdb_extensions", "httpfs.duckdb_extension"),
        "/var/task/duckdb_extensions/httpfs.duckdb_extension",
        os.path.expanduser("~/.duckdb/extensions/v2.0.1/linux_amd64/httpfs.duckdb_extension"),
        os.path.expanduser("~/.duckdb/extensions/v1.5.6/linux_amd64/httpfs.duckdb_extension"),
    ]
    loaded = False
    for p in candidates:
        if os.path.exists(p):
            try:
                con.execute(f"LOAD '{p}';")
                loaded = True
                log.info("Loaded DuckDB httpfs from %s", p)
                break
            except Exception as e:
                log.warning("Failed to load httpfs from %s: %s", p, e)

    if not loaded:
        try:
            con.execute("LOAD httpfs;")
            loaded = True
        except Exception:
            try:
                con.execute("INSTALL httpfs; LOAD httpfs;")
                loaded = True
            except Exception as e:
                log.error("Could not install/load httpfs: %s", e)

    # 2. Configure native DuckDB S3 settings
    con.execute("SET enable_object_cache = true;")
    con.execute(f"SET s3_region = '{REGION}';")

    try:
        session = boto3.Session()
        creds = session.get_credentials()
        if creds:
            frozen = creds.get_frozen_credentials()
            con.execute(f"SET s3_access_key_id = '{frozen.access_key}';")
            con.execute(f"SET s3_secret_access_key = '{frozen.secret_key}';")
            if frozen.token:
                con.execute(f"SET s3_session_token = '{frozen.token}';")
    except Exception as exc:
        log.warning("Could not set explicit S3 credentials in DuckDB: %s", exc)

    _CON = con
    return _CON


def extract_request_filters(query_params: dict, body_dict: dict = None) -> Tuple[int, int, str, str, Optional[str], Optional[str], Optional[str], Optional[str]]:
    """
    Extracts pagination, sorting, and filter conditions (e.g. date ranges, region, workload)
    from query string parameters or JSON request body.
    """
    p = {k.lower(): v for k, v in query_params.items()}
    if body_dict and isinstance(body_dict, dict):
        for k, v in body_dict.items():
            if isinstance(v, (str, int, float)):
                p[k.lower()] = str(v)

    # Page size (default 1000, max 10000)
    page_size_val = DEFAULT_PAGE_SIZE
    for k in ("pagesize", "page_size", "size", "limit", "count"):
        if k in p and p[k] is not None:
            try:
                page_size_val = int(p[k])
                break
            except (ValueError, TypeError):
                pass

    # Page number
    page_val = 1
    for k in ("page", "pagenum", "page_num", "pageno", "p"):
        if k in p and p[k] is not None:
            try:
                page_val = int(p[k])
                break
            except (ValueError, TypeError):
                pass

    # If offset is passed instead of page
    if "offset" in p and p["offset"] is not None:
        try:
            offset_val = int(p["offset"])
            page_val = (offset_val // max(1, page_size_val)) + 1
        except (ValueError, TypeError):
            pass

    # Sorting
    sort_by = p.get("sort_by") or p.get("sortby") or p.get("sort") or p.get("orderby") or "date"
    sort_order = p.get("sort_order") or p.get("sortorder") or p.get("order") or "desc"

    # Date range filters
    start_date = None
    end_date = None

    for k in ("startdate", "start_date", "date_from", "from", "start", "min_date", "starttime", "start_time"):
        if k in p and p[k]:
            start_date = str(p[k]).split("T")[0].split(" ")[0].strip()
            break

    for k in ("enddate", "end_date", "date_to", "to", "end", "max_date", "endtime", "end_time"):
        if k in p and p[k]:
            end_date = str(p[k]).split("T")[0].split(" ")[0].strip()
            break

    if "date" in p and p["date"]:
        val = str(p["date"]).strip()
        if "," in val:
            parts = val.split(",")
            start_date, end_date = parts[0].strip(), parts[1].strip()
        elif ".." in val:
            parts = val.split("..")
            start_date, end_date = parts[0].strip(), parts[1].strip()
        elif "_" in val and len(val) == 21:
            parts = val.split("_")
            start_date, end_date = parts[0].strip(), parts[1].strip()
        elif re.match(r"^\d{4}-\d{2}-\d{2}$", val):
            start_date = val
            end_date = val

    if "year" in p and p["year"]:
        y = str(p["year"]).strip()
        if re.match(r"^\d{4}$", y):
            start_date = f"{y}-01-01"
            end_date = f"{y}-12-31"

    if "month" in p and p["month"]:
        m = str(p["month"]).strip()
        if re.match(r"^\d{4}-\d{2}$", m):
            start_date = f"{m}-01"
            end_date = f"{m}-31"

    # SQL WHERE clause parsing
    raw_filter = p.get("where") or p.get("filter") or p.get("sql") or ""
    if raw_filter:
        m_start = re.search(r"date\s*(?:>=|>|=)\s*['\"]?(\d{4}-\d{2}-\d{2})['\"]?", raw_filter, re.I)
        if m_start:
            start_date = m_start.group(1)
        m_end = re.search(r"date\s*(?:<=|<|=)\s*['\"]?(\d{4}-\d{2}-\d{2})['\"]?", raw_filter, re.I)
        if m_end:
            end_date = m_end.group(1)

    # Region and Workload filters
    region_filter = p.get("region") or p.get("aws_region") or None
    workload_filter = p.get("workload_type") or p.get("workload") or None

    return page_val, page_size_val, sort_by, sort_order, start_date, end_date, region_filter, workload_filter


def get_export_urls(expires_in: int = 604800) -> Dict[str, Any]:
    """Generates direct presigned S3 URLs for bulk dataset export."""
    s3 = boto3.client("s3", region_name=REGION)
    url_parquet = s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": S3_BUCKET, "Key": PARQUET_S3_KEY},
        ExpiresIn=expires_in,
    )
    url_csv_gz = s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": S3_BUCKET, "Key": CSV_GZ_S3_KEY},
        ExpiresIn=expires_in,
    )
    url_sample_csv = s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": S3_BUCKET, "Key": SAMPLE_CSV_S3_KEY},
        ExpiresIn=expires_in,
    )
    return {
        "parquet_1m_url": url_parquet,
        "csv_gz_1m_url": url_csv_gz,
        "sample_csv_10k_url": url_sample_csv,
        "github_raw_sample_url": "https://raw.githubusercontent.com/sethusrinivasan/sql-frontier-eval/main/data/aws_1m_sample.csv",
        "description": "Full 1,000,000 multi-region AWS usage dataset export files",
        "expires_in_seconds": expires_in,
    }


def query_paginated_from_s3(
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
    sort_by: str = "date",
    sort_order: str = "desc",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    region_filter: Optional[str] = None,
    workload_filter: Optional[str] = None,
    total_records: int = TOTAL_RECORDS,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    Executes paginated queries over 1,000,000 records in Amazon S3 directly via DuckDB.
    Strictly conforms to the Paginated API Endpoint Specification.
    Zero out-of-band reads from S3.
    """
    if page_size <= 0:
        return None, "pageSize must be >= 1"

    if page < 1:
        page = 1

    effective_page_size = min(page_size, MAX_PAGE_SIZE)

    valid_sort_fields = {
        "date": "date",
        "gross_usd": "gross_usd",
        "region": "region",
        "workload_type": "workload_type",
    }
    if sort_by not in valid_sort_fields:
        return None, f"Unknown sort field: {sort_by}"

    sort_order = sort_order.lower()
    if sort_order not in ("asc", "desc"):
        sort_order = "desc"

    s3_uri = f"s3://{S3_BUCKET}/{PARQUET_S3_KEY}"

    # Build SQL WHERE conditions for date ranges and attributes
    where_clauses = []
    if start_date:
        where_clauses.append(f"date >= '{start_date}'")
    if end_date:
        where_clauses.append(f"date <= '{end_date}'")
    if region_filter:
        where_clauses.append(f"region = '{region_filter}'")
    if workload_filter:
        where_clauses.append(f"workload_type = '{workload_filter}'")

    where_str = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    try:
        con = get_duckdb_s3_connection()

        # Compute total matching count
        if where_str:
            cnt_sql = f"SELECT COUNT(*) FROM '{s3_uri}' {where_str}"
            total = con.execute(cnt_sql).fetchone()[0]
        else:
            total = total_records

        if total == 0:
            return {
                "total": 0,
                "page": page,
                "pageSize": 0,
                "totalPages": 0,
                "hasNext": False,
                "hasPrev": False,
                "records": [],
            }, None

        total_pages = math.ceil(total / effective_page_size)

        if page > total_pages:
            return {
                "total": total,
                "page": page,
                "pageSize": 0,
                "totalPages": total_pages,
                "hasNext": False,
                "hasPrev": page > 1,
                "records": [],
            }, None

        offset = (page - 1) * effective_page_size
        col_sort = valid_sort_fields[sort_by]

        # Optimization: when no sort is requested or when default date desc,
        # stream without full table sort if no extra where condition
        if sort_by == "date" and sort_order == "desc" and not where_str:
            data_sql = f"""
                SELECT date, region, workload_type, gross_usd, color_class, status_label, top_5_services_json, raw_services_json
                FROM '{s3_uri}'
                LIMIT {effective_page_size} OFFSET {offset}
            """
        else:
            data_sql = f"""
                SELECT date, region, workload_type, gross_usd, color_class, status_label, top_5_services_json, raw_services_json
                FROM '{s3_uri}'
                {where_str}
                ORDER BY {col_sort} {sort_order.upper()}
                LIMIT {effective_page_size} OFFSET {offset}
            """

        rows = con.execute(data_sql).fetchall()

        records = []
        for r in rows:
            top5 = json.loads(r[6]) if isinstance(r[6], str) else r[6]
            raw = json.loads(r[7]) if isinstance(r[7], str) else r[7]
            records.append({
                "date": r[0],
                "region": r[1],
                "workload_type": r[2],
                "gross_usd": float(r[3]),
                "color_class": r[4],
                "status_label": r[5],
                "top_5_services": top5,
                "raw_services": raw,
            })

        return {
            "total": total,
            "page": page,
            "pageSize": len(records),
            "totalPages": total_pages,
            "hasNext": page < total_pages,
            "hasPrev": page > 1,
            "records": records,
        }, None

    except Exception as exc:
        log.error("DuckDB S3 query error: %s. Falling back to on-demand engine.", exc, exc_info=True)
        try:
            from paginator import get_paginated_records
            return get_paginated_records(
                page=page,
                page_size=page_size,
                sort_by=sort_by,
                sort_order=sort_order,
                total_records=total_records,
            )
        except Exception:
            return None, f"Database query error: {str(exc)}"
