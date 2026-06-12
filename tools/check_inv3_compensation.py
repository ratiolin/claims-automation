#!/usr/bin/env python3
"""INV-3 跨服务补偿缺口：对当前已发布工作流演示缺口 + 验证 Mock 补偿原语。

缺口：快速通道理赔在 try-increment 消耗名额后，若 payment 失败，工作流仍把状态机
CAS 为 completed，且不释放已消耗的快速通道名额 —— 钱没扣却显示「完成」，名额白白浪费。

本脚本：
  1) 注入支付失败（/mock/payment/set-fail on）
  2) 对当前工作流跑一个快速通道理赔
  3) 观测：payment 失败? 名额是否被消耗? 状态机是否 completed? -> 判定缺口
  4) 验证 /mock/fast-lane/release 补偿原语可释放名额

用法: DIFY_MAIN_WORKFLOW_API_KEY=... python3 tools/check_inv3_compensation.py \
        [--mock-base http://localhost:8080] [--dify-base http://localhost:18080]
导入 stage6 修复后复跑：状态应为 failed（非 completed）且名额由工作流自动释放，缺口消失。
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
    ap.add_argument("--timeout", type=int, default=240)
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

    print("== 1) reset + 注入支付失败 ==")
    jpost(mb, "/mock/reset-all")
    jpost(mb, "/mock/payment/set-fail", {"on": True})

    print("== 2) 对当前工作流跑一个快速通道理赔（支付将失败）==")
    status, payload, _ = m.run_workflow(a.dify_base, a.main_key, scenario, user_prefix="inv3", timeout=a.timeout)
    s = m.summarize_workflow_result(payload)
    print(f"   run_status={s.get('status')} branch={s.get('branch')} decision={s.get('decision')}")
    print(f"   payment_body={s.get('payment_body')}")
    print(f"   state_body={s.get('state_body')}")

    print("== 3) 观测副作用一致性 ==")
    _, fc = jget(mb, f"/mock/fast-lane/count?user_id={user_id}")
    _, st = jget(mb, f"/mock/state-machine/status?claim_id={cid}")
    pay_failed = "payment_failed" in (s.get("payment_body") or "")
    slot_used = fc.get("count", 0)
    state_status = st.get("status")
    print(f"   支付失败? {pay_failed} | 快速通道已消耗名额={slot_used} | 状态机={state_status}")
    gap = pay_failed and slot_used >= 1 and state_status == "completed"
    print(f"   >> INV-3 缺口存在? {gap}  （支付失败但名额被消耗且状态=completed → 钱没扣却显示完成）")

    print("== 4) 验证 Mock 补偿原语 /fast-lane/release ==")
    _, rel = jpost(mb, "/mock/fast-lane/release", {"user_id": user_id, "claim_id": cid, "release": True})
    _, fc2 = jget(mb, f"/mock/fast-lane/count?user_id={user_id}")
    print(f"   release -> {rel} | 释放后名额={fc2.get('count')}")
    comp_ok = rel.get("released") is True and fc2.get("count", 99) == slot_used - 1

    jpost(mb, "/mock/payment/set-fail", {"on": False})
    jpost(mb, "/mock/reset-all")

    print(f"\n=== 结论：v2 缺口复现={gap}；补偿原语可用={comp_ok} ===")
    if gap and comp_ok:
        print("修复（stage6）：工作流在 payment 后加 settle 节点——支付失败则状态置 failed、")
        print("降级 manual_review、并调用 /fast-lane/release 释放名额。导入 stage6 后复跑本脚本，")
        print("应得：状态≠completed 且名额已自动释放，缺口消失。")
    return 0 if (gap and comp_ok) else 1


if __name__ == "__main__":
    raise SystemExit(main())
