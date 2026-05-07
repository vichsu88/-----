from pymongo.errors import DuplicateKeyError

import database
from utils.errors import ServiceUnavailableError
from utils.timezone import utc_now


ACTIVE_COMMITTEE_STATUSES = {"pending", "paid"}


def _require_db():
    if database.db is None:
        raise ServiceUnavailableError("Database is not available")
    return database.db


def calculate_committee_usage(role_name):
    db = _require_db()
    pipeline = [
        {"$match": {
            "orderType": "committee",
            "status": {"$in": list(ACTIVE_COMMITTEE_STATUSES)},
            "items.name": role_name,
        }},
        {"$unwind": "$items"},
        {"$match": {"items.name": role_name}},
        {"$group": {"_id": "$items.name", "used": {"$sum": {"$ifNull": ["$items.qty", 1]}}}},
        {"$limit": 1},
    ]
    doc = next(db.orders.aggregate(pipeline), None)
    return int(doc.get("used", 0)) if doc else 0


def ensure_committee_quota_usage(role_name, limit):
    """初始化/同步名額文件；既有 used 不覆蓋，避免覆寫正在扣減中的數值。"""
    db = _require_db()
    now = utc_now()
    used = calculate_committee_usage(role_name)
    try:
        db.committee_quota_usage.update_one(
            {"_id": role_name},
            {
                "$set": {
                    "limit": int(limit),
                    "updatedAt": now,
                },
                "$setOnInsert": {
                    "used": used,
                    "createdAt": now,
                },
            },
            upsert=True,
        )
    except DuplicateKeyError:
        # 多個請求同時初始化同一職稱時，只需要補上最新 limit。
        db.committee_quota_usage.update_one(
            {"_id": role_name},
            {"$set": {"limit": int(limit), "updatedAt": now}},
        )


def sync_committee_quota_usages(roles):
    for role in roles:
        name = role.get("name")
        if not name:
            continue
        ensure_committee_quota_usage(name, role.get("limit", 0))


def reserve_committee_quota(role_name, limit, quantity=1):
    """以單文件 atomic update 扣名額，非 replica set 環境也不會超賣。"""
    db = _require_db()
    quantity = max(1, int(quantity or 1))
    ensure_committee_quota_usage(role_name, limit)
    now = utc_now()
    expr = {"$lt": ["$used", "$limit"]}
    if quantity > 1:
        expr = {"$lte": [{"$add": ["$used", quantity]}, "$limit"]}

    result = db.committee_quota_usage.update_one(
        {
            "_id": role_name,
            "$expr": expr,
        },
        {
            "$inc": {"used": quantity},
            "$set": {
                "limit": int(limit),
                "updatedAt": now,
            },
        },
    )
    return result.modified_count == 1


def release_committee_quota(role_name, quantity=1):
    db = _require_db()
    quantity = max(1, int(quantity or 1))
    db.committee_quota_usage.update_one(
        {
            "_id": role_name,
            "used": {"$gte": quantity},
        },
        {
            "$inc": {"used": -quantity},
            "$set": {"updatedAt": utc_now()},
        },
    )


def release_committee_quota_for_order(order):
    if not order or order.get("orderType") != "committee":
        return
    if order.get("status") not in ACTIVE_COMMITTEE_STATUSES:
        return

    for item in order.get("items", []):
        role_name = item.get("name")
        if role_name:
            release_committee_quota(role_name, item.get("qty", 1))
