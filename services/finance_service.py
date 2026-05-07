from repositories.order_repository import (
    aggregate_finance_summary,
    find_finance_pending_orders,
)
from utils.timezone import format_taipei


TYPE_LABELS = {
    "shop": "🛍️ 結緣品",
    "donation": "🕯️ 捐香",
    "fund": "🏗️ 建廟基金",
    "committee": "🏛️ 委員會",
}


def _serialize_finance_order(doc):
    """將 MongoDB 文件轉成前端可安全使用的財務單據格式。"""
    result = dict(doc)
    result["_id"] = str(result["_id"])
    result["createdAt"] = format_taipei(result.get("createdAt"))
    result["source_label"] = TYPE_LABELS.get(result.get("orderType", ""), "未知")
    if result.get("paymentDeadline"):
        result["paymentDeadline"] = format_taipei(result["paymentDeadline"])
    return result


def get_finance_pending(limit=None):
    """取得待收款清單；商業規則與 API 序列化集中在 Service 層。"""
    docs = find_finance_pending_orders(limit=limit)
    return [_serialize_finance_order(doc) for doc in docs]


def get_finance_summary():
    """取得財務摘要，依 orderType/status 整理為前端既有結構。"""
    raw_summary = aggregate_finance_summary()
    summary = {}
    for item in raw_summary:
        group = item.get("_id") or {}
        order_type = group.get("type") or "unknown"
        status = group.get("status") or "unknown"
        summary.setdefault(order_type, {})[status] = {
            "count": item.get("count", 0),
            "total": item.get("total", 0),
        }
    return summary
