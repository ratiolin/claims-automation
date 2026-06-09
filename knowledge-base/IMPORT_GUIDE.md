# 知识库初始化指南 — Dify 1.13.3

## 前置条件
- Dify 已部署运行，可访问控制台
- 已配置 Embedding 模型（系统设置 → 模型供应商）

---

## Step 1: 创建三个知识库

Dify 控制台 → 知识库 → 创建知识库：

| 知识库名称 | 类型 | 建议索引方式 |
|-----------|------|------------|
| 错误模式库（正式） | 高质量 | 高质量索引 |
| 错误模式库（候选） | 高质量 | 高质量索引 |
| 相似案例库 | 高质量 | 高质量索引 |

---

## Step 2: 上传文档并设置 metadata

### 2.1 错误模式库（正式）

上传 `knowledge-base/error-patterns-official/` 下的 5 份文档。

**关键步骤**：每份文档上传时/上传后，在文档详情中设置 **元数据(metadata)**：

| 文档 | metadata.priority | metadata.severity | metadata.category |
|------|-------------------|-------------------|-------------------|
| ERR-001 | **90** (number) | high | 物流判定 |
| ERR-002 | **70** (number) | high | 对话分析 |
| ERR-003 | **50** (number) | medium | 用户行为 |
| ERR-004 | **60** (number) | medium | 品类判定 |
| ERR-005 | **80** (number) | high | 证据判定 |

**metadata 字段类型**：
- `priority`: **数字(Number)** — 这是数值过滤的关键
- `severity`: 字符串
- `category`: 字符串

**验证**：在 Dify 知识库界面，打开任意文档 → 元数据 → 确认 `priority` 字段类型为"数字"（不是"字符串"）。数值过滤仅在 Number 类型上生效。

### 2.2 错误模式库（候选）

上传 `knowledge-base/error-patterns-candidate/` 下的 1 份文档。

| 文档 | metadata.priority | metadata.status |
|------|-------------------|-----------------|
| ERR-CANDIDATE-001 | 15 (number) | pending_review |

### 2.3 相似案例库

上传 `knowledge-base/similar-cases/` 下的 3 份文档。

每份文档设置 metadata：

| 文档 | metadata.case_type | metadata.logistics_type | metadata.amount_range | metadata.category |
|------|-------------------|------------------------|----------------------|-------------------|
| CASE-001 | positive | 超时未更新 | small | 日用品 |
| CASE-002 | negative | 其他 | small | 电子产品 |
| CASE-003 | correction | 错分 | medium | 家电配件 |

---

## Step 3: 验证检索

在知识库界面使用测试检索功能：

1. 查询文本：`物流超时未更新 日用品 小额`
2. 期望：CASE-001 命中（相似案例），ERR-001 命中（错误模式）

---

## 注意

### metadata.priority 数值过滤验证方法

在后续 3.3（知识检索节点）配置完成后，可以通过以下方式验证：

- 健康分支（priority >= 60）：期望返回 ERR-001(90), ERR-002(70), ERR-004(60), ERR-005(80)
- 劣化分支（priority >= 30）：期望返回以上 + ERR-003(50)

如果发现过滤不生效，检查：
1. metadata 中 `priority` 字段类型是否为 **Number**（不是 String）
2. 知识检索节点的 Metadata Filter 中比较运算符是否选 `≥`
3. 知识库是否已完成索引（状态为"已就绪"）
