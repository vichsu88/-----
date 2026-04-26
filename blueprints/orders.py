import io
import random
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from utils.line_bot import send_admin_notification
from flask import Blueprint, jsonify, request, session, Response, current_app
from pymongo.errors import ConfigurationError, OperationFailure, PyMongoError

from database import db, get_client, write_audit_log
from utils.decorators import admin_required, user_login_required
from utils.helpers import get_object_id, validate_real_name, mask_name
from utils.email import (
    send_email,
    generate_shop_email_html,
    generate_donation_created_email,
    generate_donation_paid_email,
)

orders_bp = Blueprint('orders', __name__)

# 註：/api/public/committee-status 改由 main.py 提供（包含 price 欄位）


class OrderValidationError(ValueError):
    pass


PRODUCT_PROJECTION = {
    "name": 1,
    "price": 1,
    "variants": 1,
    "isActive": 1,
    "isDonation": 1,
}


FUND_ITEMS = {
    'suixi': {'name': '[建廟] 隨喜助建', 'price': 100},
    'tile': {'name': '[建廟] 建廟瓦片', 'price': 600},
    'pillar': {'name': '[建廟] 龍柱認捐', 'price': 10000},
}
FUND_ITEM_NAMES = {v['name']: k for k, v in FUND_ITEMS.items()}
FUND_ITEM_NAMES.update({v['name'].replace('[建廟] ', ''): k for k, v in FUND_ITEMS.items()})


def _to_positive_int(value, field='數量', max_value=99):
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise OrderValidationError(f"{field}格式錯誤")
    if number < 1 or number > max_value:
        raise OrderValidationError(f"{field}必須介於 1 到 {max_value} 之間")
    return number


def _to_money(value, field='金額'):
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise OrderValidationError(f"{field}格式錯誤")
    if number < 0:
        raise OrderValidationError(f"{field}不可為負數")
    return number


def _normalize_product_item(raw_item, order_type, product=None):
    product_id = raw_item.get('id')
    product_oid = get_object_id(product_id)
    if not product_oid:
        raise OrderValidationError("商品資料格式錯誤，請重新整理頁面")

    if product is None:
        product = db.products.find_one({"_id": product_oid}, PRODUCT_PROJECTION)
    if not product or not product.get('isActive', True):
        raise OrderValidationError("商品已下架，請重新整理頁面")
    if order_type == 'donation' and not product.get('isDonation', False):
        raise OrderValidationError("護持項目資料不正確，請重新整理頁面")

    qty = _to_positive_int(raw_item.get('qty'), max_value=99)
    product_name = str(product.get('name') or '').strip()
    if not product_name:
        raise OrderValidationError("商品名稱資料不完整")

    variants = product.get('variants') or []
    requested_variant = raw_item.get('variantName') or raw_item.get('variant')
    variant_name = None
    if variants:
        variant = None
        if requested_variant:
            variant = next((v for v in variants if str(v.get('name')) == str(requested_variant)), None)
        else:
            variant = variants[0]
        if not variant:
            raise OrderValidationError(f"商品「{product_name}」規格不存在，請重新選擇")
        variant_name = str(variant.get('name') or '').strip()
        price = _to_money(variant.get('price'), '商品價格')
    else:
        price = _to_money(product.get('price'), '商品價格')

    normalized = {
        "id": str(product['_id']),
        "name": product_name,
        "price": price,
        "qty": qty,
    }
    if order_type == 'shop':
        normalized["variant"] = variant_name or raw_item.get('variant') or '標準'
        normalized["cartId"] = f"{normalized['id']}-{normalized['variant']}"
    elif variant_name:
        normalized["variantName"] = variant_name

    return normalized


def _normalize_fund_item(raw_item):
    key = str(raw_item.get('id') or '').strip()
    name = str(raw_item.get('name') or '').strip()
    if key not in FUND_ITEMS:
        key = FUND_ITEM_NAMES.get(name)
    if key not in FUND_ITEMS:
        raise OrderValidationError("建廟護持項目資料不正確，請重新整理頁面")

    item = FUND_ITEMS[key]
    return {
        "id": key,
        "name": item['name'],
        "price": item['price'],
        "qty": _to_positive_int(raw_item.get('qty'), max_value=999),
    }


def _normalize_committee_items(raw_items):
    if len(raw_items) != 1:
        raise OrderValidationError("委員會每次只能選擇一個護持項目")

    setting = db.settings.find_one({"type": "committee_quota"}) or {}
    roles = {
        role.get('name'): role
        for role in setting.get('roles', [])
        if role.get('name')
    }
    if not roles:
        raise OrderValidationError("委員會名額尚未開放")

    raw_item = raw_items[0]
    name = str(raw_item.get('name') or '').strip()
    role = roles.get(name)
    if not role:
        raise OrderValidationError("委員會護持項目資料不正確，請重新整理頁面")

    qty = _to_positive_int(raw_item.get('qty'), max_value=1)
    limit = _to_positive_int(role.get('limit'), field='名額', max_value=9999)
    price = _to_money(role.get('price'), '功德金')
    if limit <= 0:
        raise OrderValidationError(f"【{name}】已額滿")

    return [{
        "name": name,
        "price": price,
        "qty": qty,
    }], [{"name": name, "limit": limit}]


def _normalize_order_payload(data, order_type):
    raw_items = data.get('items')
    if not isinstance(raw_items, list) or not raw_items:
        raise OrderValidationError("請至少選擇一個項目")
    if len(raw_items) > 50:
        raise OrderValidationError("項目數量過多，請分批送出")

    quota_checks = []
    shipping_fee = 0

    if order_type in ('shop', 'donation'):
        product_oids = []
        for item in raw_items:
            product_oid = get_object_id(item.get('id'))
            if not product_oid:
                raise OrderValidationError("商品資料格式錯誤，請重新整理頁面")
            product_oids.append(product_oid)

        products = {
            product['_id']: product
            for product in db.products.find(
                {"_id": {"$in": list(set(product_oids))}},
                PRODUCT_PROJECTION,
            )
        }
        items = [
            _normalize_product_item(item, order_type, products.get(product_oids[index]))
            for index, item in enumerate(raw_items)
        ]
        subtotal = sum(item['price'] * item['qty'] for item in items)
        if order_type == 'shop':
            shipping_method = data.get('shippingMethod', 'home')
            if shipping_method not in ('home', '711'):
                raise OrderValidationError("配送方式不正確")
            shipping_fee = 60 if shipping_method == '711' else 120
            if shipping_method == '711' and not str(data.get('storeInfo', '')).strip():
                raise OrderValidationError("請填寫 7-11 門市資訊")
            if shipping_method == 'home' and not str(data.get('address', '')).strip():
                raise OrderValidationError("請填寫宅配地址")
    elif order_type == 'fund':
        items = [_normalize_fund_item(item) for item in raw_items]
        subtotal = sum(item['price'] * item['qty'] for item in items)
    elif order_type == 'committee':
        items, quota_checks = _normalize_committee_items(raw_items)
        subtotal = sum(item['price'] * item['qty'] for item in items)
    else:
        raise OrderValidationError("不支援的訂單類型")

    total = subtotal + shipping_fee
    if data.get('total') is not None and _to_money(data.get('total'), '訂單總額') != total:
        raise OrderValidationError("訂單金額已變動，請重新整理頁面後再送出")

    return items, total, shipping_fee, quota_checks


def _insert_order_with_quota(order, quota_checks):
    if not quota_checks:
        db.orders.insert_one(order)
        return

    def write_order(session_obj=None):
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        for check in quota_checks:
            query = {
                "orderType": "committee",
                "status": {"$in": ["paid", "pending"]},
                "items.name": check["name"],
            }
            if session_obj is not None:
                db.committee_quota_locks.update_one(
                    {"_id": check["name"]},
                    {"$set": {"updatedAt": now}},
                    upsert=True,
                    session=session_obj,
                )
                used_count = db.orders.count_documents(query, session=session_obj)
            else:
                used_count = db.orders.count_documents(query)
            if used_count >= check["limit"]:
                raise OrderValidationError(f"非常抱歉，【{check['name']}】名額已額滿")

        db.orders.insert_one(order, session=session_obj)

    client = get_client()
    if client is not None:
        try:
            with client.start_session() as session_obj:
                session_obj.with_transaction(lambda s: write_order(s))
            return
        except OrderValidationError:
            raise
        except (ConfigurationError, OperationFailure) as exc:
            message = str(exc).lower()
            if all(token not in message for token in ('transaction', 'replica set', 'sessions')):
                raise
        except PyMongoError:
            raise

    write_order()

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

    projection = {
        "customer.name": 1,
        "customer.prayer": 1,
        "items.name": 1,
        "items.qty": 1,
    }
    cursor = db.orders.find(query, projection).sort("updatedAt", -1).limit(1000)
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
@admin_required(roles=['super_admin', 'finance', 'ops', 'data'])
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
@admin_required(roles=['super_admin', 'ops', 'data'])
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
        # 加上規格名稱的判斷
        items_str = "、".join([f"{i.get('name', '')}{'['+i.get('variantName', '')+']' if i.get('variantName') else ''}x{i.get('qty', 1)}" for i in doc.get('items', [])])
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
@admin_required(roles=['super_admin', 'finance', 'ops'])
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


@orders_bp.route('/api/orders', methods=['POST'])
@user_login_required
def create_order():
    if db is None:
        return jsonify({"error": "DB Error"}), 500
    data = request.get_json() or {}
    line_id = session.get('user_line_id')

    order_type = data.get('orderType', 'shop')

    is_valid, error_msg = validate_real_name(data.get('name', '').strip())
    if not is_valid:
        return jsonify({"error": f"系統阻擋：{error_msg}"}), 400

    try:
        normalized_items, total, shipping_fee, quota_checks = _normalize_order_payload(data, order_type)
    except OrderValidationError as exc:
        return jsonify({"error": str(exc)}), 400

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
        "prayer": data.get('prayer', ''),
        "shippingMethod": data.get('shippingMethod', 'home'),
        "storeInfo": data.get('storeInfo', ''),
        "shippingFee": shipping_fee
    }

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    deadline = now + timedelta(hours=2)

    order = {
        "orderId": order_id, "orderType": order_type, "customer": customer_info,
        "items": normalized_items, "total": total, "status": "pending",
        "lineId": line_id,
        "paymentDeadline": deadline,
        "createdAt": now, "updatedAt": now
    }

    if order_type == 'donation':
        order['is_reported'] = False

    try:
        _insert_order_with_quota(order, quota_checks)
    except OrderValidationError as exc:
        return jsonify({"error": str(exc)}), 400

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
    return jsonify({"success": True, "orderId": order_id, "total": total})


@orders_bp.route('/api/orders', methods=['GET'])
@admin_required(roles=['super_admin', 'finance', 'ops', 'data'])
def get_orders():
    cursor = db.orders.find({"orderType": "shop"}).sort("createdAt", -1)
    results = []
    for doc in cursor:
        doc['_id'] = str(doc['_id'])
        doc['createdAt'] = (doc['createdAt'] + timedelta(hours=8)).strftime('%Y-%m-%d %H:%M')
        results.append(doc)
    return jsonify(results)


@orders_bp.route('/api/orders/cleanup-shipped', methods=['DELETE'])
@admin_required(roles=['super_admin', 'ops'])
def cleanup_shipped_orders():
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=14)
    result = db.orders.delete_many({"status": "shipped", "shippedAt": {"$lt": cutoff}})
    return jsonify({"success": True, "count": result.deleted_count})


@orders_bp.route('/api/orders/<oid>/confirm', methods=['PUT'])
@admin_required(roles=['super_admin', 'finance'])
def confirm_order_payment(oid):
    oid_obj = get_object_id(oid)
    if not oid_obj:
        return jsonify({"error": "無效的 ID 格式"}), 400

    order = db.orders.find_one({'_id': oid_obj})
    if not order:
        return jsonify({"error": "No order"}), 404

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    admin_user = session.get('admin_username', 'admin') # 取得當下操作員

    # ✅ 變數都準備好後，才執行更新
    db.orders.update_one(
        {'_id': oid_obj}, 
        {'$set': {'status': 'paid', 'updatedAt': now, 'paidAt': now, 'paidBy': admin_user}}
    )

    write_audit_log(admin_user, '確認收款', order.get('orderId', oid), f"${order.get('total', 0)}")
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
@admin_required(roles=['super_admin', 'finance', 'ops'])
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
@admin_required(roles=['super_admin'])
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
@admin_required(roles=['super_admin', 'ops'])
def ship_order(oid):
    oid_obj = get_object_id(oid)
    if not oid_obj:
        return jsonify({"error": "無效的 ID 格式"}), 400

    data = request.get_json() or {}
    tracking_num = data.get('trackingNumber', '').strip()

    order = db.orders.find_one({'_id': oid_obj})
    if not order:
        return jsonify({"error": "No order"}), 404

    # 準備好所有變數
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    admin_user = session.get('admin_username', 'admin') # 取得當下操作員

    # ✅ 變數都準備好後，才執行更新
    db.orders.update_one({'_id': oid_obj}, {'$set': {
        'status': 'shipped', 
        'updatedAt': now, 
        'shippedAt': now, 
        'trackingNumber': tracking_num, 
        'shippedBy': admin_user
    }})

    write_audit_log(admin_user, '出貨', order.get('orderId', oid), tracking_num)

    # 寄信通知
    cust = order['customer']
    email_subject = f"【承天中承府】訂單出貨通知 ({order['orderId']})"
    email_html = generate_shop_email_html(order, 'shipped', tracking_num, db=db)
    send_email(cust.get('email'), email_subject, email_html,
               current_app.config['SENDGRID_API_KEY'], current_app.config['MAIL_SENDER'],
               is_html=True)
    return jsonify({"success": True})
