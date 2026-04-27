from database import db, write_audit_log
from utils.email import (
    generate_donation_created_email,
    generate_donation_paid_email,
    generate_shop_email_html,
    send_email,
)
from utils.errors import NotFoundError, ServiceUnavailableError, ValidationError
from utils.helpers import get_object_id
from utils.timezone import format_taipei, utc_now


def _require_db():
    if db is None:
        raise ServiceUnavailableError("Database is not available")


def _tw_datetime(value, fmt="%Y-%m-%d %H:%M"):
    return format_taipei(value, fmt)


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

    now = utc_now()
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

    now = utc_now()
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


def _mail_args(mail_config):
    mail_config = mail_config or {}
    return (
        mail_config.get("sendgrid_api_key"),
        mail_config.get("mail_sender"),
    )


def queue_order_created_email(order, mail_config=None):
    customer = order.get("customer", {})
    order_id = order.get("orderId", "")
    order_type = order.get("orderType")
    subject = f"【承天中承府】訂單確認 ({order_id})"
    if order_type == "donation":
        subject = f"【承天中承府】捐香登記確認 ({order_id})"
    elif order_type == "fund":
        subject = f"【承天中承府】建廟護持確認 ({order_id})"
    elif order_type == "committee":
        subject = f"【承天中承府】委員會發心護持確認 ({order_id})"

    if order_type in ["donation", "fund", "committee"]:
        html = generate_donation_created_email(order, db=db)
    else:
        html = generate_shop_email_html(order, "created", db=db)

    send_email(customer.get("email"), subject, html, *_mail_args(mail_config), is_html=True)


def queue_payment_confirmed_email(order, mail_config=None):
    customer = order.get("customer", {})
    order_id = order.get("orderId", "")
    if order.get("orderType") in ["donation", "fund", "committee"]:
        subject = f"【承天中承府】電子感謝狀 - 功德無量 ({order_id})"
        html = generate_donation_paid_email(
            customer,
            order_id,
            order.get("items", []),
            order.get("total", 0),
        )
    else:
        subject = f"【承天中承府】收款確認通知 ({order_id})"
        html = generate_shop_email_html(order, "paid", db=db)

    send_email(customer.get("email"), subject, html, *_mail_args(mail_config), is_html=True)


def queue_order_shipped_email(order, tracking_number, mail_config=None):
    customer = order.get("customer", {})
    order_id = order.get("orderId", "")
    subject = f"【承天中承府】訂單出貨通知 ({order_id})"
    html = generate_shop_email_html(order, "shipped", tracking_number, db=db)
    send_email(customer.get("email"), subject, html, *_mail_args(mail_config), is_html=True)
