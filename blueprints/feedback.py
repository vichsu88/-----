import io

from flask import Blueprint, jsonify, request, session, Response
from pymongo.errors import DuplicateKeyError

import database
from extensions import limiter
from services.sequence_service import generate_feedback_id, write_with_unique_id_retry
from tasks.notifications import (
    delay_notification,
    send_feedback_rejected_email,
    send_feedback_status_email,
)
from utils.decorators import admin_required, user_login_required
from utils.errors import ServiceUnavailableError
from utils.helpers import get_object_id
from utils.security import as_string, get_json_object
from utils.timezone import format_taipei, taipei_now, utc_now

feedback_bp = Blueprint('feedback', __name__)


def enrich_feedback_for_admin(cursor):
    """解決 N+1 Query：批次取得 User 與 sent 狀態，避免在迴圈內反覆查詢資料庫"""
    docs = list(cursor)
    if not docs:
        return []

    line_ids = list({d.get('lineId') for d in docs if d.get('lineId')})

    users_map = {}
    if line_ids:
        user_projection = {
            "lineId": 1,
            "realName": 1,
            "phone": 1,
            "address": 1,
            "email": 1,
            "lunarBirthday": 1,
        }
        for u in database.db.users.find({"lineId": {"$in": line_ids}}, user_projection):
            users_map[u['lineId']] = u

    sent_set = set()
    if line_ids:
        sent_counts = database.db.feedback.aggregate([
            {"$match": {"lineId": {"$in": line_ids}, "status": "sent"}},
            {"$group": {"_id": "$lineId"}}
        ])
        sent_set = {item['_id'] for item in sent_counts}

    results = []
    for doc in docs:
        line_id = doc.get('lineId')
        user = users_map.get(line_id, {})

        doc['realName'] = doc.get('realName') or user.get('realName') or '未填寫'
        doc['phone'] = doc.get('phone') or user.get('phone') or '未填寫'
        doc['address'] = doc.get('address') or user.get('address') or '未填寫'
        doc['email'] = doc.get('email') or user.get('email') or ''
        doc['lunarBirthday'] = doc.get('lunarBirthday') or user.get('lunarBirthday') or '未提供'
        doc['has_received'] = (line_id in sent_set)
        doc['_id'] = str(doc['_id'])

        for field, fmt in [('createdAt', '%Y-%m-%d %H:%M:%S'), ('approvedAt', '%Y-%m-%d %H:%M'), ('sentAt', '%Y-%m-%d %H:%M')]:
            if field in doc:
                val = doc[field]
                if isinstance(val, str):
                    pass  # already a string, keep as-is
                else:
                    try:
                        doc[field] = format_taipei(val, fmt)
                    except Exception:
                        doc[field] = str(val) if val else ''

        results.append(doc)
    return results


@feedback_bp.route('/api/feedback', methods=['POST'])
@limiter.limit("10 per hour")
@user_login_required
def add_feedback():
    if database.db is None:
        return jsonify({"error": "DB Error"}), 500
    line_id = session.get('user_line_id')

    data = get_json_object()
    if not data.get('agreed'):
        return jsonify({"error": "必須勾選同意條款"}), 400

    raw_category = data.get('category', [])
    category = [as_string(item).strip() for item in raw_category if as_string(item).strip()] if isinstance(raw_category, list) else []

    # 🚀 快照核心邏輯：在送出瞬間，立刻去 users 表把當下最新的個資抓出來
    user_info = database.db.users.find_one({"lineId": line_id}) or {}

    new_feedback = {
        "lineId": line_id,
        "nickname": as_string(data.get('nickname')).strip(),
        "category": category,
        "content": as_string(data.get('content')).strip(),
        "agreed": True,
        "createdAt": utc_now(),
        "status": "pending",
        "isMarked": False,
        
        # 🛡️ 寫入快照：實實在在地把個資存進這筆回饋單裡
        "realName": user_info.get('realName', ''),
        "phone": user_info.get('phone', ''),
        "address": user_info.get('address', ''),
        "email": user_info.get('email', ''),
        "lunarBirthday": user_info.get('lunarBirthday', '')
    }
    database.db.feedback.insert_one(new_feedback)
    return jsonify({"success": True, "message": "回饋已送出"})


@feedback_bp.route('/api/feedback/approved', methods=['GET'])
def get_public_approved_feedback():
    if database.db is None:
        return jsonify([])
    projection = {
        "feedbackId": 1,
        "nickname": 1,
        "category": 1,
        "content": 1,
        "createdAt": 1,
    }
    cursor = database.db.feedback.find(
        {"status": {"$in": ["approved", "sent"]}},
        projection,
    ).sort("approvedAt", -1)
    results = []
    for doc in cursor:
        results.append({
            '_id': str(doc['_id']),
            'feedbackId': doc.get('feedbackId', ''),
            'nickname': doc.get('nickname', '匿名'),
            'category': doc.get('category', []),
            'content': doc.get('content', ''),
            'createdAt': (doc['createdAt'].strftime('%Y-%m-%d') if hasattr(doc.get('createdAt'), 'strftime') else str(doc.get('createdAt', ''))) if 'createdAt' in doc else ''
        })
    return jsonify(results)


@feedback_bp.route('/api/feedback/status/pending', methods=['GET'])
@admin_required(roles=['super_admin', 'ops', 'data'])
def get_pending_feedback():
    cursor = database.db.feedback.find({"status": "pending"}).sort("createdAt", 1)
    return jsonify(enrich_feedback_for_admin(cursor))


@feedback_bp.route('/api/feedback/status/approved', methods=['GET'])
@admin_required(roles=['super_admin', 'ops', 'data'])
def get_admin_approved_feedback():
    cursor = database.db.feedback.find({"status": "approved"}).sort("approvedAt", -1)
    return jsonify(enrich_feedback_for_admin(cursor))


@feedback_bp.route('/api/feedback/status/sent', methods=['GET'])
@admin_required(roles=['super_admin', 'ops', 'data'])
def get_sent_feedback():
    cursor = database.db.feedback.find({"status": "sent"}).sort("sentAt", -1)
    return jsonify(enrich_feedback_for_admin(cursor))


@feedback_bp.route('/api/feedback/<fid>/approve', methods=['PUT'])
@admin_required(roles=['super_admin', 'ops'])
def approve_feedback(fid):
    oid = get_object_id(fid)
    if not oid:
        return jsonify({"error": "無效的 ID 格式"}), 400
        
    fb = database.db.feedback.find_one({'_id': oid})
    if not fb:
        return jsonify({"error": "No data"}), 404
    if fb.get("status") != "pending":
        return jsonify({"error": "只有待審核回饋可以核准"}), 400

    now = utc_now()
    admin_user = session.get('admin_username', 'admin') # 取得當下操作員

    def approve_with_id(candidate_feedback_id):
        # feedbackId 有 partial unique index，若撞號就重新取下一個 counter 流水號。
        return database.db.feedback.update_one({'_id': oid, 'status': 'pending'}, {'$set': {
            'status': 'approved',
            'feedbackId': candidate_feedback_id,
            'approvedAt': now,
            'approvedBy': admin_user
        }})

    try:
        fb_id, result = write_with_unique_id_retry(
            generate_feedback_id,
            approve_with_id,
            label="feedback",
        )
    except DuplicateKeyError as exc:
        raise ServiceUnavailableError("回饋編號產生重複，請稍後再試") from exc
    if result.matched_count == 0:
        return jsonify({"error": "狀態已被其他操作變更"}), 409
    
    database.write_audit_log(admin_user, '核准回饋', fb_id)

    delay_notification(send_feedback_status_email, str(oid), 'approved')
    return jsonify({"success": True})


@feedback_bp.route('/api/feedback/<fid>/ship', methods=['PUT'])
@admin_required(roles=['super_admin', 'ops'])
def ship_feedback(fid):
    oid = get_object_id(fid)
    if not oid:
        return jsonify({"error": "無效的 ID 格式"}), 400
        
    data = get_json_object()
    tracking = as_string(data.get('trackingNumber')).strip()
    
    fb = database.db.feedback.find_one({'_id': oid})
    if not fb:
        return jsonify({"error": "No data"}), 404
    if fb.get("status") != "approved":
        return jsonify({"error": "只有已核准回饋可以寄送"}), 400

    line_id = fb.get("lineId")
    if line_id:
        existing_sent = database.db.feedback.find_one({
            "lineId": line_id,
            "status": "sent",
            "_id": {"$ne": oid},
        })
        if existing_sent:
            return jsonify({"error": "此信徒已領取過回饋禮"}), 400

    # 準備好所有變數
    now = utc_now()
    admin_user = session.get('admin_username', 'admin') # 取得當下操作員

    # ✅ 變數都準備好後，才執行更新
    result = database.db.feedback.update_one({'_id': oid, 'status': 'approved'}, {'$set': {
        'status': 'sent',
        'trackingNumber': tracking,
        'sentAt': now,
        'sentBy': admin_user
    }})
    if result.matched_count == 0:
        return jsonify({"error": "狀態已被其他操作變更"}), 409
    
    database.write_audit_log(admin_user, '寄出回饋禮', fb.get('feedbackId', fid), tracking)

    delay_notification(send_feedback_status_email, str(oid), 'sent', tracking)
    return jsonify({"success": True})


@feedback_bp.route('/api/feedback/<fid>', methods=['DELETE'])
@admin_required(roles=['super_admin', 'ops'])
def delete_feedback(fid):
    oid = get_object_id(fid)
    if not oid:
        return jsonify({"error": "無效的 ID 格式"}), 400
    fb = database.db.feedback.find_one({'_id': oid})
    if not fb:
        return jsonify({"error": "No data"}), 404

    user = database.db.users.find_one({"lineId": fb.get('lineId')}) if fb and fb.get('lineId') else {}
    email = user.get('email') or (fb.get('email') if fb else None)
    if email:
        delay_notification(send_feedback_rejected_email, {
            "email": email,
            "feedbackId": fb.get('feedbackId', ''),
            "nickname": fb.get('nickname', ''),
            "category": fb.get('category', []),
            "content": fb.get('content', ''),
            "realName": user.get('realName') or fb.get('realName') or '信徒',
        })

    database.write_audit_log(session.get('admin_username', 'admin'), '刪除回饋', fb.get('feedbackId', fid) if fb else fid)
    database.db.feedback.delete_one({'_id': oid})
    return jsonify({"success": True})


@feedback_bp.route('/api/feedback/<fid>', methods=['PUT'])
@admin_required(roles=['super_admin', 'ops'])
def update_feedback(fid):
    oid = get_object_id(fid)
    if not oid:
        return jsonify({"error": "無效的 ID 格式"}), 400
    data = get_json_object()
    raw_category = data.get('category', [])
    category = [as_string(item).strip() for item in raw_category if as_string(item).strip()] if isinstance(raw_category, list) else []
    update_fields = {
        'nickname': as_string(data.get('nickname')).strip(),
        'category': category,
        'content': as_string(data.get('content')).strip()
    }
    for field in ('realName', 'phone', 'address', 'email', 'lunarBirthday'):
        if field in data:
            update_fields[field] = as_string(data.get(field)).strip()

    database.db.feedback.update_one({'_id': oid}, {'$set': update_fields})
    return jsonify({"success": True})


@feedback_bp.route('/api/feedback/export-sent-txt', methods=['POST'])
@admin_required(roles=['super_admin', 'ops', 'data'])
def export_sent_feedback_txt():
    cursor = database.db.feedback.find({"status": "sent"}).sort("sentAt", -1)
    enriched = enrich_feedback_for_admin(cursor)
    if not enriched:
        return jsonify({"error": "無已寄送資料"}), 404

    si = io.StringIO()
    si.write(f"已寄送名單匯出\n匯出時間: {taipei_now().strftime('%Y-%m-%d %H:%M')}\n")
    si.write("=" * 50 + "\n")
    for doc in enriched:
        si.write(f"{doc.get('realName', '')}\t{doc.get('phone', '')}\t{doc.get('address', '')}\n")
    return Response(si.getvalue(), mimetype='text/plain',
                    headers={"Content-Disposition": "attachment;filename=sent_feedback_list.txt"})


@feedback_bp.route('/api/feedback/export-txt', methods=['POST'])
@admin_required(roles=['super_admin', 'ops', 'data'])
def export_feedback_txt():
    cursor = database.db.feedback.find({"status": "approved"}).sort("approvedAt", 1)
    enriched = enrich_feedback_for_admin(cursor)
    if not enriched:
        return jsonify({"error": "無資料"}), 404

    si = io.StringIO()
    si.write(f"匯出時間: {taipei_now().strftime('%Y-%m-%d %H:%M')}\n\n")
    for doc in enriched:
        si.write(f"【編號】{doc.get('feedbackId', '無')}\n")
        si.write(f"姓名：{doc.get('realName', '')}\n")
        si.write(f"電話：{doc.get('phone', '')}\n")
        si.write(f"地址：{doc.get('address', '')}\n")
        si.write("-" * 30 + "\n")
    return Response(si.getvalue(), mimetype='text/plain',
                    headers={"Content-Disposition": "attachment;filename=feedback_list.txt"})
