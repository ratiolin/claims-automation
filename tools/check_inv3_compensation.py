#!/usr/bin/env python3
"""INV-3 跨服务补偿验证（对当前已发布的主工作流）。

注入支付失败后跑一个快速通道理赔，观测状态机与快速通道名额，自动判定：
  - 未修复（v2）：state=completed 且名额被消耗 -> 缺口存在（钱没扣却显示完成），
                  并验证 Mock 补偿原语 /mock/fast-lane/release 可释放名额。
  - 已修复（stage6）：state=failed 且名额=0 -> settle 置 failed + 转人工 + release 自动释放名额。

用法: DIFY_MAIN_WORKFLOW_API_KEY=<主工作流key> python3 tools/check_inv3_compensation.py \
        [--mock-base http://localhost:8080] [--dify-base http://localhost:18080]
退出码 0 表示得到一个干净判定（缺口存在 或 已修复）；1 表示判定不清（如 transient）。
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import run_stage5_checks as m  # noqa: E402


def jget(base, path):
    return m.request_json("GET", base.rstrip("/") + path)


def jpost(base, path, body=None):
    return m.request_json("POST", base.rstrip("/") + path, body=body)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mock-base", default=os.getenv("MOCK_BASE", "http://localhost:8080"))
    ap.add_argument("--dify-base", default=os.getenv("DIFY_BASE", "http://localhost:18080"))
    ap.add_argument("--main-key", default=os.getenv("DIFY_MAIN_WORKFLOW_API_KEY", ""))
    ap.add_argument("--timeout", type=int, default=300)
    ap.add_argument("--max-attempts", type=int, default=3)
    a = ap.parse_args()
    if not a.main_key:
        print("DIFY_MAIN_WORKFLOW_API_KEY required", file=sys.stderr)
        return 2

    mb = a.mock_base
    user_id, order_id = "U003", "10008"
    scenario = {"id": "INV3", "input": {
        "user_text": f"订单号{order_id}，用户ID: {user_id}，物流一直没有更新，申请理赔",
        "file_list": [{"name": f"订单截图_{order_id}.png"}, {"name": "物流异常截图.png"}]}}
    cid = m.claim_id_for(order_id, user_id)

    def arm():
        jpost(mb, "/mock/reset-all")
        jpost(mb, "/mock/payment/set-fail", {"on": True})

    print("== 注入支付失败，对当前主工作流跑一个快速通道理赔 ==")
    s = {}
    for attempt in range(1, a.max_attempts + 1):
        arm()
        status, payload, el = m.run_workflow(a.dify_base, a.main_key, scenario, user_prefix="inv3", timeout=a.timeout)
        s = m.summarize_workflow_result(payload)
        if status == 200 and s.get("status") == "succeeded":
            print(f"   ok (attempt {attempt}, {round(el, 1)}s)")
            break
        print(f"   attempt {attempt}: http={status} run={s.get('status')} — retry")
    else:
        print("ABORT: transient 未能在重试内稳定")
        jpost(mb, "/mock/payment/set-fail", {"on": False})
        return 1

    print(f"   run_status={s.get('status')} branch={s.get('branch')} decision={s.get('decision')}")
    print(f"   payment_body={s.get('payment_body')}")
    print(f"   state_body={s.get('state_body')}")

    _, fc = jget(mb, f"/mock/fast-lane/count?user_id={user_id}")
    _, st = jget(mb, f"/mock/state-machine/status?claim_id={cid}")
    _, logs = jget(mb, "/mock/decision-log/query?days=7")
    log = [l for l in logs.get("results", []) if l.get("claim_id") == cid]
    pay_failed = "payment_failed" in (s.get("payment_body") or "")
    slot = fc.get("count", 0)
    state = st.get("status")
    log_decision = log[-1].get("decision") if log else None
    print(f"   支付失败? {pay_failed} | 快速通道名额={slot} | 状态机={state} | 日志决策={log_decision}")

    gap = pay_failed and slot >= 1 and state == "completed"
    fixed = pay_failed and state == "failed" and slot == 0 and log_decision == "manual_review"

    rc = 1
    if fixed:
        print("\n=== 判定：已修复（stage6）===")
        print("  支付失败 -> 状态机=failed（非completed）+ 名额自动释放为 0 + 决策降级 manual_review。INV-3 缺口已关闭。")
        rc = 0
    elif gap:
        print("\n=== 判定：缺口存在（未修复 / v2）===")
        print("  支付失败但状态=completed 且名额被消耗 -> 钱没扣却显示完成。")
        _, rel = jpost(mb, "/mock/fast-lane/release", {"user_id": user_id, "claim_id": cid, "release": True})
        _, fc2 = jget(mb, f"/mock/fast-lane/count?user_id={user_id}")
        print(f"  补偿原语 /fast-lane/release -> {rel} | 释放后名额={fc2.get('count')}")
        rc = 0 if rel.get("released") and fc2.get("count") == slot - 1 else 1
    else:
        print("\n=== 判定：不清楚（payment_failed/state 非预期组合，可能 transient 或工作流异常）===")

    jpost(mb, "/mock/payment/set-fail", {"on": False})
    jpost(mb, "/mock/reset-all")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
