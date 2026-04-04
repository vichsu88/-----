import io
import random
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from flask import Blueprint, jsonify, request, session, Response, current_app

from database import db, write_audit_log
from extensions import csrf
from utils.decorators import login_required, user_login_required
from utils.helpers import get_object_id, validate_real_name, mask_name
from utils.email import (
    send_email,
    generate_shop_email_html,
    generate_donation_created_email,
    generate_donation_paid_email,
)

orders_bp = Blueprint('orders', __name__)


@orders_bp.route('/api/donations/public', methods=['GET'])
def get_public_donations():
    if db is None:
        return jsonify([]), 500

    target_type = request.args.get('type', 'donation')
    query = {"status": "paid"}

    if target_type == 'all':
        query["orderType"] = {"$in": ["donation", "fund", "committee"]}
    else:
        query["orderType"] = target_type

    cursor = db.orders.find(query).sort("updatedAt", -1).limit(1000)
    results = []
    for doc in cursor:
        items_summary = [f"{i['name']} x{i['qty']}" for i in doc.get('items', [])]
        results.append({
            "name": mask_name(doc.get('customer', {}).get('name', '善信')),
            "wish": doc.get('customer', {}).get('prayer', '祈求平安'),
            "items": ", ".join(items_summary)
        })
    return jsonify(results)


@orders_bp.route('/api/donations/admin', methods=['GET'])
@login_required
def get_admin_donations():
    type_filter = request.args.get('type')
    status_filter = request.args.get('status')
    report_filter = request.args.get('reported')

    query = {}
    if type_filter:
        query['orderType'] = type_filter
    else:
        query['orderType'] = {"$in": ["donation", "fund", "committee"]}

    if status_filter:
        query['status'] = status_filter

    if type_filter == 'donation' and report_filter is not None:
        query['is_reported'] = (report_filter == '1')

    start_str = request.args.get('start')
    end_str = request.args.get('end')
    if start_str and end_str:
        try:
            start_date = datetime.strptime(start_str, '%Y-%m-%d')
            end_date = datetime.strptime(end_str, '%Y-%m-%d') + timedelta(days=1)
            query["createdAt"] = {"$gte": start_date, "$lt": end_date}
        except Exception:
            pass

    cursor = db.orders.find(query).sort([("is_reported", 1), ("createdAt", -1)])
    results = []
    for doc in cursor:
        doc['_id'] = str(doc['_id'])
        doc['createdAt'] = (doc['createdAt'] + timedelta(hours=8)).strftime('%Y-%m-%d %H:%M')
        if doc.get('reportedAt'):
            doc['reportedAt'] = (doc['reportedAt'] + timedelta(hours=8)).strftime('%Y-%m-%d')
        results.append(doc)
    return jsonify(results)


@orders_bp.route('/api/donations/export-txt', methods=['POST'])
@login_required
def export_donations_txt():
    data = request.get_json() or {}
    start_str = data.get('start')
    end_str = data.get('end')

    order_type = data.get('type', 'donation')
    query = {"orderType": order_type, "status": "paid"}

    if start_str and end_str:
        try:
            start_date = datetime.strptime(start_str, '%Y-%m-%d')
            end_date = datetime.strptime(end_str, '%Y-%m-%d') + timedelta(days=1)
            query["updatedAt"] = {"$gte": start_date, "$lt": end_date}
        except Exception:
            pass

    cursor = db.orders.find(query).sort("updatedAt", 1)
    orders = list(cursor)
    if not orders:
        return jsonify({"error": "目前無資料"}), 404

    title_map = {'fund': '建廟基金護持清單', 'committee': '委員會護持清單', 'donation': '捐贈稟報清單'}
    report_title = title_map.get(order_type, '護持清單')

    si = io.StringIO()
    si.write(f"{report_title}\n匯出日期：{datetime.now().strftime('%Y-%m-%d')}\n")
    si.write("=" * 40 + "\n\n")

    idx = 1
    for doc in orders:
        cust = doc.get('customer', {})
        items_str = "、".join([f"{i['name']}x{i['qty']}" for i in doc.get('items', [])])
        paid_date = doc.get('updatedAt').strftime('%Y/%m/%d') if doc.get('updatedAt') else ''

        si.write(f"【{idx}】\n")
        si.write(f"日期：{paid_date}\n")
        si.write(f"姓名：{cust.get('name', '')}\n")
        si.write(f"農曆：{cust.get('lunarBirthday', '')}\n")
        si.write(f"地址：{cust.get('address', '')}\n")

        if order_type in ['fund', 'committee']:
            si.write(f"金額：${doc.get('total', 0)}\n")
            si.write(f"末五碼：{cust.get('last5', '無')}\n")

        si.write(f"項目：{items_str}\n")
        si.write("-" * 20 + "\n")
        idx += 1

    return Response(si.getvalue(), mimetype='text/plain',
                    headers={"Content-Disposition": f"attachment; filename={order_type}_list.txt"})


@orders_bp.route('/api/donations/cleanup-unpaid', methods=['DELETE'])
@login_required
def cleanup_unpaid_orders():
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=76)
    cursor = db.orders.find({"status": "pending", "createdAt": {"$lt": cutoff}})
    for order in cursor:
        if order.get('customer', {}).get('email'):
            subject = f"【承天中承府】訂單/捐贈登記已取消 ({order['orderId']})"
            body = f"親愛的 {order['customer'].get('name', '信徒')} 您好：\n您的訂單/捐贈登記 ({order['orderId']}) 因超過付款期限，系統已自動取消。如需服務請重新下單。"
            send_email(order['customer']['email'], subject, body,
                       current_app.config['SENDGRID_API_KEY'], current_app.config['MAIL_SENDER'])

    result = db.orders.delete_many({"status": "pending", "createdAt": {"$lt": cutoff}})
    return jsonify({"success": True, "count": result.deleted_count})


@csrf.exempt
@orders_bp.route('/api/orders', methods=['POST'])
@user_login_required
def create_order():
    if db is None:
        return jsonify({"error": "DB Error"}), 500
    data = request.get_json()
    line_id = session.get('user_line_id')

    order_type = data.get('orderType', 'shop')

    is_valid, error_msg = validate_real_name(data.get('name', '').strip())
    if not is_valid:
        return jsonify({"error": f"系統阻擋：{error_msg}"}), 400

    if order_type == 'fund':
        for item in data.get('items', []):
            item_name = item.get('name')
            item_qty = int(item.get('qty', 0))

            if item_name in ['副主委', '委員', '顧問'] and item_qty != 1:
                return jsonify({"error": f"【{item_name}】每次結帳限購 1 名，數量不可更改。"}), 400

            if item_name == '副主委':
                used_count = db.orders.count_documents({
                    "orderType": "fund",
                    "status": {"$in": ["paid", "pending"]},
                    "items.name": "副主委"
                })
                if used_count >= 7:
                    return jsonify({"error": "非常抱歉，【副主委】7名額已全數被預約完畢！"}), 400

    if order_type == 'committee':
        def check_limit(name, max_limit):
            used = db.orders.count_documents({
                "orderType": "committee",
                "status": {"$in": ["paid", "pending"]},
                "items.name": name
            })
            return used >= max_limit

        for item in data.get('items', []):
            item_name = item.get('name')
            item_qty = int(item.get('qty', 0))

            if item_qty != 1 and item_name != '[建廟] 建廟功德金':
                return jsonify({"error": f"【{item_name}】每次結帳限購 1 名。"}), 400

            if item_name == '[本府] 主委' and check_limit(item_name, 1):
                return jsonify({"error": "【[本府] 主委】名額已滿！"}), 400
            if item_name == '[本府] 副主委' and check_limit(item_name, 7):
                return jsonify({"error": "【[本府] 副主委】名額已滿！"}), 400
            if item_name == '[建廟] 籌備主委' and check_limit(item_name, 1):
                return jsonify({"error": "【[建廟] 籌備主委】名額已滿！"}), 400
            if item_name == '[建廟] 籌備副主委' and check_limit(item_name, 0):
                return jsonify({"error": "【[建廟] 籌備副主委】名額已滿！"}), 400

    prefix = "ORD"
    if order_type == 'donation': prefix = "DON"
    elif order_type == 'fund': prefix = "FND"
    elif order_type == 'committee': prefix = "COM"

    order_id = f"{prefix}{datetime.now().strftime('%Y%m%d%H%M%S')}{random.randint(10,99)}"

    customer_info = {
        "name": data.get('name'),
        "phone": data.get('phone'),
        "email": data.get('email', ''),
        "address": data.get('address'),
        "last5": data.get('last5'),
        "lunarBirthday": data.get('lunarBirthday', ''),
        "shippingMethod": data.get('shippingMethod', 'home'),
        "storeInfo": data.get('storeInfo', ''),
        "shippingFee": data.get('shippingFee', 120)
    }

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    deadline = now + timedelta(hours=2)

    order = {
        "orderId": order_id, "orderType": order_type, "customer": customer_info,
        "items": data['items'], "total": data['total'], "status": "pending",
        "lineId": line_id,
        "paymentDeadline": deadline,
        "createdAt": now, "updatedAt": now
    }

    if order_type == 'donation':
        order['is_reported'] = False

    db.orders.insert_one(order)

    subject = f"【承天中承府】訂單確認 ({order_id})"
    if order_type == 'donation':
        subject = f"【承天中承府】捐香登記確認 ({order_id})"
    elif order_type == 'fund':
        subject = f"【承天中承府】建廟護持確認 ({order_id})"
    elif order_type == 'committee':
        subject = f"【承天中承府】委員會發心護持確認 ({order_id})"

    if order_type in ['donation', 'fund', 'committee']:
        html = generate_donation_created_email(order, db=db)
    else:
        html = generate_shop_email_html(order, 'created', db=db)

    send_email(customer_info['email'], subject, html,
               current_app.config['SENDGRID_API_KEY'], current_app.config['MAIL_SENDER'],
               is_html=True)
    return jsonify({"success": True, "orderId": order_id})


@orders_bp.route('/api/donations/mark-reported', methods=['POST'])
@login_required
def mark_donations_reported():
    data = request.get_json()
    ids = data.get('ids', [])
    if not ids:
        return jsonify({"success": False, "message": "無選取訂單"})
    if object_ids:
        admin_user = session.get('admin_username', 'admin') # 取得當下操作員
        db.orders.update_many(
            {"_id": {"$in": object_ids}},
            {"$set": {"is_reported": True, "reportedAt": datetime.now(timezone.utc).replace(tzinfo=None), "reportedBy": admin_user}}
        )

    object_ids = [get_object_id(i) for i in ids if get_object_id(i)]
    if object_ids:
        db.orders.update_many(
            {"_id": {"$in": object_ids}},
            {"$set": {"is_reported": True, "reportedAt": datetime.now(timezone.utc).replace(tzinfo=None)}}
        )
        write_audit_log(session.get('admin_username', 'admin'), '標記已稟告', '', f'{len(object_ids)} 筆')
    return jsonify({"success": True})


@orders_bp.route('/api/orders', methods=['GET'])
@login_required
def get_orders():
    cursor = db.orders.find({"orderType": "shop"}).sort("createdAt", -1)
    results = []
    for doc in cursor:
        doc['_id'] = str(doc['_id'])
        doc['createdAt'] = (doc['createdAt'] + timedelta(hours=8)).strftime('%Y-%m-%d %H:%M')
        results.append(doc)
    return jsonify(results)


@orders_bp.route('/api/orders/cleanup-shipped', methods=['DELETE'])
@login_required
def cleanup_shipped_orders():
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=14)
    result = db.orders.delete_many({"status": "shipped", "shippedAt": {"$lt": cutoff}})
    return jsonify({"success": True, "count": result.deleted_count})


@orders_bp.route('/api/orders/<oid>/confirm', methods=['PUT'])
@login_required
def confirm_order_payment(oid):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    admin_user = session.get('admin_username', 'admin') # 取得當下操作員
    db.orders.update_one({'_id': oid_obj}, {'$set': {'status': 'paid', 'updatedAt': now, 'paidAt': now, 'paidBy': admin_user}})
    oid_obj = get_object_id(oid)
    if not oid_obj:
        return jsonify({"error": "無效的 ID 格式"}), 400

    order = db.orders.find_one({'_id': oid_obj})
    if not order:
        return jsonify({"error": "No order"}), 404

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    db.orders.update_one({'_id': oid_obj}, {'$set': {'status': 'paid', 'updatedAt': now, 'paidAt': now}})
    write_audit_log(session.get('admin_username', 'admin'), '確認收款', order.get('orderId', oid), f"${order.get('total', 0)}")
    cust = order['customer']

    if order.get('orderType') in ['donation', 'fund', 'committee']:
        email_subject = f"【承天中承府】電子感謝狀 - 功德無量 ({order['orderId']})"
        email_html = generate_donation_paid_email(cust, order['orderId'], order['items'], order['total'])
        send_email(cust.get('email'), email_subject, email_html,
                   current_app.config['SENDGRID_API_KEY'], current_app.config['MAIL_SENDER'],
                   is_html=True)
    else:
        email_subject = f"【承天中承府】收款確認通知 ({order['orderId']})"
        email_html = generate_shop_email_html(order, 'paid', db=db)
        send_email(cust.get('email'), email_subject, email_html,
                   current_app.config['SENDGRID_API_KEY'], current_app.config['MAIL_SENDER'],
                   is_html=True)
    return jsonify({"success": True})


@orders_bp.route('/api/orders/<oid>/resend-email', methods=['POST'])
@login_required
def resend_order_email(oid):
    oid_obj = get_object_id(oid)
    if not oid_obj:
        return jsonify({"error": "無效的 ID 格式"}), 400

    data = request.get_json()
    new_email = data.get('email')
    order = db.orders.find_one({'_id': oid_obj})
    if not order:
        return jsonify({"error": "No order"}), 404

    cust = order['customer']
    target_email = cust.get('email')

    if new_email and new_email != target_email:
        db.orders.update_one({'_id': oid_obj}, {'$set': {'customer.email': new_email}})
        cust['email'] = new_email
        target_email = new_email

    if order.get('orderType') == 'donation':
        if order.get('status') == 'paid':
            email_subject = f"【補寄感謝狀】承天中承府 - 功德無量 ({order['orderId']})"
            email_html = generate_donation_paid_email(cust, order['orderId'], order['items'], order['total'])
        else:
            email_subject = f"【補寄】護持登記確認通知 ({order['orderId']})"
            email_html = generate_donation_created_email(order, db=db)
    else:
        email_subject = f"【承天中承府】訂單信件補寄 ({order['orderId']})"
        if order.get('status') == 'shipped':
            email_html = generate_shop_email_html(order, 'shipped', order.get('trackingNumber'), db=db)
        elif order.get('status') == 'paid':
            email_html = generate_shop_email_html(order, 'paid', db=db)
        else:
            email_html = generate_shop_email_html(order, 'created', db=db)

    send_email(target_email, email_subject, email_html,
               current_app.config['SENDGRID_API_KEY'], current_app.config['MAIL_SENDER'],
               is_html=True)
    return jsonify({"success": True})


@orders_bp.route('/api/orders/<oid>', methods=['DELETE'])
@login_required
def delete_order(oid):
    oid_obj = get_object_id(oid)
    if not oid_obj:
        return jsonify({"error": "無效的 ID 格式"}), 400

    order = db.orders.find_one({'_id': oid_obj})
    if order and order.get('customer', {}).get('email'):
        subject = f"【承天中承府】訂單/登記已取消 ({order['orderId']})"
        body = f"親愛的 {order['customer'].get('name', '信徒')} 您好：\n您的訂單/登記 ({order['orderId']}) 已被取消。如為誤操作或有任何疑問，請聯繫官方 LINE。"
        send_email(order['customer']['email'], subject, body,
                   current_app.config['SENDGRID_API_KEY'], current_app.config['MAIL_SENDER'])

    write_audit_log(session.get('admin_username', 'admin'), '刪除訂單', order.get('orderId', oid) if order else oid)
    db.orders.delete_one({'_id': oid_obj})
    return jsonify({"success": True})


@orders_bp.route('/api/orders/<oid>/ship', methods=['PUT'])
@login_required
def ship_order(oid):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    admin_user = session.get('admin_username', 'admin') # 取得當下操作員
    db.orders.update_one({'_id': oid_obj}, {'$set': {
        'status': 'shipped', 'updatedAt': now, 'shippedAt': now, 'trackingNumber': tracking_num, 'shippedBy': admin_user
    }})
    oid_obj = get_object_id(oid)
    if not oid_obj:
        return jsonify({"error": "無效的 ID 格式"}), 400

    data = request.get_json() or {}
    tracking_num = data.get('trackingNumber', '').strip()
    order = db.orders.find_one({'_id': oid_obj})
    if not order:
        return jsonify({"error": "No order"}), 404

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    db.orders.update_one({'_id': oid_obj}, {'$set': {
        'status': 'shipped', 'updatedAt': now, 'shippedAt': now, 'trackingNumber': tracking_num
    }})
    write_audit_log(session.get('admin_username', 'admin'), '出貨', order.get('orderId', oid), tracking_num)
    cust = order['customer']
    email_subject = f"【承天中承府】訂單出貨通知 ({order['orderId']})"
    email_html = generate_shop_email_html(order, 'shipped', tracking_num, db=db)
    send_email(cust.get('email'), email_subject, email_html,
               current_app.config['SENDGRID_API_KEY'], current_app.config['MAIL_SENDER'],
               is_html=True)
    return jsonify({"success": True})
