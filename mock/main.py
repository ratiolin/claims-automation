"""
Claims Automation Mock Service
All 19 endpoints for testing the Dify multi-agent claims processing system.
"""
import json
import time
import hashlib
import threading
from datetime import date, datetime, timedelta
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
from typing import Optional

app = FastAPI(title="Claims Mock Service")

# ── In-memory state ──────────────────────────────────────────
state_lock = threading.Lock()
state_db: dict = {}
fast_lane_lock = threading.Lock()
fast_lane_counts: dict = {}
payment_lock = threading.Lock()

# ── Test scenario data ───────────────────────────────────────

ORDERS = {
    "10001": {"amount": 45.0, "category": "日用品", "detail": "订单10001：日用品套装，下单2024-01-10，金额45.00元，状态已付款。"},
    "10002": {"amount": 300.0, "category": "电子产品", "detail": "订单10002：蓝牙耳机，下单2024-01-08，金额300.00元，状态已付款。"},
    "10003": {"amount": 1200.0, "category": "家电", "detail": "订单10003：微波炉，下单2024-01-05，金额1200.00元，状态已付款。"},
    "10004": {"amount": 55.0, "category": "服饰", "detail": "订单10004：运动鞋，下单2024-01-12，金额55.00元，状态已付款。"},
    "10005": {"amount": 88.0, "category": "食品", "detail": "订单10005：坚果礼盒，下单2024-01-03，金额88.00元，状态已付款。"},
}

LOGISTICS = {
    "10001": {"anomaly_type": "超时未更新", "trace": "2024-01-10 揽件 → 2024-01-12 运输中 → 至今无更新（超48小时）。"},
    "10002": {"anomaly_type": "错分", "trace": "2024-01-08 揽件 → 2024-01-09 错分至错误网点 → 2024-01-11 退回重发。"},
    "10003": {"anomaly_type": "超时未更新", "trace": "2024-01-05 揽件 → 2024-01-07 运输中 → 至今无更新。"},
    "10004": {"anomaly_type": "其他", "trace": "2024-01-12 揽件 → 2024-01-14 已签收。用户声称未收到。"},
    "10005": {"anomaly_type": "超时未更新", "trace": "2024-01-03 揽件 → 2024-01-04 运输中 → 至今无更新。"},
}

USERS = {
    "U001": {
        "claim_count_12m": 1,
        "static_risk": "low",
        "order_history": [
            {"order_id": "10001", "amount": 45.0, "status": "completed", "days_ago": 5},
            {"order_id": "10005", "amount": 88.0, "status": "completed", "days_ago": 18},
            {"order_id": "10010", "amount": 120.0, "status": "completed", "days_ago": 45},
        ],
        "claim_history": [
            {"claim_id": "C001", "amount": 30.0, "result": "approved", "days_ago": 180},
        ],
        "risk_flags": [],
    },
    "U002": {
        "claim_count_12m": 5,
        "static_risk": "high",
        "order_history": [
            {"order_id": "20001", "amount": 50.0, "status": "refunded", "days_ago": 2},
            {"order_id": "20002", "amount": 60.0, "status": "refunded", "days_ago": 5},
            {"order_id": "20003", "amount": 70.0, "status": "refunded", "days_ago": 8},
            {"order_id": "20004", "amount": 80.0, "status": "refunded", "days_ago": 10},
            {"order_id": "20005", "amount": 90.0, "status": "refunded", "days_ago": 15},
            {"order_id": "20006", "amount": 100.0, "status": "completed", "days_ago": 45},
            {"order_id": "20007", "amount": 110.0, "status": "completed", "days_ago": 60},
        ],
        "claim_history": [
            {"claim_id": "C101", "amount": 25.0, "result": "approved", "days_ago": 3},
            {"claim_id": "C102", "amount": 30.0, "result": "approved", "days_ago": 7},
            {"claim_id": "C103", "amount": 20.0, "result": "rejected", "days_ago": 14},
            {"claim_id": "C104", "amount": 40.0, "result": "manual_review", "days_ago": 20},
            {"claim_id": "C105", "amount": 35.0, "result": "approved", "days_ago": 25},
        ],
        "risk_flags": [
            {"flag": "高频退款", "severity": "high", "detail": "近30天退款率80%"},
            {"flag": "地址异常", "severity": "medium", "detail": "3个不同收货地址"},
        ],
    },
}


# ══════════════════════════════════════════════════════════════
#  2.2  订单 / 物流 / 用户画像 API Mock
# ══════════════════════════════════════════════════════════════

@app.get("/mock/order/amount")
def get_order_amount(order_id: str):
    if order_id == "99999":
        raise HTTPException(503, "Service unavailable")
    order = ORDERS.get(order_id)
    if not order:
        return {"order_id": order_id, "amount": None, "error": "not_found"}
    return {"order_id": order_id, "amount": order["amount"]}


@app.get("/mock/order/category")
def get_order_category(order_id: str):
    if order_id == "99999":
        raise HTTPException(503, "Service unavailable")
    order = ORDERS.get(order_id)
    if not order:
        return {"order_id": order_id, "category": None, "error": "not_found"}
    return {"order_id": order_id, "category": order["category"]}


@app.get("/mock/order/detail")
def get_order_detail(order_id: str):
    if order_id == "99999":
        raise HTTPException(503, "Service unavailable")
    order = ORDERS.get(order_id)
    if not order:
        return {"order_id": order_id, "detail": None, "error": "not_found"}
    return {"order_id": order_id, "detail": order["detail"]}


@app.get("/mock/logistics/anomaly-type")
def get_logistics_anomaly_type(order_id: str):
    if order_id == "99999":
        raise HTTPException(503, "Service unavailable")
    logi = LOGISTICS.get(order_id)
    if not logi:
        return {"order_id": order_id, "anomaly_type": None, "error": "not_found"}
    return {"order_id": order_id, "anomaly_type": logi["anomaly_type"]}


@app.get("/mock/logistics/trace")
def get_logistics_trace(order_id: str):
    if order_id == "99999":
        raise HTTPException(503, "Service unavailable")
    logi = LOGISTICS.get(order_id)
    if not logi:
        return {"order_id": order_id, "trace": None, "error": "not_found"}
    return {"order_id": order_id, "trace": logi["trace"]}


@app.get("/mock/policy/search")
def search_claim_policy(query: str = ""):
    return {
        "policy_text": (
            "理赔政策 v2.3（2024年1月生效）：\n"
            "1. 物流异常超48小时未更新，最高赔付订单金额2倍，上限5000元。\n"
            "2. 错分/丢件全额赔付，需提供物流异常截图。\n"
            "3. 用户30天内理赔超3次需人工审核。\n"
            "4. 材料需含订单截图与物流异常截图。\n"
            "5. 虚假材料永久拒绝理赔。\n"
            "6. 快速通道：金额≤100元、近12月理赔≤2次、物流类型为超时未更新或错分、信号灯绿色。"
        )
    }


@app.get("/mock/user/claim-count-12m")
def get_user_claim_count_12m(user_id: str):
    if user_id == "99999":
        raise HTTPException(503, "Service unavailable")
    user = USERS.get(user_id)
    if not user:
        return {"user_id": user_id, "claim_count_12m": 0}
    return {"user_id": user_id, "claim_count_12m": user["claim_count_12m"]}


@app.get("/mock/user/static-risk")
def get_static_risk_level(user_id: str):
    if user_id == "99999":
        raise HTTPException(503, "Service unavailable")
    user = USERS.get(user_id)
    if not user:
        return {"user_id": user_id, "static_risk": "low"}
    return {"user_id": user_id, "static_risk": user["static_risk"]}


@app.get("/mock/user/order-history")
def get_user_order_history(user_id: str):
    if user_id == "99999":
        raise HTTPException(503, "Service unavailable")
    user = USERS.get(user_id)
    if not user:
        return json.dumps([])
    return json.dumps(user["order_history"])


@app.get("/mock/user/claim-history")
def get_user_claim_history(user_id: str):
    if user_id == "99999":
        raise HTTPException(503, "Service unavailable")
    user = USERS.get(user_id)
    if not user:
        return json.dumps([])
    return json.dumps(user["claim_history"])


@app.get("/mock/user/risk-flags")
def get_user_risk_flags(user_id: str):
    if user_id == "99999":
        raise HTTPException(503, "Service unavailable")
    user = USERS.get(user_id)
    if not user:
        return json.dumps([])
    return json.dumps(user["risk_flags"])


# ══════════════════════════════════════════════════════════════
#  2.3  图像分类服务 Mock
# ══════════════════════════════════════════════════════════════

class ClassifyRequest(BaseModel):
    file_names: Optional[list[str]] = None

@app.post("/mock/vision/classify")
async def classify_materials(request: Request):
    """
    模拟视觉模型材料验证。
    默认返回 source="vision_model"（高可靠），
    传入 file_names=["no_order"] 可模拟材料缺失。
    """
    try:
        body = await request.json()
        files = body.get("file_names", []) if body else []
    except Exception:
        files = []

    has_order = "no_order" not in files
    has_logistics = "no_logistics" not in files

    return {
        "has_order_screenshot": has_order,
        "has_logistics_screenshot": has_logistics,
        "source": "vision_model"
    }


class OCRRequest(BaseModel):
    image_data: Optional[str] = None

@app.post("/mock/vision/parse-image")
def parse_image(request: OCRRequest):
    return {
        "image_text": (
            "订单号 10001，物流单号 SF1234567890。"
            "2024-01-10 发货，物流状态至今未更新。"
            "联系客服3次未解决，要求赔付。"
        )
    }


# ══════════════════════════════════════════════════════════════
#  2.4  配置中心 biz_stats Mock
# ══════════════════════════════════════════════════════════════

CURRENT_BIZ_STATS = {
    "degradation_index": 0.15,
    "smoothed_degradation_index": 0.12,
    "queue_pressure": 0.3,
    "signal_light": "green",
    "k_factor": 2.0,
    "max_daily_fast_lane": 3,
    "max_degradation_fast_lane": 0.3,
}

@app.get("/mock/biz-stats")
def get_recent_biz_stats():
    return {**CURRENT_BIZ_STATS, "timestamp": int(time.time())}


@app.post("/mock/biz-stats/update")
def update_biz_stats(stats: dict):
    """用于测试时动态调整业务态势参数"""
    for key in ["degradation_index", "smoothed_degradation_index",
                "queue_pressure", "signal_light", "k_factor",
                "max_daily_fast_lane", "max_degradation_fast_lane"]:
        if key in stats:
            CURRENT_BIZ_STATS[key] = stats[key]
    return {"status": "updated", "stats": CURRENT_BIZ_STATS}


# ══════════════════════════════════════════════════════════════
#  2.5  理赔状态机服务 Mock
# ══════════════════════════════════════════════════════════════

class CreateRequest(BaseModel):
    claim_id: str
    status: str = "processing"
    ttl: int = 1800

@app.post("/mock/state-machine/create")
def create_if_absent(req: CreateRequest):
    with state_lock:
        if req.claim_id in state_db:
            return {
                "result": "duplicate",
                "claim_id": req.claim_id,
                "message": "申请已提交，请勿重复操作"
            }
        state_db[req.claim_id] = {
            "status": req.status,
            "created_at": time.time(),
            "ttl": req.ttl,
            "paid": False,
            "paid_amount": 0,
        }
        return {"result": "created", "claim_id": req.claim_id, "status": req.status}


class CompleteRequest(BaseModel):
    claim_id: str
    expected: str = "processing"
    next: str = "completed"

@app.post("/mock/state-machine/complete")
def complete_if_status(req: CompleteRequest):
    with state_lock:
        record = state_db.get(req.claim_id)
        if not record:
            return {"result": "not_found", "claim_id": req.claim_id}
        if record["status"] != req.expected:
            return {
                "result": "conflict",
                "claim_id": req.claim_id,
                "current": record["status"],
                "expected": req.expected,
            }
        record["status"] = req.next
        record["completed_at"] = time.time()
        return {"result": "migrated", "claim_id": req.claim_id, "status": req.next}


@app.get("/mock/state-machine/status")
def get_state(claim_id: str):
    record = state_db.get(claim_id)
    if not record:
        return {"claim_id": claim_id, "status": "not_found"}
    return {"claim_id": claim_id, "status": record["status"]}


@app.post("/mock/state-machine/reset")
def reset_state_db():
    with state_lock:
        state_db.clear()
    return {"status": "reset", "count": 0}


# ══════════════════════════════════════════════════════════════
#  2.6  快速通道计数服务 Mock
# ══════════════════════════════════════════════════════════════

class FastLaneRequest(BaseModel):
    user_id: str
    claim_id: str
    max_daily_fast_lane: int = 3

@app.post("/mock/fast-lane/try-increment")
def try_increment_fast_lane(req: FastLaneRequest):
    today = str(date.today())
    with fast_lane_lock:
        record = fast_lane_counts.get(req.user_id, {"count": 0, "date": today})
        if record["date"] != today:
            record = {"count": 0, "date": today}
        if record["count"] >= req.max_daily_fast_lane:
            return {
                "accepted": False,
                "new_count": record["count"],
                "max_daily_fast_lane": req.max_daily_fast_lane,
                "message": "当日快速通道次数已用完",
            }
        record["count"] += 1
        fast_lane_counts[req.user_id] = record
        return {
            "accepted": True,
            "new_count": record["count"],
            "max_daily_fast_lane": req.max_daily_fast_lane,
        }


@app.get("/mock/fast-lane/count")
def get_fast_lane_count(user_id: str):
    today = str(date.today())
    with fast_lane_lock:
        record = fast_lane_counts.get(user_id, {"count": 0, "date": today})
        count = record["count"] if record["date"] == today else 0
    return {
        "user_id": user_id,
        "count": count,
        "fast_lane_count_today": count,
        "date": today,
    }


@app.post("/mock/fast-lane/reset")
def reset_fast_lane():
    with fast_lane_lock:
        fast_lane_counts.clear()
    return {"status": "reset"}


# ══════════════════════════════════════════════════════════════
#  2.7  支付服务 Mock
# ══════════════════════════════════════════════════════════════

class PaymentRequest(BaseModel):
    claim_id: str
    amount: float
    user_id: str = ""

@app.post("/mock/payment/execute")
def execute_payment(req: PaymentRequest):
    with payment_lock:
        if req.amount <= 0:
            return {
                "result": "skipped",
                "claim_id": req.claim_id,
                "amount": req.amount,
                "message": "无需支付",
            }
        record = state_db.get(req.claim_id)
        if record and record.get("paid"):
            return {
                "result": "already_paid",
                "claim_id": req.claim_id,
                "message": "该理赔已支付",
            }
        if record:
            record["paid"] = True
            record["paid_amount"] = req.amount
        txn_id = f"TXN-{req.claim_id}-{int(time.time())}"
        return {
            "result": "success",
            "claim_id": req.claim_id,
            "amount": req.amount,
            "transaction_id": txn_id,
        }


# ══════════════════════════════════════════════════════════════
#  2.8  决策日志 Mock
# ══════════════════════════════════════════════════════════════

decision_log_store: list[dict] = []


class DecisionLogRequest(BaseModel):
    claim_id: str
    order_id: str = ""
    user_id: str = ""
    claim_valid: Optional[bool] = None
    claim_reason: str = ""
    suggested_amount: float = 0
    confidence: str = ""
    risk_level: str = ""
    risk_reason: str = ""
    decision: str = ""
    final_amount: float = 0
    dynamic_threshold: float = 0
    k_factor: float = 0
    degradation_index: float = 0
    queue_pressure: float = 0
    threshold_details: str = ""
    user_message: str = ""
    review_reason: str = ""
    copy_quality_score: float = 0
    fast_lane: bool = False
    material_source: str = ""
    is_shadow_mode: bool = True
    human_override: bool = False
    human_decision: str = ""
    complaint: bool = False
    raw_claim_result: str = ""
    raw_risk_result: str = ""
    evidence_package: str = ""


@app.post("/mock/decision-log/insert")
def insert_decision_log(log: DecisionLogRequest):
    entry = log.model_dump()
    entry["id"] = len(decision_log_store) + 1
    entry["created_at"] = datetime.now().isoformat()
    decision_log_store.append(entry)
    return {"result": "inserted", "id": entry["id"]}


@app.get("/mock/decision-log/query")
def query_decision_log(
    days: int = 7,
    human_override: Optional[bool] = None,
    complaint: Optional[bool] = None,
    decision: Optional[str] = None,
):
    cutoff = datetime.now() - timedelta(days=days)
    results = []
    for entry in decision_log_store:
        created = datetime.fromisoformat(entry["created_at"])
        if created < cutoff:
            continue
        if human_override is not None and entry.get("human_override") != human_override:
            continue
        if complaint is not None and entry.get("complaint") != complaint:
            continue
        if decision is not None and entry.get("decision") != decision:
            continue
        results.append(entry)
    return {"count": len(results), "results": results}


@app.post("/mock/decision-log/reset")
def reset_decision_log():
    decision_log_store.clear()
    return {"status": "reset", "count": 0}


# ══════════════════════════════════════════════════════════════
#  全局重置
# ══════════════════════════════════════════════════════════════

@app.post("/mock/reset-all")
def reset_all():
    with state_lock:
        state_db.clear()
    with fast_lane_lock:
        fast_lane_counts.clear()
    decision_log_store.clear()
    # 恢复默认 biz_stats
    CURRENT_BIZ_STATS.update({
        "degradation_index": 0.15,
        "smoothed_degradation_index": 0.12,
        "queue_pressure": 0.3,
        "signal_light": "green",
        "k_factor": 2.0,
        "max_daily_fast_lane": 3,
        "max_degradation_fast_lane": 0.3,
    })
    return {"status": "reset", "state_count": 0, "fast_lane_count": 0, "decision_log_count": 0}


@app.get("/health")
def health():
    return {"status": "ok", "service": "claims-mock"}

