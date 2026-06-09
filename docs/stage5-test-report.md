# Stage 5 全链路测试报告

测试时间：2026-06-09

## 结论

Stage 5 v2 全链路测试通过。8 个测试场景均完成工作流调用，并成功回查到状态机、支付或跳过支付、决策日志结果。

## 测试范围

- 快速通道自动通过
- 中金额转人工
- 高风险用户转人工
- 大金额转人工
- 材料缺失转人工
- 外部依赖失败降级
- 重复提交拦截
- 劣化模式检索分支

## 场景结果

| 场景 | 结果 | 决策 | 分支 | 状态机 | 支付 | 决策日志 |
|---|---|---|---|---|---|---|
| S01_fast_lane | 通过 | approve | fast_lane | completed | success | inserted |
| S02_medium_manual | 通过 | manual_review | healthy | completed | skipped | inserted |
| S03_high_risk_user | 通过 | manual_review | healthy | completed | skipped | inserted |
| S04_large_amount | 通过 | manual_review | healthy | completed | skipped | inserted |
| S05_missing_materials | 通过 | manual_review | healthy | completed | skipped | inserted |
| S06_dependency_degraded | 通过 | manual_review | healthy | completed | skipped | inserted |
| S07_duplicate_submission | 通过 | approve / duplicate | fast_lane / early end | completed | success once | inserted once |
| S08_degraded_band | 通过 | manual_review | degraded | completed | skipped | inserted |

## 关键修复

- Stage 5 fixed：修复 `用户ID: U001` 被提取为 `D` 的正则问题。
- Stage 5 v2：补齐 21 个 HTTP 节点的 `error_strategy: default-value`，确保 503 等外部依赖失败进入降级路径，而不是中断工作流。

## 说明

S06 的 Dify workflow status 为 `partial-succeeded`，这是预期行为：外部 HTTP 节点发生 503，但已由默认值兜底，业务流程最终完成转人工、状态迁移和日志写入。
