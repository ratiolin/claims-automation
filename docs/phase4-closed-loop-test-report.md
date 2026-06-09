# 阶段四闭环测试报告

测试时间：2026-06-09

## 结论

阶段四闭环链路已验证通过：

- 文案质量评估工作流可通过 Dify Workflow API 调用。
- 好文案返回 `passed`。
- 坏文案返回 `candidate_generated`，并输出候选错误模式 JSON。
- 错误模式自动挖掘工作流可从决策日志中聚合重复问题。
- 噪声过滤 `min_occurrence=2` 生效。
- 自动挖掘结果已写入错误模式候选知识库，并设置 metadata。

## 文案质量评估

工作流 API Key：已验证可用。

测试结果：

| 用例 | 输入特征 | 结果 |
|---|---|---|
| 好文案 | 人工复核说明完整、无绝对承诺 | `passed` |
| 坏文案 | “保证马上赔付”、approve 但金额为 0 | `candidate_generated` |

坏文案输出问题：

- `too_short`
- `risky_absolute_terms`
- `approve_without_amount`

## 错误模式自动挖掘

种子日志：

- `mine-001`：物流截图缺少最终状态，无法自动确认责任
- `mine-002`：物流截图缺少最终状态，无法自动确认责任
- `mine-noise`：单次噪声样本

挖掘结果：

- `record_count`: 3
- `pattern_count`: 1
- 候选模式：`manual_review / filename_guess 高频问题`
- 样本：`mine-001`, `mine-002`
- 单次噪声样本已过滤

## 候选知识库写入

候选知识库：

- 名称：错误模式库（候选）
- ID：`84595bdf-aa20-4cd8-9a56-0fead9284e1a`

写入文档：

- 名称：`ERR-CANDIDATE-PHASE4-001.md`
- 文档 ID：`3a42925d-e59d-4070-a0fd-80432b7cba6d`
- 索引状态：`completed`
- 显示状态：`available`

metadata：

| 字段 | 值 |
|---|---|
| priority | 15 |
| severity | medium |
| category | 自动挖掘 |
| status | pending_review |
| occurrence_count | 2 |

## 可复测脚本

阶段四闭环测试：

```bash
cd ~/claims-automation
DIFY_COPY_QUALITY_API_KEY='...' \
DIFY_ERROR_MINING_API_KEY='...' \
python3 tools/run_phase4_checks.py --mock-base http://localhost:8080
```

候选模式写入知识库：

```bash
cd ~/claims-automation
DIFY_DATASET_API_KEY='...' \
python3 tools/write_candidate_pattern_to_kb.py \
  --name ERR-CANDIDATE-PHASE4-001.md \
  --pattern-json '[{"title":"manual_review filename_guess","category":"auto","priority":15,"status":"pending_review","occurrence_count":2,"description":"desc","mitigation":"mit","sample_claim_ids":["mine-001","mine-002"]}]'
```

同名文档已存在时脚本会返回 `skipped_existing`，避免重复写入。
