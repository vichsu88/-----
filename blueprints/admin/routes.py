import csv
import io
import logging
from datetime import datetime, timedelta

from bson import ObjectId
from flask import Blueprint, Response, jsonify, request, session
from pymongo import UpdateOne
from pymongo.errors import DuplicateKeyError
from werkzeug.security import generate_password_hash

import database
from repositories.committee_quota_repository import (
    release_committee_quota_for_order,
    sync_committee_quota_usages,
)
from utils.decorators import admin_required
from utils.helpers import get_object_id
from utils.security import as_string, get_json_object, get_json_value, safe_regex_contains
from utils.timezone import format_taipei, taipei_date_range_query, taipei_now, utc_now
# 記得在檔案最上方引入我們剛剛寫的 Service
from services.history_service import fetch_history_data

admin_bp = Blueprint('admin', __name__)
logger = logging.getLogger(__name__)

# 過渡期讓既有 blueprints/admin.py 可以逐步拆出 blueprints/admin/*.py 子模組。


# =========================================================
# 工具函式
# =========================================================

def _serialize_doc(obj):
    """強化版遞迴序列化：把所有不認識的物件強制轉字串"""
    if isinstance(obj, dict):
        return {k: _serialize_doc(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_serialize_doc(v) for v in obj]
    if isinstance(obj, ObjectId):
        return str(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
    # 🛡️ 終極防線：如果不是基本 JSON 支援的型別，一律暴力轉成字串！
    # 這樣 jsonify 絕對不可能再因為型別錯誤而崩潰
    if not isinstance(obj, (int, float, str, bool, type(None))):
        return str(obj)
    return obj


def _safe_csv_cell(value):
    if value is None:
        text = ''
    else:
        text = str(value)
    if text.lstrip()[:1] in ('=', '+', '-', '@'):
        return "'" + text
    return text


def _tw_time(dt):
    """UTC datetime → 台灣時間字串（相容 legacy 字串資料）"""
    return format_taipei(dt)


def _get_sort_ts(dt):
    """取得排序用 timestamp (float)，安全處理各種型別"""
    if not dt:
        return 0
    if isinstance(dt, (int, float)):
        return float(dt)
    if isinstance(dt, datetime):
        return dt.timestamp()
    if isinstance(dt, str):
        for fmt in ('%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%d'):
            try:
                return datetime.strptime(dt[:len(fmt.replace('%', 'X'))], fmt).timestamp()
            except Exception:
                continue
    return 0


_TYPE_LABELS = {
    'shop': '🛍️ 結緣品',
    'donation': '🕯️ 捐香',
    'fund': '🏗️ 建廟基金',
    'committee': '🏛️ 委員會',
    'feedback': '💬 回饋'
}

VALID_ORDER_TYPES = {'shop', 'donation', 'fund', 'committee'}
VALID_HISTORY_TYPES = VALID_ORDER_TYPES | {'feedback'}
VALID_STATUSES = {'pending', 'paid', 'shipped', 'approved', 'sent', 'cancelled'}
MIN_ADMIN_PASSWORD_LENGTH = 10
RECEIPT_BLOCKED_FIELDS = {
    '_id', 'lineId', 'orderId', 'feedbackId', 'orderType',
    'createdAt', 'updatedAt',
    'paidAt', 'paidBy', 'shippedAt', 'shippedBy',
    'approvedAt', 'approvedBy', 'sentAt', 'sentBy',
    'reportedAt', 'reportedBy',
}
ORDER_RECEIPT_ALLOWED_FIELDS = {
    'customer', 'total', 'trackingNumber',
    'is_reported', 'memo', 'notes',
}
FEEDBACK_RECEIPT_ALLOWED_FIELDS = {
    'nickname', 'category', 'content', 'realName', 'phone',
    'address', 'email', 'lunarBirthday', 'trackingNumber',
    'isMarked', 'memo', 'notes',
}


def _clean_bank_info(value):
    if not isinstance(value, dict):
        return {}
    return {
        "bankCode": as_string(value.get('bankCode')).strip(),
        "bankName": as_string(value.get('bankName')).strip(),
        "account": as_string(value.get('account')).strip(),
    }


def _clean_committee_roles(value):
    if not isinstance(value, list):
        return []
    roles = []
    for item in value[:50]:
        if not isinstance(item, dict):
            continue
        try:
            limit = int(item.get('limit', 0))
            price = int(item.get('price', 0))
        except (TypeError, ValueError):
            continue
        roles.append({
            "name": as_string(item.get('name')).strip(),
            "limit": max(0, limit),
            "price": max(0, price),
        })
    return [role for role in roles if role["name"]]


def _safe_update_value(value):
    if isinstance(value, dict):
        cleaned = {}
        for key, child in value.items():
            if not isinstance(key, str) or not key or key.startswith('$') or '.' in key:
                continue
            if key in RECEIPT_BLOCKED_FIELDS:
                continue
            cleaned[key] = _safe_update_value(child)
        return cleaned
    if isinstance(value, list):
        return [_safe_update_value(item) for item in value]
    return value


def _clean_receipt_update(value, allowed_fields):
    if not isinstance(value, dict):
        return {}, []

    cleaned = {}
    ignored = []
    for key, child in value.items():
        if (
            key in RECEIPT_BLOCKED_FIELDS
            or key not in allowed_fields
            or key.startswith('$')
            or '.' in key
        ):
            ignored.append(key)
            continue
        cleaned[key] = _safe_update_value(child)
    return cleaned, sorted(set(ignored))


# =========================================================
# Module 1: 💰 財務稽核中樞 (Finance Hub)
# Finance routes 已拆至 blueprints/admin/finance.py，保留區塊標記方便後續搬遷。
# =========================================================

# =========================================================
# Module 2: 🛠️ 站務作業中樞 (Operations Center)
# =========================================================

@admin_bp.route('/api/admin/ops/print-queue')
@admin_required(roles=['super_admin', 'ops'])
def get_print_queue():
    """文書列印排程：已付款但未稟告的捐香訂單"""
    if database.db is None:
        return jsonify([])

    cursor = database.db.orders.find({
        "status": "paid",
        "orderType": "donation",
        "is_reported": {"$ne": True}
    }).sort("paidAt", 1)

    results = []
    for doc in cursor:
        doc['_id'] = str(doc['_id'])
        doc['paidAt'] = _tw_time(doc.get('paidAt'))
        doc['createdAt'] = _tw_time(doc.get('createdAt'))
        results.append(doc)
    return jsonify(results)


@admin_bp.route('/api/admin/ops/ship-queue')
@admin_required(roles=['super_admin', 'ops'])
def get_ship_queue():
    """出貨物流排程：已付款的結緣品訂單"""
    if database.db is None:
        return jsonify([])

    cursor = database.db.orders.find({
        "status": "paid",
        "orderType": "shop"
    }).sort("paidAt", 1)

    results = []
    for doc in cursor:
        doc['_id'] = str(doc['_id'])
        doc['paidAt'] = _tw_time(doc.get('paidAt'))
        doc['createdAt'] = _tw_time(doc.get('createdAt'))
        results.append(doc)
    return jsonify(results)


@admin_bp.route('/api/admin/ops/shipped-list')
@admin_required(roles=['super_admin', 'ops'])
def get_shipped_list():
    """已出貨歷史 (最近 30 天) — 保留 API 供歷史總表使用"""
    if database.db is None:
        return jsonify([])

    cutoff = utc_now() - timedelta(days=30)
    cursor = database.db.orders.find({
        "status": "shipped",
        "shippedAt": {"$gte": cutoff}
    }).sort("shippedAt", -1)

    results = []
    for doc in cursor:
        doc['_id'] = str(doc['_id'])
        doc['shippedAt'] = _tw_time(doc.get('shippedAt'))
        doc['createdAt'] = _tw_time(doc.get('createdAt'))
        results.append(doc)
    return jsonify(results)


# =========================================================
# Module 3: 🗂️ 綜合資料總管與 CRM (Master Data)
# 整併 orders + feedback 到單一歷史總表
# =========================================================


@admin_bp.route('/api/admin/data/history')
@admin_required(roles=['super_admin', 'data', 'finance'])
def get_data_history():
    """萬用歷史總表：整併 orders + feedback，支援複合篩選 (已優化為 database.db 聚合查詢)"""
    order_type = as_string(request.args.get('type')).strip()
    order_id = as_string(request.args.get('orderId')).strip()
    name = as_string(request.args.get('name')).strip()
    status = as_string(request.args.get('status')).strip()
    start = as_string(request.args.get('start')).strip()
    end = as_string(request.args.get('end')).strip()

    if order_type and order_type not in VALID_HISTORY_TYPES:
        return jsonify({"error": "不支援的查詢類型"}), 400
    if status and status not in VALID_STATUSES:
        return jsonify({"error": "不支援的狀態"}), 400

    try:
        page = max(int(request.args.get('page', 1)), 1)
        per_page = min(max(int(request.args.get('per_page', 50)), 1), 100)
    except (TypeError, ValueError):
        page = 1
        per_page = 50

    # 核心邏輯交給 Service 處理
    results, total = fetch_history_data(
        order_type, order_id, name, status, start, end, page, per_page
    )

    return jsonify({
        "results": results, 
        "total": total, 
        "page": page, 
        "per_page": per_page
    })
@admin_bp.route('/api/donations/mark-reported', methods=['POST'])
@admin_required(roles=['super_admin', 'ops'])
def mark_donations_reported():
    """批次標記捐香訂單為已稟告"""
    if database.db is None:
        return jsonify({"error": "資料庫未連線"}), 500

    data = get_json_object()
    if not data or 'ids' not in data:
        return jsonify({"error": "未提供要標記的資料"}), 400

    ids = data.get('ids', [])
    if not isinstance(ids, list) or not ids:
        return jsonify({"error": "未提供訂單 ID"}), 400

    # 將字串 ID 轉換為 MongoDB 的 ObjectId
    object_ids = []
    for id_str in ids[:500]:
        oid = get_object_id(id_str)
        if oid:
            object_ids.append(oid)

    if not object_ids:
        return jsonify({"error": "無效的訂單 ID"}), 400

    admin_name = session.get('admin_username', 'admin')
    now = utc_now()

    # 執行批次更新
    result = database.db.orders.update_many(
        {"_id": {"$in": object_ids}},
        {"$set": {
            "is_reported": True,
            "reportedAt": now,
            "reportedBy": admin_name
        }}
    )

    database.write_audit_log(admin_name, '批次標記已稟告', f'共 {result.modified_count} 筆')
    return jsonify({"success": True, "message": f"已成功標記 {result.modified_count} 筆訂單為已稟告"})
# =========================================================
# 委員會名額動態管理 (CMS)
# =========================================================


@admin_bp.route('/api/admin/data/export-csv')
@admin_required(roles=['super_admin', 'data', 'finance'])
def export_data_csv():
    """匯出歷史資料為 CSV (所見即所得)"""
    if database.db is None:
        return jsonify({"error": "資料庫未連線"}), 500

    query = {}
    order_type = as_string(request.args.get('type')).strip()
    if order_type:
        if order_type not in VALID_ORDER_TYPES:
            return jsonify({"error": "不支援的查詢類型"}), 400
        query['orderType'] = order_type
    status = as_string(request.args.get('status')).strip()
    if status:
        if status not in VALID_STATUSES:
            return jsonify({"error": "不支援的狀態"}), 400
        query['status'] = status
    name = as_string(request.args.get('name')).strip()
    if name:
        query['customer.name'] = {"$regex": safe_regex_contains(name)}
    start = as_string(request.args.get('start')).strip()
    end = as_string(request.args.get('end')).strip()
    if start and end:
        try:
            query['createdAt'] = taipei_date_range_query(start, end)
        except ValueError:
            pass

    cursor = database.db.orders.find(query).sort("createdAt", -1).limit(5000)

    si = io.StringIO()
    si.write('\ufeff')  # BOM for Excel
    writer = csv.writer(si, lineterminator='\n')
    writer.writerow(['單號', '類型', '狀態', '姓名', '電話', 'Email', '地址', '項目', '金額', '建立日期', '付款日期'])

    for doc in cursor:
        cust = doc.get('customer', {})
        # 加上規格名稱的判斷
        items_str = '；'.join([
            f"{i.get('name', '')}{'('+i.get('variantName', '')+')' if i.get('variantName') else ''}x{i.get('qty', 1)}"
            for i in doc.get('items', [])
        ])
        row = [
            doc.get('orderId', ''),
            _TYPE_LABELS.get(doc.get('orderType', ''), ''),
            doc.get('status', ''),
            cust.get('name', ''),
            cust.get('phone', ''),
            cust.get('email', ''),
            cust.get('address', ''),
            items_str,
            str(doc.get('total', 0)),
            _tw_time(doc.get('createdAt')),
            _tw_time(doc.get('paidAt'))
        ]
        writer.writerow([_safe_csv_cell(value) for value in row])

    return Response(
        si.getvalue(),
        mimetype='text/csv; charset=utf-8',
        headers={"Content-Disposition": f"attachment; filename=export_{taipei_now().strftime('%Y%m%d')}.csv"}
    )


@admin_bp.route('/api/admin/data/members')
@admin_required(roles=['super_admin', 'data', 'finance'])
def get_data_members():
    """會員資料庫 — 效能極致優化版 (解決 OOM 問題)"""
    if database.db is None:
        return jsonify([])

    try:
        projection = {
            "displayName": 1,
            "lineId": 1,
            "lastLoginAt": 1,
            "createdAt": 1,
            "pictureUrl": 1,
            "realName": 1,
        }
        users = list(database.db.users.find({}, projection).sort("lastLoginAt", -1).limit(3000))
        line_ids = [user.get("lineId") for user in users if user.get("lineId")]

        order_counts = {}
        feedback_counts = {}
        if line_ids:
            order_pipeline = [
                {"$match": {"lineId": {"$in": line_ids}}},
                {"$group": {"_id": "$lineId", "count": {"$sum": 1}}},
            ]
            feedback_pipeline = [
                {"$match": {"lineId": {"$in": line_ids}}},
                {"$group": {"_id": "$lineId", "count": {"$sum": 1}}},
            ]
            order_counts = {
                item["_id"]: item["count"]
                for item in database.db.orders.aggregate(order_pipeline)
                if item.get("_id")
            }
            feedback_counts = {
                item["_id"]: item["count"]
                for item in database.db.feedback.aggregate(feedback_pipeline)
                if item.get("_id")
            }

        results = []
        for user in users:
            user['_id'] = str(user['_id'])
            user['lastLoginAt'] = _tw_time(user.get('lastLoginAt'))
            user['createdAt'] = _tw_time(user.get('createdAt'))
            line_id = user.get('lineId')
            user['orderCount'] = order_counts.get(line_id, 0)
            user['feedbackCount'] = feedback_counts.get(line_id, 0)
            results.append(_serialize_doc(user))

        return jsonify(results)

    except Exception as e:
        logger.exception("Member list failed", extra={"event": "admin_member_list_failed"})
        return jsonify({"error": f"資料庫查詢錯誤: {str(e)}"}), 500


@admin_bp.route('/api/admin/data/member/<line_id>/history')
@admin_required(roles=['super_admin', 'data', 'finance'])
def get_member_history(line_id):
    """會員互動歷程：該會員所有 orders + feedback"""
    if database.db is None:
        return jsonify({"orders": [], "feedback": []})

    orders = []
    for doc in database.db.orders.find({"lineId": line_id}).sort("createdAt", -1).limit(200):
        doc['_id'] = str(doc['_id'])
        doc['createdAt'] = _tw_time(doc.get('createdAt'))
        doc['source_label'] = _TYPE_LABELS.get(doc.get('orderType', ''), '未知')
        if doc.get('paidAt'):
            doc['paidAt'] = _tw_time(doc['paidAt'])
            doc['paidBy'] = doc.get('paidBy', '') # 新增這行
        orders.append(doc)

    feedback = []
    for doc in database.db.feedback.find({"lineId": line_id}).sort("createdAt", -1).limit(200):
        doc['_id'] = str(doc['_id'])
        doc['createdAt'] = _tw_time(doc.get('createdAt'))
        if doc.get('approvedAt'):
            doc['approvedAt'] = _tw_time(doc['approvedAt'])
        if doc.get('sentAt'):
            doc['sentAt'] = _tw_time(doc['sentAt'])
        feedback.append(doc)

    return jsonify({
        "orders": _serialize_doc(orders),
        "feedback": _serialize_doc(feedback)
    })


# =========================================================
# Module 5: ⚙️ 系統與權限管理 (System & RBAC — 陣列式權限)
# =========================================================

@admin_bp.route('/api/admin/system/users', methods=['GET'])
@admin_required(roles=['super_admin'])
def list_admin_users():
    """列出所有管理員帳號 (不含密碼)"""
    if database.db is None:
        return jsonify([])

    cursor = database.db.admin_users.find({}, {"password_hash": 0}).sort("createdAt", -1)
    results = []
    for user in cursor:
        user['_id'] = str(user['_id'])
        user['createdAt'] = _tw_time(user.get('createdAt'))
        # 向下相容：若無 permissions 欄位，從 role 推導
        if 'permissions' not in user:
            legacy_role = user.get('role', 'ops')
            user['permissions'] = ['super_admin'] if legacy_role == 'super_admin' else [legacy_role]
        results.append(user)
    return jsonify(results)


@admin_bp.route('/api/admin/system/users', methods=['POST'])
@admin_required(roles=['super_admin'])
def create_admin_user():
    """建立新管理員帳號 — 接收陣列式權限"""
    data = get_json_object()
    username = as_string(data.get('username')).strip()
    password = as_string(data.get('password')).strip()
    permissions = data.get('permissions', [])

    # 向下相容：若前端仍傳 role 字串
    if not permissions and data.get('role'):
        permissions = [as_string(data.get('role')).strip()]
    if isinstance(permissions, list):
        permissions = [as_string(p).strip() for p in permissions if as_string(p).strip()]
    else:
        permissions = []

    if not username or not password:
        return jsonify({"error": "帳號和密碼不可為空"}), 400

    if len(password) < MIN_ADMIN_PASSWORD_LENGTH:
        return jsonify({"error": f"管理員密碼至少需要 {MIN_ADMIN_PASSWORD_LENGTH} 個字元"}), 400

    valid_perms = ['super_admin', 'finance', 'ops', 'data', 'cms']
    for p in permissions:
        if p not in valid_perms:
            return jsonify({"error": f"無效的權限: {p}"}), 400

    if not permissions:
        return jsonify({"error": "請至少選擇一個權限"}), 400

    if database.db.admin_users.find_one({"username": username}):
        return jsonify({"error": "此帳號已存在"}), 400

    try:
        database.db.admin_users.insert_one({
            "username": username,
            "password_hash": generate_password_hash(password),
            "permissions": permissions,
            "role": 'super_admin' if 'super_admin' in permissions else permissions[0],
            "createdAt": utc_now()
        })
    except DuplicateKeyError:
        return jsonify({"error": "帳號名稱已被使用"}), 400

    admin_name = session.get('admin_username', 'admin')
    database.write_audit_log(admin_name, '新增管理員帳號', username, f'權限: {", ".join(permissions)}')
    return jsonify({"success": True, "message": f"已建立帳號 {username}"})


@admin_bp.route('/api/admin/system/users/<uid>', methods=['DELETE'])
@admin_required(roles=['super_admin'])
def delete_admin_user(uid):
    """刪除管理員帳號"""
    oid = get_object_id(uid)
    if not oid:
        return jsonify({"error": "無效的 ID"}), 400

    user = database.db.admin_users.find_one({"_id": oid})
    if not user:
        return jsonify({"error": "帳號不存在"}), 404

    database.db.admin_users.delete_one({"_id": oid})

    admin_name = session.get('admin_username', 'admin')
    database.write_audit_log(admin_name, '刪除管理員帳號', user.get('username', ''))
    return jsonify({"success": True})


@admin_bp.route('/api/admin/system/audit-log')
@admin_required(roles=['super_admin'])
def get_audit_log():
    """操作日誌查詢"""
    if database.db is None:
        return jsonify([])

    try:
        limit = min(max(int(request.args.get('limit', 200)), 1), 500)
    except (TypeError, ValueError):
        limit = 200
    cursor = database.db.audit_log.find({}).sort("timestamp", -1).limit(limit)

    results = []
    for doc in cursor:
        doc['_id'] = str(doc['_id'])
        doc['timestamp'] = _tw_time(doc.get('timestamp'))
        results.append(doc)
    return jsonify(results)


# =========================================================
# 共用：銀行設定、萬能單據 CRUD、除錯
# =========================================================

@admin_bp.route('/api/settings/bank', methods=['GET', 'POST'])
@admin_required(roles=['super_admin', 'finance'])
def handle_bank_settings():
    if request.method == 'GET':
        fund_set = database.db.settings.find_one({"type": "bank_info"}) or {}
        shop_set = database.db.settings.find_one({"type": "bank_info_shop"}) or {}

        return jsonify({
            "fund": {
                "bankCode": fund_set.get('bankCode', ''),
                "bankName": fund_set.get('bankName', ''),
                "account": fund_set.get('account', '')
            },
            "shop": {
                "bankCode": shop_set.get('bankCode', ''),
                "bankName": shop_set.get('bankName', ''),
                "account": shop_set.get('account', '')
            }
        })
    else:
        data = get_json_object()
        if 'fund' in data:
            fund_data = _clean_bank_info(data.get('fund'))
            database.db.settings.update_one(
                {"type": "bank_info"},
                {"$set": fund_data},
                upsert=True
            )
        if 'shop' in data:
            shop_data = _clean_bank_info(data.get('shop'))
            database.db.settings.update_one(
                {"type": "bank_info_shop"},
                {"$set": shop_data},
                upsert=True
            )
        database.write_audit_log(session.get('admin_username', 'admin'), '更新匯款帳號設定')
        return jsonify({"success": True})


@admin_bp.route('/api/public/bank-info', methods=['GET'])
def get_public_bank_info():
    usage = as_string(request.args.get('type'), 'shop')
    if usage not in ('fund', 'shop'):
        usage = 'shop'
    setting_key = "bank_info" if usage == 'fund' else "bank_info_shop"

    defaults = {
        'fund': {'code': '103', 'name': '新光銀行', 'account': '0666-50-971133-3'},
        'shop': {'code': '808', 'name': '玉山銀行', 'account': '尚未設定'}
    }

    settings = {}
    if database.db is not None:
        settings = database.db.settings.find_one({"type": setting_key}) or {}

    return jsonify({
        "bankCode": settings.get('bankCode', defaults[usage]['code']),
        "bankName": settings.get('bankName', defaults[usage]['name']),
        "account": settings.get('account', defaults[usage]['account'])
    })


@admin_bp.route('/api/admin/receipt/<receipt_id>', methods=['GET'])
@admin_required(roles=['super_admin', 'finance', 'ops', 'data'])
def query_receipt(receipt_id):
    """萬能單據查詢"""
    if database.db is None:
        return jsonify({"error": "資料庫未連線"}), 500

    clean_id = receipt_id.strip().upper()

    if clean_id.startswith('FB'):
        doc = database.db.feedback.find_one({"feedbackId": clean_id})
    elif clean_id.startswith(('ORD', 'DON', 'FND', 'COM')):
        doc = database.db.orders.find_one({"orderId": clean_id})
    else:
        return jsonify({"error": f"無法識別的單號格式：{clean_id}"}), 400

    if not doc:
        return jsonify({"error": f"找不到單號：{clean_id}"}), 404

    return jsonify(_serialize_doc(doc))


@admin_bp.route('/api/admin/receipt/<receipt_id>', methods=['PUT'])
@admin_required(roles=['super_admin'])
def update_receipt(receipt_id):
    """萬能單據修改"""
    if database.db is None:
        return jsonify({"error": "資料庫未連線"}), 500

    clean_id = receipt_id.strip().upper()
    payload = get_json_object()

    if clean_id.startswith('FB'):
        update_data, ignored_fields = _clean_receipt_update(payload, FEEDBACK_RECEIPT_ALLOWED_FIELDS)
        if not update_data:
            return jsonify({"error": "沒有可更新的合法欄位", "ignoredFields": ignored_fields}), 400
        result = database.db.feedback.update_one({"feedbackId": clean_id}, {"$set": update_data})
    elif clean_id.startswith(('ORD', 'DON', 'FND', 'COM')):
        update_data, ignored_fields = _clean_receipt_update(payload, ORDER_RECEIPT_ALLOWED_FIELDS)
        if not update_data:
            return jsonify({"error": "沒有可更新的合法欄位", "ignoredFields": ignored_fields}), 400
        update_data["updatedAt"] = utc_now()
        result = database.db.orders.update_one({"orderId": clean_id}, {"$set": update_data})
    else:
        return jsonify({"error": f"無法識別的單號格式：{clean_id}"}), 400

    if result.matched_count == 0:
        return jsonify({"error": f"找不到單號：{clean_id}"}), 404

    admin_name = session.get('admin_username', 'admin')
    ignored_text = f"，忽略欄位：{', '.join(ignored_fields)}" if ignored_fields else ''
    database.write_audit_log(admin_name, '修改單據', clean_id, f"欄位：{', '.join(update_data.keys())}{ignored_text}")
    return jsonify({
        "success": True,
        "message": f"單據 {clean_id} 已更新成功",
        "ignoredFields": ignored_fields,
    })


@admin_bp.route('/api/admin/receipt/<receipt_id>', methods=['DELETE'])
@admin_required(roles=['super_admin'])
def force_delete_receipt(receipt_id):
    """強制刪除單據"""
    if database.db is None:
        return jsonify({"error": "資料庫未連線"}), 500

    clean_id = receipt_id.strip().upper()

    if clean_id.startswith('FB'):
        result = database.db.feedback.delete_one({"feedbackId": clean_id})
        if result.deleted_count > 0:
            database.write_audit_log(session.get('admin_username', 'admin'), '強制刪除單據', clean_id)
            return jsonify({"success": True, "message": f"已成功刪除回饋單：{clean_id}"})
        else:
            return jsonify({"error": f"找不到回饋單號：{clean_id}"}), 404

    elif clean_id.startswith(('ORD', 'DON', 'FND', 'COM')):
        order = database.db.orders.find_one({"orderId": clean_id})
        result = database.db.orders.delete_one({"orderId": clean_id})
        if result.deleted_count > 0:
            release_committee_quota_for_order(order)
            database.write_audit_log(session.get('admin_username', 'admin'), '強制刪除單據', clean_id)
            return jsonify({"success": True, "message": f"已成功刪除單據：{clean_id}"})
        else:
            return jsonify({"error": f"找不到此單號：{clean_id}"}), 404

    else:
        return jsonify({"error": f"無法識別的單號格式：{clean_id}"}), 400


@admin_bp.route('/api/debug-connection')
@admin_required(roles=['super_admin'])
def debug_connection():
    status = {}
    try:
        database.db.command('ping')
        status['database'] = "✅ MongoDB 連線成功"
    except Exception as e:
        status['database'] = f"❌ MongoDB 連線失敗: {str(e)}"
    return jsonify(status)
# === 委員會名額與金額管理 API ===
@admin_bp.route('/api/settings/committee-quota', methods=['GET', 'POST'])
@admin_required(roles=['super_admin', 'cms'])
def handle_committee_quota():
    # 完整的 9 個項目預設值
    default_roles = [
        {"name": "[建廟] 籌備主委", "limit": 1, "price": 50000},
        {"name": "[建廟] 籌備副主委", "limit": 10, "price": 36000},
        {"name": "[建廟] 建廟功德金", "limit": 999, "price": 10000},
        {"name": "[顧問] 顧問主席", "limit": 1, "price": 50000},
        {"name": "[顧問] 顧問副主席", "limit": 7, "price": 36000},
        {"name": "[顧問] 顧問", "limit": 999, "price": 20000},
        {"name": "[本府] 主委", "limit": 1, "price": 50000},
        {"name": "[本府] 副主委", "limit": 7, "price": 36000},
        {"name": "[本府] 委員", "limit": 999, "price": 25000}
    ]

    if database.db is None:
        if request.method == 'GET':
            return jsonify(default_roles)
        return jsonify({"error": "Database unavailable"}), 503

    if request.method == 'GET':
        setting = database.db.settings.find_one({"type": "committee_quota"})
        db_roles = setting.get("roles", []) if setting else []
        
        # 💡 強效修復：如果資料庫項目不齊全，則進行合併
        if len(db_roles) < 9:
            # 以預設值為基底，如果資料庫有同名的就用資料庫的數字
            db_map = {r['name']: r for r in db_roles}
            final_roles = []
            for d in default_roles:
                final_roles.append(db_map.get(d['name'], d))
            return jsonify(final_roles)
            
        return jsonify(db_roles)
    
    # 儲存設定
    data = _clean_committee_roles(get_json_value([]))
    if not data:
        return jsonify({"error": "未收到有效的委員會設定"}), 400
    database.db.settings.update_one(
        {"type": "committee_quota"},
        {"$set": {"roles": data}},
        upsert=True
    )
    sync_committee_quota_usages(data)
    # 寫入操作日誌以便追蹤
    database.write_audit_log(session.get('admin_username', 'admin'), '更新委員會名額與金額')
    return jsonify({"success": True})
# =========================================================
# 臨時工具：歷史回饋單快照修復
# =========================================================
@admin_bp.route('/api/admin/data/fix-feedback-snapshots', methods=['POST'])
@admin_required(roles=['super_admin'])
def fix_feedback_snapshots():
    """一次性歷史資料修復：把舊回饋單補上會員個資快照"""
    if database.db is None:
        return jsonify({"error": "資料庫未連線"}), 500

    feedback = list(database.db.feedback.find(
        {"$or": [{"realName": {"$exists": False}}, {"realName": ""}]},
        {"lineId": 1},
    ))
    line_ids = list({fb.get('lineId') for fb in feedback if fb.get('lineId')})
    users = {
        user['lineId']: user
        for user in database.db.users.find(
            {"lineId": {"$in": line_ids}},
            {"lineId": 1, "realName": 1, "phone": 1, "address": 1, "email": 1, "lunarBirthday": 1},
        )
    } if line_ids else {}

    operations = []
    for fb in feedback:
        user_info = users.get(fb.get('lineId'))
        if not user_info:
            continue
        operations.append(UpdateOne(
            {"_id": fb['_id']},
            {"$set": {
                "realName": user_info.get('realName', ''),
                "phone": user_info.get('phone', ''),
                "address": user_info.get('address', ''),
                "email": user_info.get('email', ''),
                "lunarBirthday": user_info.get('lunarBirthday', ''),
            }},
        ))

    updated_count = 0
    if operations:
        updated_count = database.db.feedback.bulk_write(operations, ordered=False).modified_count

    return jsonify({"success": True, "message": f"已成功為 {updated_count} 筆歷史回饋單補上資料快照"})
