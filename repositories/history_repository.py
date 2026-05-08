import database
from utils.errors import ServiceUnavailableError

def get_paginated_history(orders_match, feedback_match, skip, limit):
    """
    透過 $unionWith 結合 orders 與 feedback，並透過 $facet 同時返回總數與分頁資料
    """
    if database.db is None:
        raise ServiceUnavailableError("資料庫尚未連線")

    # 1. Orders 的處理管線
    orders_pipeline = [
        {"$match": orders_match},
        {"$project": {
            "_id": 1,
            "orderId": 1,
            "orderType": 1,
            "status": 1,
            "createdAt": 1,
            "updatedAt": 1,
            "total": 1,
            "customer": 1,
            "items": 1,
            "lineId": 1,
            "paymentDeadline": 1,
            "is_reported": 1,
            "paidAt": 1, "paidBy": 1,
            "shippedAt": 1, "shippedBy": 1,
            "reportedAt": 1, "reportedBy": 1,
            "trackingNumber": 1,
            "_docType": {"$literal": "order"}
        }}
    ]

    # 2. Feedback 的處理管線 (將欄位對齊 Order)
    feedback_pipeline = [
        {"$match": feedback_match},
        {"$project": {
            "_id": 1,
            "orderId": "$feedbackId",
            "feedbackId": 1,
            "orderType": {"$literal": "feedback"},
            "status": 1,
            "createdAt": 1,
            "total": {"$literal": 0},
            "customer": {"name": {"$ifNull": ["$nickname", "匿名"]}},
            "items": {"$literal": []},
            "approvedAt": 1, "approvedBy": 1,
            "sentAt": 1, "sentBy": 1,
            "trackingNumber": 1,
            "nickname": 1, "content": 1, "category": 1,
            "realName": 1, "phone": 1, "address": 1, "lineId": 1,
            "_docType": {"$literal": "feedback"}
        }}
    ]

    # 3. 主查詢管線 (合併、排序、分頁)
    pipeline = [
        *orders_pipeline,
        {"$unionWith": {
            "coll": "feedback",
            "pipeline": feedback_pipeline
        }},
        # 統一排序 (一定要有 _id 確保排序穩定性)
        {"$sort": {"createdAt": -1, "_id": -1}},
        # $facet 平行處理：一邊算總數，一邊切分頁
        {"$facet": {
            "metadata": [{"$count": "total"}],
            "data": [{"$skip": skip}, {"$limit": limit}]
        }}
    ]

    # allowDiskUse=True 避免資料量大時記憶體不足 (OOM)
    result = list(database.db.orders.aggregate(pipeline, allowDiskUse=True))

    total = result[0]["metadata"][0]["total"] if result[0]["metadata"] else 0
    data = result[0]["data"]

    return data, total
