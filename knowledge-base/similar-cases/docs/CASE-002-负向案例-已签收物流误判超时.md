# CASE-002 负向案例：已签收物流误判超时

## Metadata

- case_type: negative
- logistics_type: 其他
- amount_range: small
- category: 电子产品
- risk_level: high
- decision: reject
- was_overridden: True
- created_at: 2024-01-15

## Content

## 案例摘要

### 基本信息
- 订单金额: 65元
- 商品品类: 电子产品
- 物流异常类型: 其他（用户声称未收到）
- 用户历史: 近30天退款率70%

### 裁决过程
- 定责定损助手: claim_valid=true, confidence=medium, suggested_amount=65元
  （错误：仅根据用户描述判定，未仔细核查物流最终状态）
- 用户信用助手: risk_level=low（错误：未识别高频退款模式）
- 合议中心: 自动批准65元

### 推翻原因
人工审核发现物流轨迹显示1月14日已签收（签收人姓名字段非空），
用户实际已收货。高频退款行为辅助确认了恶意索赔倾向。

### 纠正措施
- 将"物流已签收但用户声称未收到"模式加入错误提醒
- 增强用户信用助手对退款率的敏感度

### 最终结果
人工推翻，改为拒绝。
