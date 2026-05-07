import database
from utils.errors import ServiceUnavailableError


def _orders_collection():
    """集中取得 orders collection，避免 Service 層直接接觸 MongoDB。"""
    if database.db is None:
        raise ServiceUnavailableError("資料庫尚未連線")
    return database.db.orders


def find_finance_pending_orders(limit=None):
    """查詢財務待收款訂單，回傳原始 MongoDB 文件供 Service 序列化。"""
    cursor = (
        _orders_collection()
        .find({"status": "pending"})
        .sort("createdAt", -1)
    )
    if limit:
        cursor = cursor.limit(limit)
    return list(cursor)


def aggregate_finance_summary():
    """彙總訂單類別與狀態的筆數、金額，封裝 MongoDB aggregation 細節。"""
    pipeline = [
        {
            "$group": {
                "_id": {"type": "$orderType", "status": "$status"},
                "count": {"$sum": 1},
                "total": {"$sum": "$total"},
            }
        }
    ]
    return list(_orders_collection().aggregate(pipeline))
