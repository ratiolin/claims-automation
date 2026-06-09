#!/usr/bin/env python3
"""Stage 5 smoke checks for the claims automation MVP.

The script can run in two modes:
- Mock-only: verifies local Mock endpoints and idempotent side effects.
- Workflow mode: if DIFY_MAIN_WORKFLOW_API_KEY is set, invokes Dify /v1/workflows/run
  for each scenario and then checks Mock state/log side effects.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCENARIOS = ROOT / "test-data" / "stage5-scenarios.json"


def request_json(
    method: str,
    url: str,
    *,
    body: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = 60,
) -> tuple[int, Any]:
    data = None
    final_headers = {"Content-Type": "application/json"}
    if headers:
        final_headers.update(headers)
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=final_headers, method=method.upper())
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return resp.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            parsed: Any = json.loads(raw)
        except Exception:
            parsed = {"error": raw}
        return exc.code, parsed


def load_scenarios(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)["scenarios"]


def extract_ids(user_text: str) -> tuple[str, str]:
    import re

    order_match = re.search(r"(\d{5,})", user_text or "")
    user_match = re.search(r"用户(?:ID|Id|id|号)?\s*[:：]?\s*([A-Za-z0-9_-]+)", user_text or "")
    return (order_match.group(0) if order_match else "", user_match.group(1) if user_match else "")


def claim_id_for(order_id: str, user_id: str) -> str:
    return hashlib.sha256(f"{order_id}_{user_id}".encode()).hexdigest()[:16]


def mock_url(base: str, path: str, params: dict[str, Any] | None = None) -> str:
    url = base.rstrip("/") + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    return url


def reset_mock(mock_base: str) -> None:
    status, body = request_json("POST", mock_url(mock_base, "/mock/reset-all"))
    if status >= 400:
        raise RuntimeError(f"mock reset failed: HTTP {status} {body}")


def apply_precondition(mock_base: str, scenario: dict[str, Any]) -> None:
    update = scenario.get("precondition", {}).get("biz_stats_update")
    if update:
        status, body = request_json("POST", mock_url(mock_base, "/mock/biz-stats/update"), body=update)
        if status >= 400:
            raise RuntimeError(f"biz-stats update failed for {scenario['id']}: HTTP {status} {body}")


def check_mock_health(mock_base: str) -> list[str]:
    failures: list[str] = []
    checks = [
        ("GET", "/health", None),
        ("GET", "/mock/order/amount?order_id=10001", None),
        ("GET", "/mock/user/static-risk?user_id=U001", None),
        ("GET", "/mock/logistics/anomaly-type?order_id=10001", None),
        ("GET", "/mock/biz-stats", None),
        ("POST", "/mock/vision/classify", {"file_names": ["订单截图.png", "物流异常截图.png"]}),
        ("POST", "/mock/payment/execute", {"claim_id": "stage5-zero-check", "amount": 0, "user_id": "U001"}),
    ]
    for method, path, body in checks:
        status, payload = request_json(method, mock_url(mock_base, path), body=body)
        if status >= 400:
            failures.append(f"{method} {path} -> HTTP {status}: {payload}")
        if path == "/mock/payment/execute" and payload.get("result") != "skipped":
            failures.append(f"zero payment should be skipped, got {payload}")
    return failures


def run_workflow(
    dify_base: str,
    api_key: str,
    scenario: dict[str, Any],
    *,
    user_prefix: str,
) -> tuple[int, Any, float]:
    inputs = scenario["input"]
    body = {
        "inputs": {
            "user_text": inputs["user_text"],
            "file_list": json.dumps(inputs.get("file_list", []), ensure_ascii=False),
        },
        "response_mode": "blocking",
        "user": f"{user_prefix}-{scenario['id']}",
    }
    headers = {"Authorization": f"Bearer {api_key}"}
    started = time.perf_counter()
    status, payload = request_json("POST", dify_base.rstrip("/") + "/v1/workflows/run", body=body, headers=headers, timeout=180)
    elapsed = time.perf_counter() - started
    return status, payload, elapsed


def get_decision_logs(mock_base: str) -> list[dict[str, Any]]:
    status, body = request_json("GET", mock_url(mock_base, "/mock/decision-log/query", {"days": 7}))
    if status >= 400:
        raise RuntimeError(f"decision log query failed: HTTP {status} {body}")
    return body.get("results", [])


def get_state(mock_base: str, claim_id: str) -> dict[str, Any]:
    status, body = request_json("GET", mock_url(mock_base, "/mock/state-machine/status", {"claim_id": claim_id}))
    if status >= 400:
        return {"error": f"HTTP {status}", "body": body}
    return body


def summarize_workflow_result(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {"raw_type": type(payload).__name__}
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    outputs = data.get("outputs") if isinstance(data.get("outputs"), dict) else {}
    return {
        "workflow_run_id": data.get("id") or payload.get("workflow_run_id"),
        "status": data.get("status") or payload.get("status"),
        "elapsed_time": data.get("elapsed_time"),
        "total_tokens": data.get("total_tokens"),
        "decision": outputs.get("decision"),
        "branch": outputs.get("branch"),
        "payment_body": outputs.get("payment_body"),
        "state_body": outputs.get("state_body"),
        "decision_log_body": outputs.get("decision_log_body"),
        "raw_error": payload.get("message") or payload.get("error"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenarios", type=Path, default=DEFAULT_SCENARIOS)
    parser.add_argument("--mock-base", default=os.getenv("MOCK_BASE", "http://localhost:8080"))
    parser.add_argument("--dify-base", default=os.getenv("DIFY_BASE", "https://dify.metratio.com"))
    parser.add_argument("--main-key", default=os.getenv("DIFY_MAIN_WORKFLOW_API_KEY", ""))
    parser.add_argument("--no-reset", action="store_true")
    parser.add_argument("--workflow", action="store_true", help="require Dify workflow mode; fail if no key is configured")
    args = parser.parse_args()

    scenarios = load_scenarios(args.scenarios)
    if args.workflow and not args.main_key:
        print("DIFY_MAIN_WORKFLOW_API_KEY is required for --workflow", file=sys.stderr)
        return 2

    if not args.no_reset:
        reset_mock(args.mock_base)

    failures = check_mock_health(args.mock_base)
    mode = "workflow" if args.main_key else "mock-only"
    print(json.dumps({"mode": mode, "mock_base": args.mock_base, "mock_health_failures": failures}, ensure_ascii=False))
    if failures:
        return 1

    results: list[dict[str, Any]] = []
    if not args.main_key:
        for scenario in scenarios:
            order_id, user_id = extract_ids(scenario["input"]["user_text"])
            results.append(
                {
                    "id": scenario["id"],
                    "name": scenario["name"],
                    "order_id": order_id,
                    "user_id": user_id,
                    "claim_id": claim_id_for(order_id, user_id) if order_id and user_id else "",
                    "status": "not_run_no_main_key",
                }
            )
        print(json.dumps({"scenarios": results}, ensure_ascii=False, indent=2))
        return 0

    for scenario in scenarios:
        if not args.no_reset:
            reset_mock(args.mock_base)
        apply_precondition(args.mock_base, scenario)
        order_id, user_id = extract_ids(scenario["input"]["user_text"])
        cid = claim_id_for(order_id, user_id) if order_id and user_id else ""
        runs = 2 if scenario.get("run_twice") else 1
        run_results = []
        for i in range(runs):
            status, payload, elapsed = run_workflow(args.dify_base, args.main_key, scenario, user_prefix="codex-stage5")
            run_results.append(
                {
                    "run": i + 1,
                    "http_status": status,
                    "elapsed_seconds": round(elapsed, 3),
                    "summary": summarize_workflow_result(payload),
                }
            )
        logs = [log for log in get_decision_logs(args.mock_base) if log.get("claim_id") == cid]
        state = get_state(args.mock_base, cid) if cid else {}
        result = {
            "id": scenario["id"],
            "name": scenario["name"],
            "claim_id": cid,
            "runs": run_results,
            "state": state,
            "log_count_for_claim": len(logs),
            "latest_log": logs[-1] if logs else None,
        }
        if scenario.get("expected", {}).get("must_have_log") and not logs:
            result["failure"] = "expected decision log entry, got none"
            failures.append(f"{scenario['id']}: missing decision log")
        if any(r["http_status"] >= 400 for r in run_results):
            failures.append(f"{scenario['id']}: workflow HTTP error")
        if any(r["summary"].get("status") == "failed" for r in run_results):
            failures.append(f"{scenario['id']}: workflow run failed")
        results.append(result)

    print(json.dumps({"scenarios": results, "failures": failures}, ensure_ascii=False, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
