import io
from datetime import datetime, timedelta, timezone

from bson import ObjectId
from flask import Blueprint, Response, jsonify, request, session
from werkzeug.security import generate_password_hash

from database import db, write_audit_log
from utils.decorators import login_required, admin_required
from utils.helpers import get_object_id

admin_bp = Blueprint('admin', __name__)


# =========================================================
# 工具函式
# =========================================================

def _serialize_doc(obj):
    """遞迴序列化 MongoDB 文件 (ObjectId, datetime → str)"""
    if isinstance(obj, dict):
        return {k: _serialize_doc(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_serialize_doc(v) for v in obj]
    if isinstance(obj, ObjectId):
        return str(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
    return obj


def _tw_time(dt):
    """UTC datetime → 台灣時間字串"""
    if dt:
        return (dt + timedelta(hours=8)).strftime('%Y-%m-%d %H:%M')
    return ''


_TYPE_LABELS = {
    'shop': '🛍️ 結緣品',
    'donation': '🕯️ 捐香',
    'fund': '🏗️ 建廟基金',
    'committee': '🏛️ 委員會'
}


# =========================================================
# Module 1: 💰 財務稽核中樞 (Finance Hub)
# =========================================================

@admin_bp.route('/api/admin/finance/pending')
@admin_required(roles=['super_admin', 'finance'])
def get_finance_pending():
    """彙整所有來源的「待收款」單據"""
    if db is None:
        return jsonify([])

    cursor = db.orders.find({"status": "pending"}).sort("createdAt", -1)
    results = []
    for doc in cursor:
        doc['_id'] = str(doc['_id'])
        doc['createdAt'] = _tw_time(doc.get('createdAt'))
        doc['source_label'] = _TYPE_LABELS.get(doc.get('orderType', ''), '未知')
        if doc.get('paymentDeadline'):
            doc['paymentDeadline'] = _tw_time(doc['paymentDeadline'])
        results.append(doc)
    return jsonify(results)


@admin_bp.route('/api/admin/finance/summary')
@admin_required(roles=['super_admin', 'finance'])
def get_finance_summary():
    """財務摘要：各類別待收款/已收款筆數與金額"""
    if db is None:
        return jsonify({})

    pipeline = [
        {"$group": {
            "_id": {"type": "$orderType", "status": "$status"},
            "count": {"$sum": 1},
            "total": {"$sum": "$total"}
        }}
    ]
    raw = list(db.orders.aggregate(pipeline))

    summary = {}
    for item in raw:
        ot = item['_id']['type']
        st = item['_id']['status']
        if ot not in summary:
            summary[ot] = {}
        summary[ot][st] = {"count": item['count'], "total": item['total']}

    return jsonify(summary)


# =========================================================
# Module 2: 🛠️ 站務作業中樞 (Operations Center)
# =========================================================

@admin_bp.route('/api/admin/ops/print-queue')
@admin_required(roles=['super_admin', 'ops'])
def get_print_queue():
    """文書列印排程：已付款但未稟告的捐香訂單"""
    if db is None:
        return jsonify([])

    cursor = db.orders.find({
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
    if db is None:
        return jsonify([])

    cursor = db.orders.find({
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
    """已出貨歷史 (最近 30 天)"""
    if db is None:
        return jsonify([])

    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=30)
    cursor = db.orders.find({
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
# =========================================================

@admin_bp.route('/api/admin/data/history')
@admin_required(roles=['super_admin', 'finance'])
def get_data_history():
    """萬用歷史總表：支援複合篩選 (項目/單號/姓名/狀態/日期)"""
    if db is None:
        return jsonify({"results": [], "total": 0})

    query = {}

    order_type = request.args.get('type')
    if order_type:
        query['orderType'] = order_type

    order_id = request.args.get('orderId')
    if order_id:
        query['orderId'] = {"$regex": order_id.strip(), "$options": "i"}

    name = request.args.get('name')
    if name:
        query['customer.name'] = {"$regex": name.strip()}

    status = request.args.get('status')
    if status:
        query['status'] = status

    start = request.args.get('start')
    end = request.args.get('end')
    if start and end:
        try:
            query['createdAt'] = {
                "$gte": datetime.strptime(start, '%Y-%m-%d'),
                "$lt": datetime.strptime(end, '%Y-%m-%d') + timedelta(days=1)
            }
        except ValueError:
            pass

    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 50))
    skip = (page - 1) * per_page

    total = db.orders.count_documents(query)
    cursor = db.orders.find(query).sort("createdAt", -1).skip(skip).limit(per_page)

    results = []
    for doc in cursor:
        doc['_id'] = str(doc['_id'])
        doc['createdAt'] = _tw_time(doc.get('createdAt'))
        doc['source_label'] = _TYPE_LABELS.get(doc.get('orderType', ''), '未知')
        if doc.get('paidAt'):
            doc['paidAt'] = _tw_time(doc['paidAt'])
        if doc.get('shippedAt'):
            doc['shippedAt'] = _tw_time(doc['shippedAt'])
        if doc.get('reportedAt'):
            doc['reportedAt'] = _tw_time(doc['reportedAt'])
        results.append(doc)

    return jsonify({"results": results, "total": total, "page": page, "per_page": per_page})


@admin_bp.route('/api/admin/data/export-csv')
@admin_required(roles=['super_admin', 'finance'])
def export_data_csv():
    """匯出歷史資料為 CSV (所見即所得)"""
    if db is None:
        return jsonify({"error": "資料庫未連線"}), 500

    query = {}
    order_type = request.args.get('type')
    if order_type:
        query['orderType'] = order_type
    status = request.args.get('status')
    if status:
        query['status'] = status
    name = request.args.get('name')
    if name:
        query['customer.name'] = {"$regex": name.strip()}
    start = request.args.get('start')
    end = request.args.get('end')
    if start and end:
        try:
            query['createdAt'] = {
                "$gte": datetime.strptime(start, '%Y-%m-%d'),
                "$lt": datetime.strptime(end, '%Y-%m-%d') + timedelta(days=1)
            }
        except ValueError:
            pass

    cursor = db.orders.find(query).sort("createdAt", -1).limit(5000)

    si = io.StringIO()
    si.write('\ufeff')  # BOM for Excel
    si.write('單號,類型,狀態,姓名,電話,Email,地址,項目,金額,建立日期,付款日期\n')

    for doc in cursor:
        cust = doc.get('customer', {})
        items_str = '；'.join([f"{i.get('name', '')}x{i.get('qty', 1)}" for i in doc.get('items', [])])
        row = [
            doc.get('orderId', ''),
            _TYPE_LABELS.get(doc.get('orderType', ''), ''),
            doc.get('status', ''),
            cust.get('name', ''),
            cust.get('phone', ''),
            cust.get('email', ''),
            cust.get('address', '').replace(',', '，'),
            items_str.replace(',', '，'),
            str(doc.get('total', 0)),
            _tw_time(doc.get('createdAt')),
            _tw_time(doc.get('paidAt'))
        ]
        si.write(','.join(row) + '\n')

    return Response(
        si.getvalue(),
        mimetype='text/csv; charset=utf-8',
        headers={"Content-Disposition": f"attachment; filename=export_{datetime.now().strftime('%Y%m%d')}.csv"}
    )


@admin_bp.route('/api/admin/data/members')
@admin_required(roles=['super_admin', 'finance'])
def get_data_members():
    """會員資料庫"""
    if db is None:
        return jsonify([])

    cursor = db.users.find({}).sort("lastLoginAt", -1)
    results = []
    for user in cursor:
        user['_id'] = str(user['_id'])
        user['lastLoginAt'] = _tw_time(user.get('lastLoginAt'))
        user['createdAt'] = _tw_time(user.get('createdAt'))
        # 統計每位會員的訂單數
        line_id = user.get('lineId')
        if line_id:
            user['orderCount'] = db.orders.count_documents({"lineId": line_id})
            user['feedbackCount'] = db.feedback.count_documents({"lineId": line_id})
        results.append(user)
    return jsonify(results)


# =========================================================
# Module 5: ⚙️ 系統與權限管理 (System & RBAC)
# =========================================================

@admin_bp.route('/api/admin/system/users', methods=['GET'])
@admin_required(roles=['super_admin'])
def list_admin_users():
    """列出所有管理員帳號 (不含密碼)"""
    if db is None:
        return jsonify([])

    cursor = db.admin_users.find({}, {"password_hash": 0}).sort("createdAt", -1)
    results = []
    for user in cursor:
        user['_id'] = str(user['_id'])
        user['createdAt'] = _tw_time(user.get('createdAt'))
        results.append(user)
    return jsonify(results)


@admin_bp.route('/api/admin/system/users', methods=['POST'])
@admin_required(roles=['super_admin'])
def create_admin_user():
    """建立新管理員帳號"""
    data = request.get_json()
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()
    role = data.get('role', 'ops')

    if not username or not password:
        return jsonify({"error": "帳號和密碼不可為空"}), 400

    if len(password) < 6:
        return jsonify({"error": "密碼長度至少 6 字元"}), 400

    valid_roles = ['super_admin', 'finance', 'ops']
    if role not in valid_roles:
        return jsonify({"error": f"角色必須為 {', '.join(valid_roles)} 之一"}), 400

    if db.admin_users.find_one({"username": username}):
        return jsonify({"error": "此帳號已存在"}), 400

    db.admin_users.insert_one({
        "username": username,
        "password_hash": generate_password_hash(password),
        "role": role,
        "createdAt": datetime.now(timezone.utc).replace(tzinfo=None)
    })

    admin_name = session.get('admin_username', 'admin')
    write_audit_log(admin_name, '新增管理員帳號', username, f'角色: {role}')
    return jsonify({"success": True, "message": f"已建立帳號 {username}"})


@admin_bp.route('/api/admin/system/users/<uid>', methods=['DELETE'])
@admin_required(roles=['super_admin'])
def delete_admin_user(uid):
    """刪除管理員帳號"""
    oid = get_object_id(uid)
    if not oid:
        return jsonify({"error": "無效的 ID"}), 400

    user = db.admin_users.find_one({"_id": oid})
    if not user:
        return jsonify({"error": "帳號不存在"}), 404

    db.admin_users.delete_one({"_id": oid})

    admin_name = session.get('admin_username', 'admin')
    write_audit_log(admin_name, '刪除管理員帳號', user.get('username', ''))
    return jsonify({"success": True})


@admin_bp.route('/api/admin/system/audit-log')
@admin_required(roles=['super_admin'])
def get_audit_log():
    """操作日誌查詢"""
    if db is None:
        return jsonify([])

    limit = int(request.args.get('limit', 200))
    cursor = db.audit_log.find({}).sort("timestamp", -1).limit(limit)

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
@login_required
def handle_bank_settings():
    if request.method == 'GET':
        fund_set = db.settings.find_one({"type": "bank_info"}) or {}
        shop_set = db.settings.find_one({"type": "bank_info_shop"}) or {}

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
        data = request.get_json()
        if 'fund' in data:
            db.settings.update_one(
                {"type": "bank_info"},
                {"$set": data['fund']},
                upsert=True
            )
        if 'shop' in data:
            db.settings.update_one(
                {"type": "bank_info_shop"},
                {"$set": data['shop']},
                upsert=True
            )
        write_audit_log(session.get('admin_username', 'admin'), '更新匯款帳號設定')
        return jsonify({"success": True})


@admin_bp.route('/api/public/bank-info', methods=['GET'])
def get_public_bank_info():
    usage = request.args.get('type', 'shop')
    setting_key = "bank_info" if usage == 'fund' else "bank_info_shop"

    defaults = {
        'fund': {'code': '103', 'name': '新光銀行', 'account': '0666-50-971133-3'},
        'shop': {'code': '808', 'name': '玉山銀行', 'account': '尚未設定'}
    }

    settings = {}
    if db is not None:
        settings = db.settings.find_one({"type": setting_key}) or {}

    return jsonify({
        "bankCode": settings.get('bankCode', defaults[usage]['code']),
        "bankName": settings.get('bankName', defaults[usage]['name']),
        "account": settings.get('account', defaults[usage]['account'])
    })


@admin_bp.route('/api/admin/receipt/<receipt_id>', methods=['GET'])
@login_required
def query_receipt(receipt_id):
    """萬能單據查詢"""
    if db is None:
        return jsonify({"error": "資料庫未連線"}), 500

    clean_id = receipt_id.strip().upper()

    if clean_id.startswith('FB'):
        doc = db.feedback.find_one({"feedbackId": clean_id})
    elif clean_id.startswith(('ORD', 'DON', 'FND', 'COM')):
        doc = db.orders.find_one({"orderId": clean_id})
    else:
        return jsonify({"error": f"無法識別的單號格式：{clean_id}"}), 400

    if not doc:
        return jsonify({"error": f"找不到單號：{clean_id}"}), 404

    return jsonify(_serialize_doc(doc))


@admin_bp.route('/api/admin/receipt/<receipt_id>', methods=['PUT'])
@login_required
def update_receipt(receipt_id):
    """萬能單據修改"""
    if db is None:
        return jsonify({"error": "資料庫未連線"}), 500

    clean_id = receipt_id.strip().upper()
    data = request.get_json()
    if not data:
        return jsonify({"error": "未收到 JSON 資料"}), 400

    data.pop('_id', None)

    if clean_id.startswith('FB'):
        result = db.feedback.update_one({"feedbackId": clean_id}, {"$set": data})
    elif clean_id.startswith(('ORD', 'DON', 'FND', 'COM')):
        result = db.orders.update_one({"orderId": clean_id}, {"$set": data})
    else:
        return jsonify({"error": f"無法識別的單號格式：{clean_id}"}), 400

    if result.matched_count == 0:
        return jsonify({"error": f"找不到單號：{clean_id}"}), 404

    admin_name = session.get('admin_username', 'admin')
    write_audit_log(admin_name, '修改單據', clean_id)
    return jsonify({"success": True, "message": f"單據 {clean_id} 已更新成功"})


@admin_bp.route('/api/admin/receipt/<receipt_id>', methods=['DELETE'])
@login_required
def force_delete_receipt(receipt_id):
    """強制刪除單據"""
    if db is None:
        return jsonify({"error": "資料庫未連線"}), 500

    clean_id = receipt_id.strip().upper()

    if clean_id.startswith('FB'):
        result = db.feedback.delete_one({"feedbackId": clean_id})
        if result.deleted_count > 0:
            write_audit_log(session.get('admin_username', 'admin'), '強制刪除單據', clean_id)
            return jsonify({"success": True, "message": f"已成功刪除回饋單：{clean_id}"})
        else:
            return jsonify({"error": f"找不到回饋單號：{clean_id}"}), 404

    elif clean_id.startswith(('ORD', 'DON', 'FND', 'COM')):
        result = db.orders.delete_one({"orderId": clean_id})
        if result.deleted_count > 0:
            write_audit_log(session.get('admin_username', 'admin'), '強制刪除單據', clean_id)
            return jsonify({"success": True, "message": f"已成功刪除單據：{clean_id}"})
        else:
            return jsonify({"error": f"找不到此單號：{clean_id}"}), 404

    else:
        return jsonify({"error": f"無法識別的單號格式：{clean_id}"}), 400


@admin_bp.route('/api/debug-connection')
def debug_connection():
    status = {}
    try:
        db.command('ping')
        status['database'] = "✅ MongoDB 連線成功"
    except Exception as e:
        status['database'] = f"❌ MongoDB 連線失敗: {str(e)}"
    return jsonify(status)
