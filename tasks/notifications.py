import logging
import os

import database
from utils.email import (
    generate_donation_created_email,
    generate_donation_paid_email,
    generate_feedback_email_html,
    generate_shop_email_html,
    send_email_task,
)
from utils.helpers import get_object_id
from utils.line_bot import send_admin_notification
from utils.task_queue import celery_app, queue_available


logger = logging.getLogger(__name__)


def _ensure_db():
    if database.db is None:
        database.init_db(os.environ.get("MONGO_URI"))
    return database.db


def _find_order(order_ref):
    db = _ensure_db()
    if db is None or not order_ref:
        return None

    query = {"orderId": order_ref}
    oid = get_object_id(order_ref)
    if oid:
        query = {"$or": [{"_id": oid}, {"orderId": order_ref}]}
    return db.orders.find_one(query)


def _find_feedback(feedback_ref):
    db = _ensure_db()
    if db is None or not feedback_ref:
        return None

    query = {"feedbackId": feedback_ref}
    oid = get_object_id(feedback_ref)
    if oid:
        query = {"$or": [{"_id": oid}, {"feedbackId": feedback_ref}]}
    return db.feedback.find_one(query)


def _send_html_email(to_email, subject, html):
    if not to_email:
        return False
    return send_email_task(to_email, subject, html, True)


def _order_created_subject(order):
    order_id = order.get("orderId", "")
    order_type = order.get("orderType")
    if order_type == "donation":
        return f"【承天中承府】捐香登記確認 ({order_id})"
    if order_type == "fund":
        return f"【承天中承府】建廟護持確認 ({order_id})"
    if order_type == "committee":
        return f"【承天中承府】委員會發心護持確認 ({order_id})"
    return f"【承天中承府】訂單確認 ({order_id})"


def _order_created_html(order):
    if order.get("orderType") in ["donation", "fund", "committee"]:
        return generate_donation_created_email(order, db=_ensure_db())
    return generate_shop_email_html(order, "created", db=_ensure_db())


def _order_resend_payload(order):
    customer = order.get("customer", {})
    order_id = order.get("orderId", "")
    if order.get("orderType") == "donation":
        if order.get("status") == "paid":
            return (
                f"【補寄感謝狀】承天中承府 - 功德無量 ({order_id})",
                generate_donation_paid_email(
                    customer,
                    order_id,
                    order.get("items", []),
                    order.get("total", 0),
                ),
            )
        return (
            f"【補寄】護持登記確認通知 ({order_id})",
            generate_donation_created_email(order, db=_ensure_db()),
        )

    subject = f"【承天中承府】訂單信件補寄 ({order_id})"
    if order.get("status") == "shipped":
        html = generate_shop_email_html(order, "shipped", order.get("trackingNumber"), db=_ensure_db())
    elif order.get("status") == "paid":
        html = generate_shop_email_html(order, "paid", db=_ensure_db())
    else:
        html = generate_shop_email_html(order, "created", db=_ensure_db())
    return subject, html


def delay_notification(task, *args, **kwargs):
    """通知只負責排隊；排隊失敗不可影響 API 主流程。"""
    if task is None or not queue_available():
        logger.warning(
            "Notification task queue is unavailable; notification skipped",
            extra={"event": "notification_queue_unavailable"},
        )
        return False
    try:
        task.delay(*args, **kwargs)
        return True
    except Exception:
        logger.exception("Notification enqueue failed", extra={"event": "notification_enqueue_failed"})
        return False


if celery_app is not None:
    @celery_app.task(name="notification.send_order_created_email")
    def send_order_created_email(order_ref):
        order = _find_order(order_ref)
        if not order:
            logger.warning("Order not found for created email", extra={"event": "notification_order_missing"})
            return False
        return _send_html_email(
            order.get("customer", {}).get("email"),
            _order_created_subject(order),
            _order_created_html(order),
        )


    @celery_app.task(name="notification.send_payment_confirmed_email")
    def send_payment_confirmed_email(order_ref):
        order = _find_order(order_ref)
        if not order:
            logger.warning("Order not found for paid email", extra={"event": "notification_order_missing"})
            return False

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
            html = generate_shop_email_html(order, "paid", db=_ensure_db())
        return _send_html_email(customer.get("email"), subject, html)


    @celery_app.task(name="notification.send_order_shipped_email")
    def send_order_shipped_email(order_ref):
        order = _find_order(order_ref)
        if not order:
            logger.warning("Order not found for shipped email", extra={"event": "notification_order_missing"})
            return False
        order_id = order.get("orderId", "")
        subject = f"【承天中承府】訂單出貨通知 ({order_id})"
        html = generate_shop_email_html(order, "shipped", order.get("trackingNumber"), db=_ensure_db())
        return _send_html_email(order.get("customer", {}).get("email"), subject, html)


    @celery_app.task(name="notification.send_order_resend_email")
    def send_order_resend_email(order_ref):
        order = _find_order(order_ref)
        if not order:
            logger.warning("Order not found for resend email", extra={"event": "notification_order_missing"})
            return False
        subject, html = _order_resend_payload(order)
        return _send_html_email(order.get("customer", {}).get("email"), subject, html)


    @celery_app.task(name="notification.send_order_cancelled_email")
    def send_order_cancelled_email(cancel_payload):
        cancel_payload = cancel_payload or {}
        to_email = cancel_payload.get("email")
        order_id = cancel_payload.get("orderId", "")
        customer_name = cancel_payload.get("customerName") or "信徒"
        reason = cancel_payload.get("reason")

        if reason == "expired":
            subject = f"【承天中承府】訂單/捐贈登記已取消 ({order_id})"
            body = (
                f"親愛的 {customer_name} 您好：\n"
                f"您的訂單/捐贈登記 ({order_id}) 因超過付款期限，系統已自動取消。"
                f"如需服務請重新下單。"
            )
        else:
            subject = f"【承天中承府】訂單/登記已取消 ({order_id})"
            body = (
                f"親愛的 {customer_name} 您好：\n"
                f"您的訂單/登記 ({order_id}) 已被取消。"
                f"如為誤操作或有任何疑問，請聯繫官方 LINE。"
            )
        return send_email_task(to_email, subject, body, False)


    @celery_app.task(name="notification.send_plain_email")
    def send_plain_email(to_email, subject, body):
        return send_email_task(to_email, subject, body, False)


    @celery_app.task(name="notification.send_feedback_status_email")
    def send_feedback_status_email(feedback_ref, status_type, tracking_num=None):
        feedback = _find_feedback(feedback_ref)
        if not feedback:
            logger.warning("Feedback not found for email", extra={"event": "notification_feedback_missing"})
            return False

        db = _ensure_db()
        user = db.users.find_one({"lineId": feedback.get("lineId")}) if feedback.get("lineId") else {}
        email = user.get("email") or feedback.get("email")
        feedback_for_email = feedback.copy()
        feedback_for_email["realName"] = user.get("realName") or feedback.get("realName") or "信徒"
        subject_map = {
            "approved": "【承天中承府】您的回饋已核准刊登",
            "sent": "【承天中承府】結緣品寄出通知",
        }
        subject = subject_map.get(status_type, "【承天中承府】回饋通知")
        html = generate_feedback_email_html(feedback_for_email, status_type, tracking_num)
        return _send_html_email(email, subject, html)


    @celery_app.task(name="notification.send_feedback_rejected_email")
    def send_feedback_rejected_email(feedback_payload):
        feedback_payload = feedback_payload or {}
        email = feedback_payload.get("email")
        subject = "【承天中承府】感謝您的投稿與分享"
        html = generate_feedback_email_html(feedback_payload, "rejected")
        return _send_html_email(email, subject, html)


    @celery_app.task(name="notification.send_line_admin_notification")
    def send_line_admin_notification(message_text):
        send_admin_notification(message_text)
        return True
else:
    send_order_created_email = None
    send_payment_confirmed_email = None
    send_order_shipped_email = None
    send_order_resend_email = None
    send_order_cancelled_email = None
    send_plain_email = None
    send_feedback_status_email = None
    send_feedback_rejected_email = None
    send_line_admin_notification = None
