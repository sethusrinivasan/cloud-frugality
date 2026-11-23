"""
Performance and database connection latency instrumentation for Cloud Frugality.
"""
from __future__ import annotations

import logging
import os
import time

log = logging.getLogger("cloud_frugality.metrics")
EMIT_METRICS = os.environ.get("EMIT_METRICS", "true").lower() in ("true", "1", "yes")


class LatencyTracker:
    def __init__(self) -> None:
        self.operations: list[dict] = []
        self.tls_version: str | None = None
        self.tls_cipher: str | None = None
        self.cold_resume: bool = False
        self._start_time = time.perf_counter()

    def record(self, service: str, operation: str, duration_ms: float) -> None:
        self.operations.append({
            "service": service,
            "operation": operation,
            "duration_ms": round(duration_ms, 2),
        })

    def summary(self) -> dict:
        total_ms = sum(op["duration_ms"] for op in self.operations)
        by_svc: dict[str, dict] = {}
        for op in self.operations:
            svc = op["service"]
            if svc not in by_svc:
                by_svc[svc] = {"service": svc, "calls": 0, "total_ms": 0.0, "sub_operations": []}
            by_svc[svc]["calls"] += 1
            by_svc[svc]["total_ms"] = round(by_svc[svc]["total_ms"] + op["duration_ms"], 2)
            by_svc[svc]["sub_operations"].append({
                "operation": op["operation"],
                "total_ms": op["duration_ms"],
            })

        services_list = list(by_svc.values())
        for s in services_list:
            s["percent"] = round((s["total_ms"] / total_ms * 100) if total_ms > 0 else 0.0, 1)

        return {
            "total_ms": round(total_ms, 2),
            "total_calls": len(self.operations),
            "cold_resume": self.cold_resume,
            "tls_version": self.tls_version,
            "tls_cipher": self.tls_cipher,
            "database_status": "Cold Resume (0 -> 0.5 ACU)" if self.cold_resume else "Warm",
            "services": services_list,
        }
