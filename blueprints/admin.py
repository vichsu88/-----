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


def _tw_time(dt):
    """UTC datetime → 台灣時間字串（相容 legacy 字串資料）"""
    if not dt:
        return ''
    if isinstance(dt, str):
        return dt
    try:
        return (dt + timedelta(hours=8)).strftime('%Y-%m-%d %H:%M')
    except Exception:
        return str(dt) if dt else ''


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
    """已出貨歷史 (最近 30 天) — 保留 API 供歷史總表使用"""
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
# 整併 orders + feedback 到單一歷史總表
# =========================================================

@admin_bp.route('/api/admin/data/history')
@admin_required(roles=['super_admin', 'data', 'finance'])
def get_data_history():
    """萬用歷史總表：整併 orders + feedback，支援複合篩選"""
    if db is None:
        return jsonify({"results": [], "total": 0})

    order_type = request.args.get('type')
    order_id = request.args.get('orderId')
    name = request.args.get('name')
    status = request.args.get('status')
    start = request.args.get('start')
    end = request.args.get('end')
    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 50))
    skip = (page - 1) * per_page

    date_range = None
    if start and end:
        try:
            date_range = {
                "$gte": datetime.strptime(start, '%Y-%m-%d'),
                "$lt": datetime.strptime(end, '%Y-%m-%d') + timedelta(days=1)
            }
        except ValueError:
            pass

    all_results = []
    total_orders = 0
    total_feedback = 0

    # --- 查詢 Orders (type 非 feedback 時) ---
    if order_type != 'feedback':
        oq = {}
        if order_type:
            oq['orderType'] = order_type
        if order_id:
            oq['orderId'] = {"$regex": order_id.strip(), "$options": "i"}
        if name:
            oq['customer.name'] = {"$regex": name.strip()}
        if status:
            oq['status'] = status
        if date_range:
            oq['createdAt'] = date_range

        total_orders = db.orders.count_documents(oq)
        for doc in db.orders.find(oq).sort("createdAt", -1).limit(skip + per_page):
            sort_ts = _get_sort_ts(doc.get('createdAt'))
            doc['_id'] = str(doc['_id'])
            doc['createdAt'] = _tw_time(doc.get('createdAt'))
            doc['source_label'] = _TYPE_LABELS.get(doc.get('orderType', ''), '未知')
            doc['_docType'] = 'order'
            doc['_sortTs'] = sort_ts
            if doc.get('paidAt'):
                doc['paidAt'] = _tw_time(doc['paidAt'])
                doc['paidBy'] = doc.get('paidBy', '') # 新增這行
            if doc.get('shippedAt'):
                doc['shippedAt'] = _tw_time(doc['shippedAt'])
                doc['shippedBy'] = doc.get('shippedBy', '')
            if doc.get('reportedAt'):
                doc['reportedAt'] = _tw_time(doc['reportedAt'])
                doc['reportedBy'] = doc.get('reportedBy', '')
            all_results.append(doc)

    # --- 查詢 Feedback (type 為空或 feedback 時) ---
    if not order_type or order_type == 'feedback':
        fq = {}
        if order_id:
            fq['feedbackId'] = {"$regex": order_id.strip(), "$options": "i"}
        if name:
            # 支援同時搜尋「真實姓名」與「暱稱」，且不分大小寫
            name_regex = {"$regex": name.strip(), "$options": "i"}
            fq['$or'] = [
                {'nickname': name_regex},
                {'realName': name_regex}
            ]
        if status:
            fq['status'] = status
        if date_range:
            fq['createdAt'] = date_range

        total_feedback = db.feedback.count_documents(fq)
        for doc in db.feedback.find(fq).sort("createdAt", -1).limit(skip + per_page):
            sort_ts = _get_sort_ts(doc.get('createdAt'))
            fb = {
                '_id': str(doc['_id']),
                'orderId': doc.get('feedbackId', ''),
                'feedbackId': doc.get('feedbackId', ''),
                'orderType': 'feedback',
                'status': doc.get('status', ''),
                'customer': {'name': doc.get('nickname', '匿名')},
                'items': [],
                'total': 0,
                'createdAt': _tw_time(doc.get('createdAt')),
                'source_label': '💬 回饋',
                '_docType': 'feedback',
                '_sortTs': sort_ts,
                # 保留原始回饋欄位供 detail modal 使用
                'nickname': doc.get('nickname', ''),
                'content': doc.get('content', ''),
                'category': doc.get('category', []),
                'realName': doc.get('realName', ''),
                'phone': doc.get('phone', ''),
                'address': doc.get('address', ''),
                'lineId': doc.get('lineId', ''),
            }
            if doc.get('approvedAt'):
                fb['approvedAt'] = _tw_time(doc.get('approvedAt'))
                fb['approvedBy'] = doc.get('approvedBy', '')
            if doc.get('sentAt'):
                fb['sentAt'] = _tw_time(doc.get('sentAt'))
                fb['sentBy'] = doc.get('sentBy', '')
            if doc.get('trackingNumber'):
                fb['trackingNumber'] = doc['trackingNumber']
            all_results.append(fb)

    # 合併排序 (依建立時間降冪)
    all_results.sort(key=lambda x: x.get('_sortTs', 0), reverse=True)

    # 清除排序暫存欄位並分頁
    total = total_orders + total_feedback
    page_results = all_results[skip:skip + per_page]
    for r in page_results:
        r.pop('_sortTs', None)

    return jsonify({"results": page_results, "total": total, "page": page, "per_page": per_page})

@admin_bp.route('/api/donations/mark-reported', methods=['POST'])
@admin_required(roles=['super_admin', 'ops'])
def mark_donations_reported():
    """批次標記捐香訂單為已稟告"""
    if db is None:
        return jsonify({"error": "資料庫未連線"}), 500

    data = request.get_json()
    if not data or 'ids' not in data:
        return jsonify({"error": "未提供要標記的資料"}), 400

    ids = data.get('ids', [])
    if not ids:
        return jsonify({"error": "未提供訂單 ID"}), 400

    # 將字串 ID 轉換為 MongoDB 的 ObjectId
    object_ids = []
    for id_str in ids:
        oid = get_object_id(id_str)
        if oid:
            object_ids.append(oid)

    if not object_ids:
        return jsonify({"error": "無效的訂單 ID"}), 400

    admin_name = session.get('admin_username', 'admin')
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    # 執行批次更新
    result = db.orders.update_many(
        {"_id": {"$in": object_ids}},
        {"$set": {
            "is_reported": True,
            "reportedAt": now,
            "reportedBy": admin_name
        }}
    )

    write_audit_log(admin_name, '批次標記已稟告', f'共 {result.modified_count} 筆')
    return jsonify({"success": True, "message": f"已成功標記 {result.modified_count} 筆訂單為已稟告"})
# =========================================================
# 委員會名額動態管理 (CMS)
# =========================================================


@admin_bp.route('/api/admin/data/export-csv')
@admin_required(roles=['super_admin', 'data', 'finance'])
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
        # 加上規格名稱的判斷
        items_str = '；'.join([f"{i.get('name', '')}{'('+i.get('variantName', '')+')' if i.get('variantName') else ''}x{i.get('qty', 1)}" for i in doc.get('items', [])])
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
@admin_required(roles=['super_admin', 'data', 'finance'])
def get_data_members():
    """會員資料庫 — 效能極致優化版 (解決 OOM 問題)"""
    if db is None:
        return jsonify([])

    try:
        # 🚀 秘訣 1：一次性向資料庫要「所有人的訂單總數」字典，極度省 RAM 且神速
        order_counts = {}
        for item in db.orders.aggregate([{"$group": {"_id": "$lineId", "count": {"$sum": 1}}}]):
            if item.get("_id"):
                order_counts[item["_id"]] = item["count"]

        # 🚀 秘訣 2：一次性向資料庫要「所有人的回饋總數」字典
        feedback_counts = {}
        for item in db.feedback.aggregate([{"$group": {"_id": "$lineId", "count": {"$sum": 1}}}]):
            if item.get("_id"):
                feedback_counts[item["_id"]] = item["count"]

        # 🚀 秘訣 3：記憶體瘦身 (Projection)
        # 只抓前台真的需要的欄位，不要把不相干的資料庫欄位拉進 RAM。
        # 同時設定 limit(3000) 當作安全閥，避免未來會員破萬時 RAM 又爆掉。
        projection = {
            "displayName": 1, "lineId": 1, "lastLoginAt": 1, 
            "createdAt": 1, "pictureUrl": 1, "realName": 1
        }
        cursor = db.users.find({}, projection).sort("lastLoginAt", -1).limit(3000)
        
        results = []
        for user in cursor:
            user['_id'] = str(user['_id'])
            user['lastLoginAt'] = _tw_time(user.get('lastLoginAt'))
            user['createdAt'] = _tw_time(user.get('createdAt'))
            
            # 從剛剛算好的總表字典裡快速取值 (O(1) 速度)，完全不用再連線資料庫
            line_id = user.get('lineId')
            user['orderCount'] = order_counts.get(line_id, 0)
            user['feedbackCount'] = feedback_counts.get(line_id, 0)
            
            results.append(_serialize_doc(user))

        return jsonify(results)

    except Exception as e:
        import traceback
        error_msg = traceback.format_exc()
        print(f"[嚴重崩潰] 會員列表無法載入:\n{error_msg}")
        return jsonify({"error": f"資料庫查詢錯誤: {str(e)}"}), 500

    except Exception as e:
        # 🛡️ 如果是一開始的 cursor 迭代或連線就當機，會被這裡接住
        import traceback
        error_msg = traceback.format_exc()
        print(f"[嚴重崩潰] 會員列表無法載入:\n{error_msg}")
        
        # 不再給 500 HTML 頁面，而是回傳 500 JSON，讓前端可以優雅地顯示真正的錯誤原因！
        return jsonify({"error": f"資料庫查詢錯誤: {str(e)}"}), 500


@admin_bp.route('/api/admin/data/member/<line_id>/history')
@admin_required(roles=['super_admin', 'data', 'finance'])
def get_member_history(line_id):
    """會員互動歷程：該會員所有 orders + feedback"""
    if db is None:
        return jsonify({"orders": [], "feedback": []})

    orders = []
    for doc in db.orders.find({"lineId": line_id}).sort("createdAt", -1).limit(200):
        doc['_id'] = str(doc['_id'])
        doc['createdAt'] = _tw_time(doc.get('createdAt'))
        doc['source_label'] = _TYPE_LABELS.get(doc.get('orderType', ''), '未知')
        if doc.get('paidAt'):
            doc['paidAt'] = _tw_time(doc['paidAt'])
            doc['paidBy'] = doc.get('paidBy', '') # 新增這行
        orders.append(doc)

    feedback = []
    for doc in db.feedback.find({"lineId": line_id}).sort("createdAt", -1).limit(200):
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
    if db is None:
        return jsonify([])

    cursor = db.admin_users.find({}, {"password_hash": 0}).sort("createdAt", -1)
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
    data = request.get_json()
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()
    permissions = data.get('permissions', [])

    # 向下相容：若前端仍傳 role 字串
    if not permissions and data.get('role'):
        permissions = [data['role']]

    if not username or not password:
        return jsonify({"error": "帳號和密碼不可為空"}), 400

    if len(password) < 6:
        return jsonify({"error": "密碼長度至少 6 字元"}), 400

    valid_perms = ['super_admin', 'finance', 'ops', 'data', 'cms']
    for p in permissions:
        if p not in valid_perms:
            return jsonify({"error": f"無效的權限: {p}"}), 400

    if not permissions:
        return jsonify({"error": "請至少選擇一個權限"}), 400

    if db.admin_users.find_one({"username": username}):
        return jsonify({"error": "此帳號已存在"}), 400

    db.admin_users.insert_one({
        "username": username,
        "password_hash": generate_password_hash(password),
        "permissions": permissions,
        "role": 'super_admin' if 'super_admin' in permissions else permissions[0],
        "createdAt": datetime.now(timezone.utc).replace(tzinfo=None)
    })

    admin_name = session.get('admin_username', 'admin')
    write_audit_log(admin_name, '新增管理員帳號', username, f'權限: {", ".join(permissions)}')
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
# === 委員會名額管理 API ===
@admin_bp.route('/api/settings/committee-quota', methods=['GET', 'POST'])
@admin_required(roles=['super_admin', 'cms'])
def handle_committee_quota():
    if request.method == 'GET':
        setting = db.settings.find_one({"type": "committee_quota"})
        # 完整 9 個項目清單與預設金額
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
        return jsonify(setting.get("roles", default_roles) if setting else default_roles)
    
    data = request.get_json()
    db.settings.update_one(
        {"type": "committee_quota"},
        {"$set": {"roles": data}},
        upsert=True
    )
    return jsonify({"success": True})
# =========================================================
# 臨時工具：歷史回饋單快照修復
# =========================================================
@admin_bp.route('/api/admin/data/fix-feedback-snapshots', methods=['POST'])
@admin_required(roles=['super_admin'])
def fix_feedback_snapshots():
    """一次性歷史資料修復：把舊回饋單補上會員個資快照"""
    if db is None:
        return jsonify({"error": "資料庫未連線"}), 500

    updated_count = 0
    # 找出所有「還沒有 realName 欄位」或「realName 為空」的舊回饋單
    cursor = db.feedback.find({"$or": [{"realName": {"$exists": False}}, {"realName": ""}]})
    
    for fb in cursor:
        line_id = fb.get('lineId')
        if line_id:
            user_info = db.users.find_one({"lineId": line_id})
            if user_info:
                db.feedback.update_one(
                    {"_id": fb['_id']},
                    {"$set": {
                        "realName": user_info.get('realName', ''),
                        "phone": user_info.get('phone', ''),
                        "address": user_info.get('address', ''),
                        "email": user_info.get('email', ''),
                        "lunarBirthday": user_info.get('lunarBirthday', '')
                    }}
                )
                updated_count += 1

    return jsonify({"success": True, "message": f"太棒了！已成功為 {updated_count} 筆歷史回饋單補上資料快照！"})
