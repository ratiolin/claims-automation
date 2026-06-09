#!/usr/bin/env python3
"""Phase 4 closed-loop checks for copy quality and error-pattern mining workflows."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
import urllib.error
from typing import Any


def request_json(method: str, url: str, *, body: dict[str, Any] | None = None, headers: dict[str, str] | None = None, timeout: int = 120):
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    final_headers = {"Content-Type": "application/json"}
    if headers:
        final_headers.update(headers)
    req = urllib.request.Request(url, data=data, headers=final_headers, method=method.upper())
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return resp.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(raw)
        except Exception:
            parsed = {"error": raw}
        return exc.code, parsed


def run_workflow(dify_base: str, api_key: str, inputs: dict[str, Any], user: str):
    headers = {"Authorization": f"Bearer {api_key}"}
    body = {"inputs": inputs, "response_mode": "blocking", "user": user}
    return request_json("POST", dify_base.rstrip("/") + "/v1/workflows/run", body=body, headers=headers, timeout=180)


def seed_logs(mock_base: str):
    request_json("POST", mock_base.rstrip() + "/mock/reset-all")
    rows = [
        {
            "claim_id": "mine-001",
            "order_id": "10011",
            "user_id": "U009",
            "decision": "manual_review",
            "final_amount": 0,
            "user_message": "进入人工复核",
            "review_reason": "物流截图缺少最终状态，无法自动确认责任",
            "fast_lane": False,
            "material_source": "filename_guess",
            "is_shadow_mode": True,
            "human_override": True,
            "human_decision": "approve",
        },
        {
            "claim_id": "mine-002",
            "order_id": "10012",
            "user_id": "U010",
            "decision": "manual_review",
            "final_amount": 0,
            "user_message": "进入人工复核",
            "review_reason": "物流截图缺少最终状态，无法自动确认责任",
            "fast_lane": False,
            "material_source": "filename_guess",
            "is_shadow_mode": True,
            "human_override": True,
            "human_decision": "approve",
        },
        {
            "claim_id": "mine-noise",
            "order_id": "10013",
            "user_id": "U011",
            "decision": "reject",
            "final_amount": 0,
            "user_message": "暂不支持",
            "review_reason": "单次噪声样本",
            "fast_lane": False,
            "material_source": "vision_model",
            "is_shadow_mode": True,
            "complaint": True,
        },
    ]
    for row in rows:
        status, payload = request_json("POST", mock_base.rstrip() + "/mock/decision-log/insert", body=row)
        if status >= 400:
            raise RuntimeError(f"seed log failed: HTTP {status} {payload}")


def workflow_outputs(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    return data.get("outputs") if isinstance(data.get("outputs"), dict) else {}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dify-base", default=os.getenv("DIFY_BASE", "https://dify.metratio.com"))
    parser.add_argument("--mock-base", default=os.getenv("MOCK_BASE", "http://localhost:8080"))
    parser.add_argument("--quality-key", default=os.getenv("DIFY_COPY_QUALITY_API_KEY", ""))
    parser.add_argument("--mining-key", default=os.getenv("DIFY_ERROR_MINING_API_KEY", ""))
    args = parser.parse_args()

    if not args.quality_key or not args.mining_key:
        print("DIFY_COPY_QUALITY_API_KEY and DIFY_ERROR_MINING_API_KEY are required", file=sys.stderr)
        return 2

    failures: list[str] = []

    good_status, good_payload = run_workflow(
        args.dify_base,
        args.quality_key,
        {
            "claim_id": "phase4-good-copy",
            "user_message": "您好，您的理赔申请已进入人工复核，我们会结合订单、物流和材料信息进一步确认处理结果。",
            "decision": "manual_review",
            "payout_amount": 0,
            "review_reason": "材料需要人工核实",
        },
        "codex-phase4-good",
    )
    good_outputs = workflow_outputs(good_payload)
    if good_status >= 400 or good_outputs.get("quality_status") != "passed":
        failures.append(f"good copy quality check failed: HTTP {good_status}, outputs={good_outputs}")

    bad_status, bad_payload = run_workflow(
        args.dify_base,
        args.quality_key,
        {
            "claim_id": "phase4-bad-copy",
            "user_message": "保证马上赔付",
            "decision": "approve",
            "payout_amount": 0,
            "review_reason": "测试坏文案",
        },
        "codex-phase4-bad",
    )
    bad_outputs = workflow_outputs(bad_payload)
    if bad_status >= 400 or bad_outputs.get("quality_status") != "candidate_generated":
        failures.append(f"bad copy candidate check failed: HTTP {bad_status}, outputs={bad_outputs}")

    seed_logs(args.mock_base)
    mining_status, mining_payload = run_workflow(
        args.dify_base,
        args.mining_key,
        {"days": 7, "min_occurrence": 2},
        "codex-phase4-mining",
    )
    mining_outputs = workflow_outputs(mining_payload)
    try:
        patterns = json.loads(mining_outputs.get("patterns_json") or "[]")
    except Exception:
        patterns = []
    if mining_status >= 400 or int(mining_outputs.get("pattern_count") or 0) < 1:
        failures.append(f"mining check failed: HTTP {mining_status}, outputs={mining_outputs}")
    if patterns and not {"mine-001", "mine-002"}.issubset(set(patterns[0].get("sample_claim_ids") or [])):
        failures.append(f"mining sample ids mismatch: {patterns}")

    result = {
        "good_copy": good_outputs,
        "bad_copy": bad_outputs,
        "mining": mining_outputs,
        "failures": failures,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
