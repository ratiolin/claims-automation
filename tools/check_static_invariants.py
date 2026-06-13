#!/usr/bin/env python3
"""静态不变量检查：对主工作流 YAML + 仓库做结构性断言（无需运行 Dify）。

把原本靠文档/人工核查的不变量工具化：
  INV-8  候选知识库隔离：无 knowledge-retrieval 节点引用候选库 ID（只引用正式库/案例库）。
  INV-5  HTTP 软失败全覆盖：所有 http-request 节点 error_strategy == default-value。
  INV-2  LLM 不直接落库：副作用 HTTP 节点（payment/state-machine/fast-lane/decision-log）的直接图前驱不是 llm 节点。
  INV-4  claim_id 派生一致：generate_claim_id 节点与 tools/run_checks.py 同用 sha256(f"{order_id}_{user_id}") + hexdigest()[:16]。
  INV-14 决策枚举封闭：safety_guard 代码含 ("approve","reject","manual_review")；SQL 注释为 approve / manual_review / reject。
  INV-6  降级默认偏保守：biz_stats=yellow/0.5、static_risk=unknown、vision=vision_failed。
  INV-9  候选→正式门：error-pattern-mining 含 min_occurrence 噪声过滤 + pending_review。
  INV-11 文案护栏词表：validate_copy_* 含绝对化词检查 + manual_review 兜底。

用法: python3 tools/check_static_invariants.py [--workflow <yml>]
退出码 0=全过，1=有不变量被破坏。
"""
from __future__ import annotations

import argparse
import os
import sys

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WF_DIR = os.path.join(ROOT, "dify-workflows")
CANDIDATE_KB = "84595bdf"   # 候选错误模式库（不得进入主检索）
FORMAL_KB = "11c2953a"      # 正式错误模式库
CASES_KB = "9114aeda"       # 相似案例库
SIDE_EFFECT_URLS = (
    "/mock/payment/", "/mock/state-machine/complete", "/mock/state-machine/create",
    "/mock/decision-log/insert", "/mock/fast-lane/try-increment", "/mock/fast-lane/release",
)


def default_workflow() -> str:
    p = os.path.join(WF_DIR, "claims-main-workflow-stage6.1-inv3.yml")
    if os.path.exists(p):
        return p
    raise SystemExit("primary workflow claims-main-workflow-stage6.1-inv3.yml not found")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workflow", default=default_workflow())
    a = ap.parse_args()
    print(f"workflow: {os.path.basename(a.workflow)}\n")

    d = yaml.safe_load(open(a.workflow, encoding="utf-8"))
    g = d["workflow"]["graph"]
    nodes = {n["id"]: n for n in g["nodes"]}
    edges = g["edges"]
    checks: list[tuple[str, bool, str]] = []

    def ck(name, ok, detail=""):
        checks.append((name, bool(ok), detail))

    # INV-8 候选库隔离
    used = set()
    for n in g["nodes"]:
        if n["data"].get("type") == "knowledge-retrieval":
            used.update(n["data"].get("dataset_ids", []))
    cand = any(CANDIDATE_KB in did for did in used)
    ck("INV-8 候选库隔离", not cand, f"检索库={sorted(used)} 含候选库={cand}")

    # INV-5 HTTP 默认值全覆盖
    https = [n for n in g["nodes"] if n["data"].get("type") == "http-request"]
    missing = [n["id"] for n in https if n["data"].get("error_strategy") != "default-value"]
    ck(f"INV-5 HTTP默认值（{len(https)}个）", not missing, f"缺default-value={missing}")

    # INV-2 LLM 不直连副作用 HTTP
    bad = []
    for n in https:
        url = n["data"].get("url", "")
        if any(se in url for se in SIDE_EFFECT_URLS):
            for e in edges:
                if e["target"] == n["id"]:
                    pre = nodes.get(e["source"], {})
                    if pre.get("data", {}).get("type") == "llm":
                        bad.append((e["source"], n["id"]))
    ck("INV-2 LLM不直连副作用", not bad, f"违规边={bad}")

    # INV-4 claim_id 派生一致
    gen = nodes.get("generate_claim_id", {}).get("data", {}).get("code", "")
    try:
        run = open(os.path.join(ROOT, "tools", "run_checks.py"), encoding="utf-8").read()
    except FileNotFoundError:
        run = ""
    sig = 'sha256(f"{order_id}_{user_id}"'
    tail = "hexdigest()[:16]"
    ck("INV-4 claim_id派生一致",
       sig in gen and tail in gen and sig in run and tail in run,
       f"workflow={sig in gen and tail in gen} run_checks={sig in run and tail in run}")

    # INV-14 决策枚举封闭
    enum_code = any(
        all(t in nodes.get(nid, {}).get("data", {}).get("code", "")
            for t in ('"approve"', '"reject"', '"manual_review"'))
        for nid in ("safety_guard_fast_lane", "safety_guard_healthy", "safety_guard_degraded")
    )
    try:
        sql = open(os.path.join(ROOT, "sql", "init_decision_log.sql"), encoding="utf-8").read()
    except FileNotFoundError:
        sql = ""
    sql_ok = "approve / manual_review / reject" in sql
    ck("INV-14 决策枚举封闭", enum_code and sql_ok, f"code={enum_code} sql={sql_ok}")

    # INV-6 降级默认偏保守（biz_stats=yellow/0.5、static_risk=unknown、vision=vision_failed）
    def _dft_body(nid):
        for kv in nodes.get(nid, {}).get("data", {}).get("default_value", []):
            if kv.get("key") == "body":
                return kv.get("value", "")
        return ""
    inv6 = ('"signal_light":"yellow"' in _dft_body("http_biz_stats")
            and '"degradation_index":0.5' in _dft_body("http_biz_stats")
            and '"static_risk":"unknown"' in _dft_body("http_static_risk")
            and '"source":"vision_failed"' in _dft_body("http_vision_classify"))
    ck("INV-6 降级默认偏保守", inv6,
       f'biz={_dft_body("http_biz_stats")[:30]} risk={_dft_body("http_static_risk")[:28]} vis={_dft_body("http_vision_classify")[:30]}')

    # INV-9 候选→正式门（min_occurrence 噪声过滤 + pending_review）
    mining_path = os.path.join(WF_DIR, "error-pattern-mining-1.13.3.yml")
    mining_ok, detail9 = False, "error-pattern-mining-1.13.3.yml 缺失"
    if os.path.exists(mining_path):
        md = yaml.safe_load(open(mining_path, encoding="utf-8"))
        codes = " ".join(n["data"].get("code", "") for n in md["workflow"]["graph"]["nodes"]
                         if n["data"].get("type") == "code")
        mining_ok = "< min_count" in codes and "pending_review" in codes
        detail9 = f'min_count过滤={"< min_count" in codes} pending_review={"pending_review" in codes}'
    ck("INV-9 候选→正式门", mining_ok, detail9)

    # INV-11 文案护栏词表（validate_copy_* 含绝对化词检查 + manual_review 兜底）
    inv11 = all(
        "保证" in nodes.get(f"validate_copy_{s}", {}).get("data", {}).get("code", "")
        and "manual_review" in nodes.get(f"validate_copy_{s}", {}).get("data", {}).get("code", "")
        for s in ("fast_lane", "healthy", "degraded"))
    ck("INV-11 文案护栏词表", inv11, "validate_copy_* 缺绝对化词表或 manual_review 兜底")

    fails = 0
    for name, ok, detail in checks:
        print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"   {detail}" if not ok else ""))
        fails += not ok
    print(f"\n=== {len(checks) - fails}/{len(checks)} passed ===")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
