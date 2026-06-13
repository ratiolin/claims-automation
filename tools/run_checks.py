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
DEFAULT_SCENARIOS = ROOT / "test-data" / "scenario-suite.json"


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
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        # Read timeout / connection refused / DNS: surface as status 0 (transient)
        return 0, {"error": f"transport: {exc}"}


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
    timeout: int = 180,
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
    status, payload = request_json("POST", dify_base.rstrip("/") + "/v1/workflows/run", body=body, headers=headers, timeout=timeout)
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
        "result": outputs.get("result"),
        "message": outputs.get("message"),
        "raw_error": payload.get("message") or payload.get("error"),
    }


# ── Expected outcomes per scenario ───────────────────────────────────────────
# Encoded in the test script (not scenarios.json) so this change touches one file.
# branch ∈ {fast_lane, healthy, degraded}; decision ∈ {approve, manual_review, reject}.
# payment: expected /payment/execute result ("success" on approve, else "skipped").
# run_status: expected Dify run status ("succeeded"; "partial-succeeded" when a
# dependency 503 is caught by default-value). duplicate_second: S07-style re-submit.
EXPECTATIONS: dict[str, dict[str, Any]] = {
    "S01_fast_lane":            {"branch": "fast_lane", "decision": "approve",       "payment": "success", "run_status": "succeeded", "payment_result": "success", "final_state": "completed", "order_amount": 45},
    "S02_medium_manual":        {"branch": "healthy",   "decision": "manual_review", "payment": "skipped", "run_status": "succeeded", "payment_result": "skipped",  "final_state": "completed", "order_amount": 300},
    "S03_high_risk_user":       {"branch": "healthy",   "decision": "manual_review", "payment": "skipped", "run_status": "succeeded", "payment_result": "skipped",  "final_state": "completed", "order_amount": 88},
    "S04_large_amount":         {"branch": "healthy",   "decision": "manual_review", "payment": "skipped", "run_status": "succeeded", "payment_result": "skipped",  "final_state": "completed", "order_amount": 1200},
    "S05_missing_materials":    {"branch": "healthy",   "decision": "manual_review", "payment": "skipped", "run_status": "succeeded", "payment_result": "skipped",  "final_state": "completed", "order_amount": 55},
    "S06_dependency_degraded":  {"branch": "healthy",   "decision": "manual_review", "payment": "skipped", "run_status": "partial-succeeded", "payment_result": "skipped",  "final_state": "completed", "order_amount": 0},
    "S07_duplicate_submission": {"branch": "fast_lane", "decision": "approve",       "payment": "success", "run_status": "succeeded", "duplicate_second": True, "payment_result": "success", "final_state": "completed", "order_amount": 45},
    "S08_degraded_band":        {"branch": "degraded",  "decision": "manual_review", "payment": "skipped", "run_status": "succeeded", "payment_result": "skipped",  "final_state": "completed", "order_amount": 45},
}


def _result_of(body: Any) -> Any:
    """Extract the 'result' field from a Dify HTTP node body (str-JSON or dict)."""
    if isinstance(body, dict):
        return body.get("result")
    if isinstance(body, str):
        try:
            return json.loads(body).get("result")
        except Exception:
            return None
    return None


def check_expectations(scenario_id: str, run_results: list[dict[str, Any]], log_count: int) -> list[str]:
    """T1/T2/T3/T5: assert branch, decision, payment side-effect, run status and
    duplicate handling against EXPECTATIONS. Returns a list of mismatch messages."""
    exp = EXPECTATIONS.get(scenario_id)
    issues: list[str] = []
    if not exp or not run_results:
        return issues
    first = run_results[0]["summary"]

    # T5: Dify run status (partial-succeeded expected when a dependency 503s)
    want_status = exp.get("run_status", "succeeded")
    if first.get("status") != want_status:
        issues.append(f"run_status expected {want_status}, got {first.get('status')}")

    # T1: branch correctness (fast_lane / healthy / degraded)
    if first.get("branch") != exp["branch"]:
        issues.append(f"branch expected {exp['branch']}, got {first.get('branch')}")

    # decision correctness (approve / manual_review / reject)
    if first.get("decision") != exp["decision"]:
        issues.append(f"decision expected {exp['decision']}, got {first.get('decision')}")

    # T3: payment side-effect (success only on approve, otherwise skipped)
    pay = _result_of(first.get("payment_body"))
    if pay != exp["payment"]:
        issues.append(f"payment expected {exp['payment']}, got {pay}")

    # T6: decision log field assertions (payment_result, final_state, order_amount)
    # Check against the log entry written by decision_log_insert_*
    log = first.get("decision_log_body")
    log_parsed = None
    if isinstance(log, dict):
        log_parsed = log
    elif isinstance(log, str):
        try:
            import json
            log_parsed = json.loads(log)
        except Exception:
            pass
    if log_parsed:
        if exp.get("payment_result") and log_parsed.get("payment_result") != exp["payment_result"]:
            issues.append(f"log.payment_result expected {exp['payment_result']}, got {log_parsed.get('payment_result')}")
        if exp.get("final_state") and log_parsed.get("final_state") != exp["final_state"]:
            issues.append(f"log.final_state expected {exp['final_state']}, got {log_parsed.get('final_state')}")
        if exp.get("order_amount") is not None:
            want_amt = exp["order_amount"]
            got_amt = log_parsed.get("order_amount")
            if got_amt is not None and float(got_amt) != float(want_amt):
                issues.append(f"log.order_amount expected {want_amt}, got {got_amt}")

    # T2: duplicate re-submission must early-stop and leave exactly one side-effect
    if exp.get("duplicate_second"):
        if len(run_results) < 2:
            issues.append("expected 2 runs for duplicate scenario, got 1")
        else:
            second = run_results[1]["summary"]
            if second.get("result") != "duplicate":
                issues.append(f"second run expected result=duplicate, got {second.get('result')!r}")
            if second.get("decision") is not None:
                issues.append(f"second run expected no decision (duplicate path), got {second.get('decision')!r}")
        if log_count != 1:
            issues.append(f"duplicate scenario expected exactly 1 decision log, got {log_count}")

    return issues


def is_transient(run_results: list[dict[str, Any]]) -> bool:
    """A run is transient (worth retrying) if the transport failed (status 0),
    the server 5xx'd, or the Dify run itself reported status 'failed'. A wrong
    branch/decision on a *succeeded* run is NOT transient — that is a real signal."""
    for r in run_results:
        if r["http_status"] == 0 or r["http_status"] >= 500:
            return True
        if r["summary"].get("status") == "failed":
            return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenarios", type=Path, default=DEFAULT_SCENARIOS)
    parser.add_argument("--mock-base", default=os.getenv("MOCK_BASE", "http://localhost:8080"))
    parser.add_argument("--dify-base", default=os.getenv("DIFY_BASE", "https://dify.metratio.com"))
    parser.add_argument("--main-key", default=os.getenv("DIFY_MAIN_WORKFLOW_API_KEY", ""))
    parser.add_argument("--no-reset", action="store_true")
    parser.add_argument("--workflow", action="store_true", help="require Dify workflow mode; fail if no key is configured")
    parser.add_argument("--timeout", type=int, default=int(os.getenv("DIFY_RUN_TIMEOUT", "180")),
                        help="per-request timeout in seconds; raise it for DeepSeek cold-start")
    parser.add_argument("--max-attempts", type=int, default=int(os.getenv("STAGE5_MAX_ATTEMPTS", "3")),
                        help="max attempts per scenario; only transient failures are retried")
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
        order_id, user_id = extract_ids(scenario["input"]["user_text"])
        cid = claim_id_for(order_id, user_id) if order_id and user_id else ""
        runs = 2 if scenario.get("run_twice") else 1
        attempt = 0
        run_results: list[dict[str, Any]] = []
        while True:
            attempt += 1
            # reset before every attempt so a half-completed retry cannot collide
            # with its own earlier state (e.g. duplicate-detection on re-run).
            if not args.no_reset:
                reset_mock(args.mock_base)
            apply_precondition(args.mock_base, scenario)
            run_results = []
            for i in range(runs):
                status, payload, elapsed = run_workflow(
                    args.dify_base, args.main_key, scenario,
                    user_prefix="codex-stage5", timeout=args.timeout,
                )
                run_results.append(
                    {
                        "run": i + 1,
                        "http_status": status,
                        "elapsed_seconds": round(elapsed, 3),
                        "summary": summarize_workflow_result(payload),
                    }
                )
            if is_transient(run_results) and attempt < args.max_attempts:
                continue  # retry the whole scenario from a clean reset
            break
        logs = [log for log in get_decision_logs(args.mock_base) if log.get("claim_id") == cid]
        state = get_state(args.mock_base, cid) if cid else {}
        result = {
            "id": scenario["id"],
            "name": scenario["name"],
            "claim_id": cid,
            "attempts": attempt,
            "runs": run_results,
            "state": state,
            "log_count_for_claim": len(logs),
            "latest_log": logs[-1] if logs else None,
        }
        if scenario.get("expected", {}).get("must_have_log") and not logs:
            result["failure"] = "expected decision log entry, got none"
            failures.append(f"{scenario['id']}: missing decision log")
        if any(400 <= r["http_status"] < 500 for r in run_results):
            failures.append(f"{scenario['id']}: workflow HTTP error {[r['http_status'] for r in run_results]}")
        if is_transient(run_results):
            failures.append(f"{scenario['id']}: transient failure persisted after {attempt} attempt(s)")
        exp_issues = check_expectations(scenario["id"], run_results, len(logs))
        if exp_issues:
            result["expectation_failures"] = exp_issues
            failures.extend(f"{scenario['id']}: {m}" for m in exp_issues)
        results.append(result)

    print(json.dumps({"scenarios": results, "failures": failures}, ensure_ascii=False, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
