-- ============================================================================
-- Claims Automation — 决策日志表
-- 在 claims_log 数据库中执行
-- ============================================================================

-- 如果复用 dify-db，在 dify-db 容器内创建：
--   docker exec -it dify-db-1 psql -U postgres -c "CREATE DATABASE claims_log;"
-- 然后连接 claims_log 执行本脚本。

CREATE TABLE IF NOT EXISTS decision_log (
    id              BIGSERIAL PRIMARY KEY,
    claim_id        VARCHAR(16) NOT NULL,
    order_id        VARCHAR(32),
    user_id         VARCHAR(32),
    created_at      TIMESTAMPTZ DEFAULT NOW(),

    -- 定责定损助手输出
    claim_valid     BOOLEAN,
    claim_reason    TEXT,
    suggested_amount NUMERIC(10,2),
    confidence      VARCHAR(10),          -- high / medium / low
    risk_level      VARCHAR(10),          -- low / medium / high
    risk_reason     TEXT,

    -- 合议中心决策
    decision        VARCHAR(20),          -- auto_approve / manual_review / reject
    final_amount    NUMERIC(10,2),
    dynamic_threshold NUMERIC(10,2),

    -- 阈值参数快照
    k_factor        NUMERIC(5,2),
    degradation_index   NUMERIC(5,4),
    queue_pressure  NUMERIC(5,4),
    threshold_details   JSONB,

    -- 文案
    user_message    TEXT,
    review_reason   TEXT,
    copy_quality_score  NUMERIC(3,2),

    -- 标记
    fast_lane       BOOLEAN DEFAULT FALSE,
    material_source VARCHAR(20),          -- vision_model / filename_guess / none
    is_shadow_mode  BOOLEAN DEFAULT TRUE,

    -- 人工反馈
    human_override  BOOLEAN DEFAULT FALSE,
    human_decision  VARCHAR(20),
    complaint       BOOLEAN DEFAULT FALSE,

    -- 原始输出（供分析）
    raw_claim_result JSONB,
    raw_risk_result  JSONB,
    evidence_package TEXT
);

-- 索引
CREATE INDEX IF NOT EXISTS idx_decision_log_claim_id   ON decision_log(claim_id);
CREATE INDEX IF NOT EXISTS idx_decision_log_created_at  ON decision_log(created_at);
CREATE INDEX IF NOT EXISTS idx_decision_log_decision    ON decision_log(decision);
CREATE INDEX IF NOT EXISTS idx_decision_log_fast_lane   ON decision_log(fast_lane);
CREATE INDEX IF NOT EXISTS idx_decision_log_override    ON decision_log(human_override);
CREATE INDEX IF NOT EXISTS idx_decision_log_complaint   ON decision_log(complaint);

-- 错误模式挖掘查询辅助索引
CREATE INDEX IF NOT EXISTS idx_decision_log_mining
    ON decision_log(created_at, human_override, complaint)
    WHERE human_override = TRUE OR complaint = TRUE;
