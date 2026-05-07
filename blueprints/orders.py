import io
from collections import defaultdict
from datetime import datetime, timedelta
from flask import Blueprint, jsonify, request, session, Response
from pymongo.errors import DuplicateKeyError

from database import db, write_audit_log
from extensions import limiter
from repositories.committee_quota_repository import (
    release_committee_quota_for_order,
    reserve_committee_quota,
)
from schemas.orders import OrderCreateSchema, ResendEmailSchema, ShipOrderSchema
from tasks.notifications import (
    delay_notification,
    send_order_cancelled_email,
    send_order_resend_email,
)
from services.order_service import (
    confirm_payment as confirm_payment_service,
    list_admin_donations,
    list_shop_orders,
    mark_shipped as mark_shipped_service,
    queue_order_created_email,
    queue_order_shipped_email,
    queue_payment_confirmed_email,
)
from services.sequence_service import (
    generate_order_id,
    write_with_unique_id_retry,
)
from utils.business_rules import (
    ORDER_PAYMENT_DEADLINE_HOURS,
    SHIPPED_ORDER_RETENTION_DAYS,
    UNPAID_ORDER_GRACE_HOURS,
    get_shop_shipping_fee,
)
from utils.decorators import admin_required, user_login_required
from utils.errors import ServiceUnavailableError, ValidationError
from utils.helpers import get_object_id, validate_real_name, mask_name
from utils.pagination import page_response, parse_pagination
from utils.security import as_string, get_json_object
from utils.timezone import utc_now
from utils.validation import validate_payload

orders_bp = Blueprint('orders', __name__)

# 註：/api/public/committee-status 改由 main.py 提供（包含 price 欄位）


class OrderValidationError(ValidationError):
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
    if not isinstance(raw_item, dict):
        raise OrderValidationError("商品資料格式錯誤，請重新整理頁面")
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
    requested_variant = as_string(raw_item.get('variantName') or raw_item.get('variant'))
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
        normalized["variant"] = variant_name or as_string(raw_item.get('variant')) or '標準'
        normalized["cartId"] = f"{normalized['id']}-{normalized['variant']}"
    elif variant_name:
        normalized["variantName"] = variant_name

    return normalized


def _normalize_fund_item(raw_item):
    if not isinstance(raw_item, dict):
        raise OrderValidationError("建廟護持項目資料不正確，請重新整理頁面")
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
    if not isinstance(raw_item, dict):
        raise OrderValidationError("委員會護持項目資料不正確，請重新整理頁面")
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
    }], [{"name": name, "limit": limit, "qty": qty}]


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
            shipping_method = as_string(data.get('shippingMethod'), 'home')
            if shipping_method not in ('home', '711'):
                raise OrderValidationError("配送方式不正確")
            shipping_fee = get_shop_shipping_fee(shipping_method)
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

    reserved = []
    try:
        for check in quota_checks:
            quantity = check.get("qty", 1)
            if not reserve_committee_quota(check["name"], check["limit"], quantity):
                raise OrderValidationError(f"非常抱歉，【{check['name']}】名額已額滿")
            reserved.append(check)

        db.orders.insert_one(order)
    except DuplicateKeyError:
        # insert 撞到唯一鍵時會由外層 retry 重新取單號；先補回本次已扣名額。
        for check in reserved:
            release_committee_quota_for_order({
                "orderType": "committee",
                "status": "pending",
                "items": [{"name": check["name"], "qty": check.get("qty", 1)}],
            })
        raise
    except Exception:
        for check in reserved:
            release_committee_quota_for_order({
                "orderType": "committee",
                "status": "pending",
                "items": [{"name": check["name"], "qty": check.get("qty", 1)}],
            })
        raise


@orders_bp.route('/api/donations/public', methods=['GET'])
def get_public_donations():
    if db is None:
        return jsonify([]), 500

    target_type = as_string(request.args.get('type'), 'donation')
    if target_type not in ('all', 'donation', 'fund', 'committee'):
        return jsonify({"error": "不支援的查詢類型"}), 400
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
    type_filter = as_string(request.args.get('type')).strip()
    status_filter = as_string(request.args.get('status')).strip()
    report_filter = as_string(request.args.get('reported')).strip()
    if type_filter and type_filter not in ('donation', 'fund', 'committee'):
        return jsonify({"error": "不支援的查詢類型"}), 400
    if status_filter and status_filter not in ('pending', 'paid', 'shipped', 'cancelled'):
        return jsonify({"error": "不支援的狀態"}), 400

    query = {}
    if type_filter:
        query['orderType'] = type_filter
    else:
        query['orderType'] = {"$in": ["donation", "fund", "committee"]}

    if status_filter:
        query['status'] = status_filter

    if type_filter == 'donation' and report_filter:
        query['is_reported'] = (report_filter == '1')

    start_str = as_string(request.args.get('start')).strip()
    end_str = as_string(request.args.get('end')).strip()
    if start_str and end_str:
        try:
            start_date = datetime.strptime(start_str, '%Y-%m-%d')
            end_date = datetime.strptime(end_str, '%Y-%m-%d') + timedelta(days=1)
            query["createdAt"] = {"$gte": start_date, "$lt": end_date}
        except Exception:
            pass

    pagination = parse_pagination(request.args, default_per_page=50, max_per_page=100)
    results, total = list_admin_donations(query, pagination)
    return jsonify(page_response(results, total, pagination))


@orders_bp.route('/api/donations/export-txt', methods=['POST'])
@admin_required(roles=['super_admin', 'ops', 'data'])
def export_donations_txt():
    data = get_json_object()
    start_str = as_string(data.get('start')).strip()
    end_str = as_string(data.get('end')).strip()

    order_type = as_string(data.get('type'), 'donation')
    if order_type not in ('donation', 'fund', 'committee'):
        return jsonify({"error": "不支援的查詢類型"}), 400
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
    cutoff = utc_now() - timedelta(hours=UNPAID_ORDER_GRACE_HOURS)
    query = {"status": "pending", "createdAt": {"$lt": cutoff}}
    orders_to_delete = list(db.orders.find(query))
    for order in orders_to_delete:
        if order.get('customer', {}).get('email'):
            delay_notification(send_order_cancelled_email, {
                "email": order['customer']['email'],
                "orderId": order.get('orderId', ''),
                "customerName": order.get('customer', {}).get('name', '信徒'),
                "reason": "expired",
            })

    result = db.orders.delete_many(query)
    if result.deleted_count:
        for order in orders_to_delete:
            release_committee_quota_for_order(order)
    return jsonify({"success": True, "count": result.deleted_count})


@orders_bp.route('/api/orders', methods=['POST'])
@limiter.limit("30 per hour")
@user_login_required
def create_order():
    if db is None:
        return jsonify({"error": "DB Error"}), 500
    payload = validate_payload(OrderCreateSchema, get_json_object())
    data = payload.model_dump(exclude_none=True)
    line_id = session.get('user_line_id')

    order_type = as_string(data.get('orderType'), 'shop')

    is_valid, error_msg = validate_real_name(as_string(data.get('name')).strip())
    if not is_valid:
        return jsonify({"error": f"系統阻擋：{error_msg}"}), 400

    normalized_items, total, shipping_fee, quota_checks = _normalize_order_payload(data, order_type)

    customer_info = {
        "name": as_string(data.get('name')).strip(),
        "phone": as_string(data.get('phone')).strip(),
        "email": as_string(data.get('email')).strip(),
        "address": as_string(data.get('address')).strip(),
        "last5": as_string(data.get('last5')).strip(),
        "lunarBirthday": as_string(data.get('lunarBirthday')).strip(),
        "prayer": as_string(data.get('prayer')).strip(),
        "shippingMethod": as_string(data.get('shippingMethod'), 'home'),
        "storeInfo": as_string(data.get('storeInfo')).strip(),
        "shippingFee": shipping_fee
    }

    now = utc_now()
    deadline = now + timedelta(hours=ORDER_PAYMENT_DEADLINE_HOURS)

    order_template = {
        "orderType": order_type, "customer": customer_info,
        "items": normalized_items, "total": total, "status": "pending",
        "lineId": line_id,
        "paymentDeadline": deadline,
        "createdAt": now, "updatedAt": now
    }

    if order_type == 'donation':
        order_template['is_reported'] = False

    def write_order(candidate_order_id):
        # 每次 retry 都用新的 dict，避免 PyMongo 在 insert 時加上的 _id 汙染下一次嘗試。
        order = {**order_template, "orderId": candidate_order_id}
        _insert_order_with_quota(order, quota_checks)
        return order

    try:
        order_id, order = write_with_unique_id_retry(
            lambda: generate_order_id(order_type),
            write_order,
            label="order",
        )
    except DuplicateKeyError as exc:
        raise ServiceUnavailableError("訂單編號產生重複，請稍後再試") from exc

    queue_order_created_email(order)
    return jsonify({"success": True, "orderId": order_id, "total": total})


@orders_bp.route('/api/orders', methods=['GET'])
@admin_required(roles=['super_admin', 'finance', 'ops', 'data'])
def get_orders():
    pagination = parse_pagination(request.args, default_per_page=50, max_per_page=100)
    results, total = list_shop_orders(pagination)
    return jsonify(page_response(results, total, pagination))


@orders_bp.route('/api/orders/cleanup-shipped', methods=['DELETE'])
@admin_required(roles=['super_admin', 'ops'])
def cleanup_shipped_orders():
    cutoff = utc_now() - timedelta(days=SHIPPED_ORDER_RETENTION_DAYS)
    result = db.orders.delete_many({"status": "shipped", "shippedAt": {"$lt": cutoff}})
    return jsonify({"success": True, "count": result.deleted_count})


@orders_bp.route('/api/orders/<oid>/confirm', methods=['PUT'])
@admin_required(roles=['super_admin', 'finance'])
def confirm_order_payment(oid):
    admin_user = session.get('admin_username', 'admin') # 取得當下操作員
    order = confirm_payment_service(oid, admin_user)
    queue_payment_confirmed_email(order)
    return jsonify({"success": True})

@orders_bp.route('/api/orders/<oid>/resend-email', methods=['POST'])
@admin_required(roles=['super_admin', 'finance', 'ops'])
def resend_order_email(oid):
    oid_obj = get_object_id(oid)
    if not oid_obj:
        return jsonify({"error": "無效的 ID 格式"}), 400

    payload = validate_payload(ResendEmailSchema, get_json_object())
    new_email = payload.email.strip()
    order = db.orders.find_one({'_id': oid_obj})
    if not order:
        return jsonify({"error": "No order"}), 404

    target_email = order.get('customer', {}).get('email')
    if new_email and new_email != target_email:
        db.orders.update_one({'_id': oid_obj}, {'$set': {'customer.email': new_email}})

    delay_notification(send_order_resend_email, order.get('orderId'))
    return jsonify({"success": True})


@orders_bp.route('/api/orders/<oid>', methods=['DELETE'])
@admin_required(roles=['super_admin'])
def delete_order(oid):
    oid_obj = get_object_id(oid)
    if not oid_obj:
        return jsonify({"error": "無效的 ID 格式"}), 400

    order = db.orders.find_one({'_id': oid_obj})
    if order and order.get('customer', {}).get('email'):
        delay_notification(send_order_cancelled_email, {
            "email": order['customer']['email'],
            "orderId": order.get('orderId', ''),
            "customerName": order.get('customer', {}).get('name', '信徒'),
            "reason": "manual",
        })

    write_audit_log(session.get('admin_username', 'admin'), '刪除訂單', order.get('orderId', oid) if order else oid)
    result = db.orders.delete_one({'_id': oid_obj})
    if result.deleted_count:
        release_committee_quota_for_order(order)
    return jsonify({"success": True})

@orders_bp.route('/api/orders/<oid>/ship', methods=['PUT'])
@admin_required(roles=['super_admin', 'ops'])
def ship_order(oid):
    payload = validate_payload(ShipOrderSchema, get_json_object())
    tracking_num = payload.trackingNumber.strip()
    admin_user = session.get('admin_username', 'admin') # 取得當下操作員
    order = mark_shipped_service(oid, tracking_num, admin_user)
    queue_order_shipped_email(order, tracking_num)
    return jsonify({"success": True})
