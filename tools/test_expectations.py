#!/usr/bin/env python3
"""Offline unit tests for the Stage 5 assertion layer in run_stage5_checks.py.

These run WITHOUT Dify or the Mock: they feed synthetic workflow summaries to the
pure helper functions (summarize_workflow_result, _result_of, check_expectations,
is_transient) and verify the assertions catch the failures they are meant to catch.

Run:  python3 tools/test_expectations.py   ->  exit 0 if all pass, 1 otherwise.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import run_stage5_checks as m  # noqa: E402

_passed = 0
_failed = 0


def expect(name: str, got, want) -> None:
    global _passed, _failed
    ok = got == want
    print(("PASS" if ok else "FAIL"), name, "" if ok else f"\n   got={got!r}\n   want={want!r}")
    _passed += ok
    _failed += (not ok)


def summ(status: str, outputs: dict):
    return m.summarize_workflow_result({"data": {"id": "r", "status": status, "outputs": outputs}})


def run(http_status: int, status: str, outputs: dict | None = None):
    return {"http_status": http_status, "summary": summ(status, outputs or {})}


# ── summarize captures the duplicate-path fields ─────────────────────────────
s = summ("succeeded", {"result": "duplicate", "message": "dup"})
expect("summarize.result", s.get("result"), "duplicate")
expect("summarize.message", s.get("message"), "dup")

# ── _result_of: str-JSON / dict / None ───────────────────────────────────────
expect("_result_of str", m._result_of('{"result":"success"}'), "success")
expect("_result_of dict", m._result_of({"result": "skipped"}), "skipped")
expect("_result_of none", m._result_of(None), None)

# ── check_expectations: happy paths ──────────────────────────────────────────
expect("S01 correct", m.check_expectations("S01_fast_lane",
       [run(200, "succeeded", {"branch": "fast_lane", "decision": "approve",
            "payment_body": '{"result":"success"}'})], 1), [])
expect("S03 correct", m.check_expectations("S03_high_risk_user",
       [run(200, "succeeded", {"branch": "healthy", "decision": "manual_review",
            "payment_body": '{"result":"skipped"}'})], 1), [])
expect("S06 partial-succeeded ok", m.check_expectations("S06_dependency_degraded",
       [run(200, "partial-succeeded", {"branch": "healthy", "decision": "manual_review",
            "payment_body": '{"result":"skipped"}'})], 1), [])
expect("S08 degraded ok", m.check_expectations("S08_degraded_band",
       [run(200, "succeeded", {"branch": "degraded", "decision": "manual_review",
            "payment_body": '{"result":"skipped"}'})], 1), [])

# ── check_expectations: the bugs we must catch ───────────────────────────────
iss = m.check_expectations("S01_fast_lane",
      [run(200, "succeeded", {"branch": "healthy", "decision": "approve",
           "payment_body": '{"result":"success"}'})], 1)
expect("S01 wrong-branch flagged", any("branch expected fast_lane" in x for x in iss), True)

iss = m.check_expectations("S03_high_risk_user",
      [run(200, "succeeded", {"branch": "healthy", "decision": "approve",
           "payment_body": '{"result":"success"}'})], 1)
expect("S03 silent-approve flagged (decision)", any("decision expected manual_review" in x for x in iss), True)
expect("S03 silent-approve flagged (payment)", any("payment expected skipped" in x for x in iss), True)

iss = m.check_expectations("S06_dependency_degraded",
      [run(200, "succeeded", {"branch": "healthy", "decision": "manual_review",
           "payment_body": '{"result":"skipped"}'})], 1)
expect("S06 wrong-status flagged", any("run_status expected partial-succeeded" in x for x in iss), True)

# ── S07 duplicate handling ───────────────────────────────────────────────────
s07_ok = [
    run(200, "succeeded", {"branch": "fast_lane", "decision": "approve",
        "payment_body": '{"result":"success"}'}),
    run(200, "succeeded", {"result": "duplicate", "message": "already"}),
]
expect("S07 duplicate ok", m.check_expectations("S07_duplicate_submission", s07_ok, 1), [])
expect("S07 double-log flagged",
       any("exactly 1 decision log, got 2" in x for x in
           m.check_expectations("S07_duplicate_submission", s07_ok, 2)), True)
s07_bad = [s07_ok[0], run(200, "succeeded", {"branch": "fast_lane", "decision": "approve",
           "payment_body": '{"result":"success"}'})]
expect("S07 second-not-duplicate flagged",
       any("result=duplicate" in x for x in
           m.check_expectations("S07_duplicate_submission", s07_bad, 2)), True)

# ── is_transient: infra-flake vs assertion-fail (the retry gate) ──────────────
expect("transient: status 0", m.is_transient([run(0, "")]), True)
expect("transient: HTTP 502", m.is_transient([run(502, "")]), True)
expect("transient: run failed", m.is_transient([run(200, "failed")]), True)
expect("NOT transient: succeeded", m.is_transient([run(200, "succeeded", {"branch": "healthy"})]), False)
expect("NOT transient: wrong-but-succeeded",
       m.is_transient([run(200, "succeeded", {"branch": "WRONG"})]), False)
expect("NOT transient: HTTP 400 (config)", m.is_transient([run(400, "")]), False)

print(f"\n=== {_passed} passed, {_failed} failed ===")
sys.exit(1 if _failed else 0)
