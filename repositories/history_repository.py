import database
from utils.errors import ServiceUnavailableError


def _require_db():
    if database.db is None:
        raise ServiceUnavailableError("資料庫尚未連線")
    return database.db


def get_paginated_history(orders_match, feedback_match, skip, per_page):
    db = _require_db()
    pipeline = [
        {"$match": orders_match},
        {"$addFields": {
            "_docType": "order",
            "orderId": "$orderId",
        }},
        {"$unionWith": {
            "coll": "feedback",
            "pipeline": [
                {"$match": feedback_match},
                {"$addFields": {
                    "_docType": "feedback",
                    "orderType": "feedback",
                    "orderId": "$feedbackId",
                    "customer": {
                        "name": {"$ifNull": ["$realName", "$nickname"]}
                    },
                    "total": 0,
                }},
            ],
        }},
        {"$sort": {"createdAt": -1}},
        {"$facet": {
            "results": [
                {"$skip": skip},
                {"$limit": per_page},
            ],
            "count": [
                {"$count": "total"}
            ],
        }},
    ]
    result = next(db.orders.aggregate(pipeline), None) or {}
    results = result.get("results", [])
    count = result.get("count", [])
    total = count[0]["total"] if count else 0
    return results, total
