# CASE-003 纠偏案例：高估损失后修正金额

## Metadata

- case_type: correction
- logistics_type: 错分
- amount_range: medium
- category: 家电配件
- risk_level: low
- decision: auto_approve
- amount_deviation: 400%
- corrected_amount: 40
- original_amount: 200
- created_at: 2024-01-25

## Content

## 案例摘要

### 基本信息
- 订单金额: 200元
- 商品品类: 家电配件
- 物流异常类型: 错分（延误3天）
- 用户历史: 正常，12月理赔1次

### 初次裁决
- 定责定损助手: claim_valid=true, confidence=high, suggested_amount=200元
  （错误：按订单全额建议赔付，未考虑实际损失仅为延误）
- 用户信用助手: risk_level=low
- 合议中心: 自动批准200元

### 人工审核发现
错分仅导致3天延误，商品最终正常送达。实际损失远小于订单金额。
根据政策：错分延误3天，赔付标准为订单金额20%，即40元。

### 纠正措施
- 修正金额为40元
- 金额偏差: (200-40)/40 = 400%，远超30%纠偏阈值
- 将此案例补充入相似案例库，提示"错分延误需按时间比例赔付"

### 最终结果
人工修正金额为40元，已赔付。
