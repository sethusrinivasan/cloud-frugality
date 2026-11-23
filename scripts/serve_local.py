#!/usr/bin/env python3
"""
scripts/serve_local.py
Serves Cloud Frugality local servers:
- Python implementation on port 8090 (http://localhost:8090/)
- Rust implementation on port 8091 (http://localhost:8091/)

Both servers run concurrently with interactive toggles between them in the dashboard header.
"""
from __future__ import annotations

import argparse
import http.server
import json
import os
import subprocess
import sys
import threading
import time
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(HERE, ".."))
SRC_DIR = os.path.join(PROJECT_ROOT, "src")
RUST_DIR = os.path.join(SRC_DIR, "rust")

# Re-execute under virtualenv Python if launched directly with system Python
if sys.prefix == sys.base_prefix:
    venv_py = os.path.join(PROJECT_ROOT, ".venv", "bin", "python")
    if os.path.isfile(venv_py) and sys.executable != venv_py:
        os.execv(venv_py, [venv_py] + sys.argv)

sys.path.insert(0, SRC_DIR)

import web

PYTHON_PORT = int(os.environ.get("PYTHON_PORT", "8090"))
RUST_PORT = int(os.environ.get("RUST_PORT", "8091"))


class PythonLambdaProxyHandler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self._handle_request("OPTIONS")

    def do_HEAD(self):
        self._handle_request("HEAD")

    def do_GET(self):
        self._handle_request("GET")

    def do_POST(self):
        self._handle_request("POST")

    def _handle_request(self, method: str):
        parsed_url = urllib.parse.urlparse(self.path)
        raw_path = parsed_url.path or "/"

        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length).decode("utf-8") if content_length > 0 else ""
        headers = {k.lower(): v for k, v in self.headers.items()}

        event = {
            "rawPath": raw_path,
            "httpMethod": method,
            "queryStringParameters": dict(urllib.parse.parse_qsl(parsed_url.query)),
            "headers": headers,
            "body": body,
            "isBase64Encoded": False,
        }

        try:
            res = web.lambda_handler(event, None)
            status_code = res.get("statusCode", 200)
            res_headers = res.get("headers", {})
            res_body = res.get("body", "")

            self.send_response(status_code)
            for k, v in res_headers.items():
                self.send_header(k, v)
            self.end_headers()

            if isinstance(res_body, str):
                self.wfile.write(res_body.encode("utf-8"))
            elif isinstance(res_body, bytes):
                self.wfile.write(res_body)
        except Exception as exc:
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            err = json.dumps({"error": str(exc), "status": "server_error"}).encode("utf-8")
            self.wfile.write(err)

    def log_message(self, format, *args):
        sys.stderr.write(f"[Python:8090] {self.address_string()} - - {format % args}\n")


def ensure_rust_binary_built() -> str:
    """Builds or locates the native Rust binary."""
    rust_bin = os.path.join(RUST_DIR, "target", "debug", "cloud-frugality")
    if not os.path.exists(rust_bin):
        print("⚡ Compiling Rust microservice binary...")
        subprocess.run(["cargo", "build"], cwd=RUST_DIR, check=True)
    return rust_bin


def start_rust_server(port: int = RUST_PORT) -> subprocess.Popen:
    rust_bin = ensure_rust_binary_built()
    cmd = [rust_bin, "serve", str(port)]
    env = os.environ.copy()
    env["FRUGALITY_S3_PREFIX"] = "frugality/rust"
    env["LOCAL_DATA_DIR"] = "/tmp/cloud-frugality-data/rust"
    proc = subprocess.Popen(cmd, cwd=PROJECT_ROOT, env=env)
    return proc


def run_python_server(port: int = PYTHON_PORT):
    os.environ["FRUGALITY_S3_PREFIX"] = "frugality/python"
    os.environ["LOCAL_DATA_DIR"] = "/tmp/cloud-frugality-data/python"
    server_address = ("0.0.0.0", port)
    httpd = HTTPServer(server_address, PythonLambdaProxyHandler)
    httpd.serve_forever()


def main():
    parser = argparse.ArgumentParser(description="Cloud Frugality Multi-Implementation Server Runner")
    parser.add_argument(
        "--engine",
        choices=["python", "rust", "both"],
        default="both",
        help="Which engine to run: 'python' (:8090), 'rust' (:8091), or 'both' (default)",
    )
    args = parser.parse_args()

    print("==================================================================")
    print("  Cloud Frugality Multi-Engine Server Environment")
    print("==================================================================")

    rust_proc = None
    if args.engine in ("rust", "both"):
        print(f"🦀 Launching Rust Server on http://localhost:{RUST_PORT}/")
        rust_proc = start_rust_server(RUST_PORT)
        time.sleep(0.5)

    if args.engine in ("python", "both"):
        print(f"🐍 Launching Python Server on http://localhost:{PYTHON_PORT}/")
        print("------------------------------------------------------------------")
        print(f"  Python Dashboard: http://localhost:{PYTHON_PORT}/")
        print(f"  Rust Dashboard:   http://localhost:{RUST_PORT}/")
        print(f"  Toggle in navbar switches between implementations instantly!")
        print("==================================================================")
        sys.stdout.flush()
        try:
            run_python_server(PYTHON_PORT)
        except KeyboardInterrupt:
            print("\nShutting down servers...")
        finally:
            if rust_proc:
                rust_proc.terminate()
    elif args.engine == "rust":
        print("------------------------------------------------------------------")
        print(f"  Rust Dashboard:   http://localhost:{RUST_PORT}/")
        print(f"  Rust Healthz:     http://localhost:{RUST_PORT}/healthz")
        print("==================================================================")
        try:
            rust_proc.wait()
        except KeyboardInterrupt:
            if rust_proc:
                rust_proc.terminate()


if __name__ == "__main__":
    main()
