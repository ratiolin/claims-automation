# ERR-CANDIDATE-001 文案金额表述不一致

## Metadata

- priority: 15
- severity: low
- category: 文案质量
- source: copy_quality_assessment
- status: pending_review
- occurrence_count: 3
- created_at: 2024-02-20

## Content

## 候选错误模式：文案中金额与裁决金额不一致

### 详细描述
系统自动生成的用户文案中，赔付金额表述与合议中心裁决金额偶尔存在偏差。
例如裁决 30 元但文案写"赔付 35 元"，或文案使用了模糊表述"约 30 元"。

### 出现次数
近期3次（待确认是否达阈值）

### 正确做法
1. 文案生成时严格使用 final_amount 精确值
2. 文案校验环节增加金额匹配检查
3. 不允许使用"约""大概"等模糊表述

### 避免指示
- 不要在文案中四舍五入金额
- 不要让 LLM 自行计算金额

### 状态
待人工审核。若确认为有效模式，迁移至正式错误模式库并设置 priority=55。
