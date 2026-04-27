from datetime import timedelta

from database import db, write_audit_log
from utils.errors import NotFoundError, ServiceUnavailableError, ValidationError
from utils.helpers import get_object_id


def _require_db():
    if db is None:
        raise ServiceUnavailableError("Database is not available")


def _tw_datetime(value, fmt="%Y-%m-%d %H:%M"):
    if not value:
        return ""
    try:
        return (value + timedelta(hours=8)).strftime(fmt)
    except Exception:
        return str(value)


def _serialize_order(doc):
    doc["_id"] = str(doc["_id"])
    if doc.get("createdAt"):
        doc["createdAt"] = _tw_datetime(doc["createdAt"])
    if doc.get("reportedAt"):
        doc["reportedAt"] = _tw_datetime(doc["reportedAt"], "%Y-%m-%d")
    if doc.get("paidAt"):
        doc["paidAt"] = _tw_datetime(doc["paidAt"])
    if doc.get("shippedAt"):
        doc["shippedAt"] = _tw_datetime(doc["shippedAt"])
    return doc


def list_shop_orders(pagination):
    _require_db()
    query = {"orderType": "shop"}
    total = db.orders.count_documents(query)
    cursor = (
        db.orders.find(query)
        .sort("createdAt", -1)
        .skip(pagination.skip)
        .limit(pagination.per_page)
    )
    return [_serialize_order(doc) for doc in cursor], total


def list_admin_donations(query, pagination):
    _require_db()
    total = db.orders.count_documents(query)
    cursor = (
        db.orders.find(query)
        .sort([("is_reported", 1), ("createdAt", -1)])
        .skip(pagination.skip)
        .limit(pagination.per_page)
    )
    return [_serialize_order(doc) for doc in cursor], total


def confirm_payment(order_id, admin_user):
    _require_db()
    oid = get_object_id(order_id)
    if not oid:
        raise ValidationError("Invalid order id")

    order = db.orders.find_one({"_id": oid})
    if not order:
        raise NotFoundError("Order not found")

    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    db.orders.update_one(
        {"_id": oid},
        {"$set": {
            "status": "paid",
            "updatedAt": now,
            "paidAt": now,
            "paidBy": admin_user,
        }},
    )
    write_audit_log(admin_user, "confirm_payment", order.get("orderId", order_id), f"${order.get('total', 0)}")
    return order


def mark_shipped(order_id, tracking_number, admin_user):
    _require_db()
    oid = get_object_id(order_id)
    if not oid:
        raise ValidationError("Invalid order id")

    order = db.orders.find_one({"_id": oid})
    if not order:
        raise NotFoundError("Order not found")

    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    db.orders.update_one(
        {"_id": oid},
        {"$set": {
            "status": "shipped",
            "updatedAt": now,
            "shippedAt": now,
            "trackingNumber": tracking_number,
            "shippedBy": admin_user,
        }},
    )
    write_audit_log(admin_user, "ship_order", order.get("orderId", order_id), tracking_number)
    return order
