# ERR-005 材料不足时 confidence 未降级

## Metadata

- priority: 80
- severity: high
- category: 证据判定
- source: complaint_feedback
- created_at: 2024-02-15

## Content

## 错误模式：关键材料缺失时仍输出 confidence=medium/high

### 详细描述
当订单截图或物流截图缺失时，系统应该输出 confidence=low 并转人工。
但实际运行中偶尔出现 confidence=medium，导致自动审批通过。

### 正确做法
1. 在 signal_quality 中检查 missing_hard_evidence
2. 关键证据缺失时，LLM 输出必须为 confidence=low
3. 合议中心代码级强制覆盖：all_critical_failed → confidence=low → dyn_th=0.0 → manual_review

### 避免指示
- 不要在有缺失证据时输出 confidence=medium 或 high
- 不要依赖 LLM 自觉降级——必须在代码层做二次校验
- 不要把"N/A"当作有效数据
