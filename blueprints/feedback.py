import io
import random
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request, session, Response, current_app

from database import db, write_audit_log
from utils.decorators import login_required, user_login_required
from utils.helpers import get_object_id
from utils.email import send_email, generate_feedback_email_html

feedback_bp = Blueprint('feedback', __name__)


def enrich_feedback_for_admin(cursor):
    """解決 N+1 Query：批次取得 User 與 sent 狀態，避免在迴圈內反覆查詢資料庫"""
    docs = list(cursor)
    if not docs:
        return []

    line_ids = [d.get('lineId') for d in docs if d.get('lineId')]

    users_map = {}
    if line_ids:
        for u in db.users.find({"lineId": {"$in": line_ids}}):
            users_map[u['lineId']] = u

    sent_set = set()
    if line_ids:
        sent_counts = db.feedback.aggregate([
            {"$match": {"lineId": {"$in": line_ids}, "status": "sent"}},
            {"$group": {"_id": "$lineId"}}
        ])
        sent_set = {item['_id'] for item in sent_counts}

    results = []
    for doc in docs:
        line_id = doc.get('lineId')
        user = users_map.get(line_id, {})

        doc['realName'] = user.get('realName') or doc.get('realName', '未填寫')
        doc['phone'] = user.get('phone') or doc.get('phone', '未填寫')
        doc['address'] = user.get('address') or doc.get('address', '未填寫')
        doc['email'] = user.get('email') or doc.get('email', '')
        doc['lunarBirthday'] = user.get('lunarBirthday') or '未提供'
        doc['has_received'] = (line_id in sent_set)
        doc['_id'] = str(doc['_id'])

        for field, fmt in [('createdAt', '%Y-%m-%d %H:%M:%S'), ('approvedAt', '%Y-%m-%d %H:%M'), ('sentAt', '%Y-%m-%d %H:%M')]:
            if field in doc:
                val = doc[field]
                if isinstance(val, str):
                    pass  # already a string, keep as-is
                else:
                    try:
                        doc[field] = val.strftime(fmt)
                    except Exception:
                        doc[field] = str(val) if val else ''

        results.append(doc)
    return results


@feedback_bp.route('/api/feedback', methods=['POST'])
@user_login_required
def add_feedback():
    if db is None:
        return jsonify({"error": "DB Error"}), 500
    line_id = session.get('user_line_id')

    data = request.get_json()
    if not data.get('agreed'):
        return jsonify({"error": "必須勾選同意條款"}), 400

    new_feedback = {
        "lineId": line_id,
        "nickname": data.get('nickname'),
        "category": data.get('category', []),
        "content": data.get('content'),
        "agreed": True,
        "createdAt": datetime.now(timezone.utc).replace(tzinfo=None),
        "status": "pending",
        "isMarked": False
    }
    db.feedback.insert_one(new_feedback)
    return jsonify({"success": True, "message": "回饋已送出"})


@feedback_bp.route('/api/feedback/approved', methods=['GET'])
def get_public_approved_feedback():
    if db is None:
        return jsonify([])
    cursor = db.feedback.find({"status": "approved"}).sort("approvedAt", -1)
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
@login_required
def get_pending_feedback():
    cursor = db.feedback.find({"status": "pending"}).sort("createdAt", 1)
    return jsonify(enrich_feedback_for_admin(cursor))


@feedback_bp.route('/api/feedback/status/approved', methods=['GET'])
@login_required
def get_admin_approved_feedback():
    cursor = db.feedback.find({"status": "approved"}).sort("approvedAt", -1)
    return jsonify(enrich_feedback_for_admin(cursor))


@feedback_bp.route('/api/feedback/status/sent', methods=['GET'])
@login_required
def get_sent_feedback():
    cursor = db.feedback.find({"status": "sent"}).sort("sentAt", -1)
    return jsonify(enrich_feedback_for_admin(cursor))


@feedback_bp.route('/api/feedback/<fid>/approve', methods=['PUT'])
@login_required
def approve_feedback(fid):
    oid = get_object_id(fid)
    if not oid:
        return jsonify({"error": "無效的 ID 格式"}), 400
    fb = db.feedback.find_one({'_id': oid})
    if not fb:
        return jsonify({"error": "No data"}), 404

    fb_id = f"FB{datetime.now().strftime('%Y%m%d')}{random.randint(10,99)}"
    db.feedback.update_one({'_id': oid}, {'$set': {
        'status': 'approved',
        'feedbackId': fb_id,
        'approvedAt': datetime.now(timezone.utc).replace(tzinfo=None)
    }})
    write_audit_log(session.get('admin_username', 'admin'), '核准回饋', fb_id)

    user = db.users.find_one({"lineId": fb.get('lineId')}) if fb.get('lineId') else {}
    email = user.get('email') or fb.get('email')
    if email:
        fb_for_email = fb.copy()
        fb_for_email['realName'] = user.get('realName', '信徒')
        send_email(
            email, "【承天中承府】您的回饋已核准刊登",
            generate_feedback_email_html(fb_for_email, 'approved'),
            current_app.config['SENDGRID_API_KEY'], current_app.config['MAIL_SENDER'],
            is_html=True
        )
    return jsonify({"success": True})


@feedback_bp.route('/api/feedback/<fid>/ship', methods=['PUT'])
@login_required
def ship_feedback(fid):
    oid = get_object_id(fid)
    if not oid:
        return jsonify({"error": "無效的 ID 格式"}), 400
    data = request.get_json()
    tracking = data.get('trackingNumber', '')
    fb = db.feedback.find_one({'_id': oid})
    if not fb:
        return jsonify({"error": "No data"}), 404

    db.feedback.update_one({'_id': oid}, {'$set': {
        'status': 'sent',
        'trackingNumber': tracking,
        'sentAt': datetime.now(timezone.utc).replace(tzinfo=None)
    }})
    write_audit_log(session.get('admin_username', 'admin'), '寄出回饋禮', fb.get('feedbackId', fid), tracking)

    user = db.users.find_one({"lineId": fb.get('lineId')}) if fb.get('lineId') else {}
    email = user.get('email') or fb.get('email')
    if email:
        fb_for_email = fb.copy()
        fb_for_email['realName'] = user.get('realName', '信徒')
        send_email(
            email, "【承天中承府】結緣品寄出通知",
            generate_feedback_email_html(fb_for_email, 'sent', tracking),
            current_app.config['SENDGRID_API_KEY'], current_app.config['MAIL_SENDER'],
            is_html=True
        )
    return jsonify({"success": True})


@feedback_bp.route('/api/feedback/<fid>', methods=['DELETE'])
@login_required
def delete_feedback(fid):
    oid = get_object_id(fid)
    if not oid:
        return jsonify({"error": "無效的 ID 格式"}), 400
    fb = db.feedback.find_one({'_id': oid})
    if not fb:
        return jsonify({"error": "No data"}), 404

    user = db.users.find_one({"lineId": fb.get('lineId')}) if fb and fb.get('lineId') else {}
    email = user.get('email') or (fb.get('email') if fb else None)
    if email:
        fb_for_email = fb.copy()
        fb_for_email['realName'] = user.get('realName', '信徒')
        send_email(
            email, "【承天中承府】感謝您的投稿與分享",
            generate_feedback_email_html(fb_for_email, 'rejected'),
            current_app.config['SENDGRID_API_KEY'], current_app.config['MAIL_SENDER'],
            is_html=True
        )

    write_audit_log(session.get('admin_username', 'admin'), '刪除回饋', fb.get('feedbackId', fid) if fb else fid)
    db.feedback.delete_one({'_id': oid})
    return jsonify({"success": True})


@feedback_bp.route('/api/feedback/<fid>', methods=['PUT'])
@login_required
def update_feedback(fid):
    oid = get_object_id(fid)
    if not oid:
        return jsonify({"error": "無效的 ID 格式"}), 400
    data = request.get_json()
    db.feedback.update_one({'_id': oid}, {'$set': {
        'nickname': data.get('nickname'),
        'category': data.get('category'),
        'content': data.get('content')
    }})
    return jsonify({"success": True})


@feedback_bp.route('/api/feedback/export-sent-txt', methods=['POST'])
@login_required
def export_sent_feedback_txt():
    cursor = db.feedback.find({"status": "sent"}).sort("sentAt", -1)
    enriched = enrich_feedback_for_admin(cursor)
    if not enriched:
        return jsonify({"error": "無已寄送資料"}), 404

    si = io.StringIO()
    si.write(f"已寄送名單匯出\n匯出時間: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
    si.write("=" * 50 + "\n")
    for doc in enriched:
        si.write(f"{doc.get('realName', '')}\t{doc.get('phone', '')}\t{doc.get('address', '')}\n")
    return Response(si.getvalue(), mimetype='text/plain',
                    headers={"Content-Disposition": "attachment;filename=sent_feedback_list.txt"})


@feedback_bp.route('/api/feedback/export-txt', methods=['POST'])
@login_required
def export_feedback_txt():
    cursor = db.feedback.find({"status": "approved"}).sort("approvedAt", 1)
    enriched = enrich_feedback_for_admin(cursor)
    if not enriched:
        return jsonify({"error": "無資料"}), 404

    si = io.StringIO()
    si.write(f"匯出時間: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n")
    for doc in enriched:
        si.write(f"【編號】{doc.get('feedbackId', '無')}\n")
        si.write(f"姓名：{doc.get('realName', '')}\n")
        si.write(f"電話：{doc.get('phone', '')}\n")
        si.write(f"地址：{doc.get('address', '')}\n")
        si.write("-" * 30 + "\n")
    return Response(si.getvalue(), mimetype='text/plain',
                    headers={"Content-Disposition": "attachment;filename=feedback_list.txt"})
