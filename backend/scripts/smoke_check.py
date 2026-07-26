"""HTTP smoke checks for a running tennis_oracle stack (local / staging / prod-like).

Usage (API only):
  python backend/scripts/smoke_check.py --base-url http://localhost:8001

With frontend:
  python backend/scripts/smoke_check.py \\
    --base-url http://localhost:8001 \\
    --frontend-url http://localhost:5174

Exit 0 on success; non-zero on failure. No credentials required for /health and /ready.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from typing import Any


def _get_json(url: str, timeout: float) -> tuple[int, Any]:
    req = urllib.request.Request(url, method="GET", headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8")
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            payload = body
        return int(resp.status), payload


def _get_status(url: str, timeout: float) -> int:
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return int(resp.status)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="tennis_oracle smoke checks")
    parser.add_argument(
        "--base-url",
        default="http://localhost:8000",
        help="API base URL without trailing slash (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--frontend-url",
        default="",
        help="Optional SPA base URL (e.g. http://localhost:5174)",
    )
    parser.add_argument("--timeout", type=float, default=10.0, help="HTTP timeout seconds")
    parser.add_argument(
        "--expect-env",
        default="",
        help="If set, require health/ready JSON environment field to match (e.g. staging)",
    )
    args = parser.parse_args(argv)

    base = args.base_url.rstrip("/")
    errors: list[str] = []

    try:
        status, payload = _get_json(f"{base}/health", args.timeout)
        if status != 200:
            errors.append(f"/health status={status}")
        elif not isinstance(payload, dict) or payload.get("status") != "ok":
            errors.append(f"/health unexpected body: {payload}")
        elif args.expect_env and payload.get("environment") != args.expect_env:
            errors.append(
                f"/health environment={payload.get('environment')!r} expected {args.expect_env!r}"
            )
        else:
            print(f"OK  GET {base}/health -> {status}")
    except urllib.error.HTTPError as exc:
        errors.append(f"/health HTTP {exc.code}")
    except Exception as exc:  # noqa: BLE001 — smoke aggregates failures
        errors.append(f"/health error: {exc}")

    try:
        status, payload = _get_json(f"{base}/ready", args.timeout)
        if status != 200:
            errors.append(f"/ready status={status} body={payload}")
        elif not isinstance(payload, dict) or payload.get("status") != "ready":
            errors.append(f"/ready unexpected body: {payload}")
        elif payload.get("database") != "ok":
            errors.append(f"/ready database not ok: {payload}")
        elif args.expect_env and payload.get("environment") != args.expect_env:
            errors.append(
                f"/ready environment={payload.get('environment')!r} expected {args.expect_env!r}"
            )
        else:
            print(f"OK  GET {base}/ready -> {status}")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        errors.append(f"/ready HTTP {exc.code} body={body}")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"/ready error: {exc}")

    if args.frontend_url:
        fe = args.frontend_url.rstrip("/")
        try:
            status = _get_status(f"{fe}/", args.timeout)
            if status != 200:
                errors.append(f"frontend {fe}/ status={status}")
            else:
                print(f"OK  GET {fe}/ -> {status}")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"frontend error: {exc}")

    if errors:
        print("SMOKE FAILED:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    print("SMOKE PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
