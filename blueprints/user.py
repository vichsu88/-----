from collections import defaultdict
from datetime import timedelta

from flask import Blueprint, jsonify, request, session

from database import db
from utils.decorators import user_login_required
from utils.helpers import validate_real_name

user_bp = Blueprint('user', __name__)


@user_bp.route('/api/user/me', methods=['GET'])
def get_current_user():
    line_id = session.get('user_line_id')
    if not line_id:
        return jsonify({"logged_in": False})

    if db is not None:
        user = db.users.find_one({'lineId': line_id}, {'_id': 0})
        if user:
            has_received = db.feedback.count_documents({"lineId": line_id, "status": "sent"}) > 0
            user['has_received_gift'] = has_received

            user['title'] = ""
            committee_orders = db.orders.find({
                "lineId": line_id,
                "orderType": "committee",
                "status": "paid"
            })

            highest_title = ""
            current_rank = 99
            rank_map = {"主委": 1, "副主委": 2, "顧問": 3, "委員": 4, "功德主": 5}

            for order in committee_orders:
                for item in order.get('items', []):
                    name = item.get('name', '')
                    clean_title = name.replace('[本府] ', '').replace('[建廟] ', '').replace('籌備', '')
                    rank = rank_map.get(clean_title, 99)
                    if rank < current_rank:
                        current_rank = rank
                        highest_title = clean_title

            user['title'] = highest_title
            return jsonify({"logged_in": True, "user": user})

    return jsonify({"logged_in": False})


@user_bp.route('/api/user/profile', methods=['PUT'])
@user_login_required
def update_user_profile():
    data = request.get_json()
    line_id = session.get('user_line_id')

    is_valid, error_msg = validate_real_name(data.get('realName', '').strip())
    if not is_valid:
        return jsonify({"error": error_msg}), 400

    if db is not None:
        db.users.update_one(
            {"lineId": line_id},
            {"$set": {
                "realName": data.get('realName'),
                "nickname": data.get('nickname'),
                "phone": data.get('phone'),
                "address": data.get('address'),
                "email": data.get('email'),
                "lunarBirthday": data.get('lunarBirthday'),
                "birthTime": data.get('birthTime')
            }}
        )
        return jsonify({"success": True, "message": "資料已更新"})
    return jsonify({"error": "資料庫連線失敗"}), 500


@user_bp.route('/api/user/feedbacks', methods=['GET'])
@user_login_required
def get_user_feedbacks():
    line_id = session.get('user_line_id')
    if db is not None:
        cursor = db.feedback.find({"lineId": line_id}).sort("createdAt", -1)
        results = []
        for doc in cursor:
            content_preview = doc.get('content', '')
            if len(content_preview) > 50:
                content_preview = content_preview[:50] + '...'
            results.append({
                "_id": str(doc['_id']),
                "feedbackId": doc.get('feedbackId', ''),
                "category": doc.get('category', []),
                "content": doc.get('content', ''),
                "content_preview": content_preview,
                "status": doc.get('status', 'pending'),
                "createdAt": doc['createdAt'].strftime('%Y-%m-%d') if 'createdAt' in doc else '',
                "trackingNumber": doc.get('trackingNumber', '')
            })
        return jsonify(results)
    return jsonify([]), 500


@user_bp.route('/api/user/pickups', methods=['GET'])
@user_login_required
def get_user_pickups():
    from datetime import datetime
    from utils.helpers import get_tw_now
    line_id = session.get('user_line_id')
    if db is None:
        return jsonify([])

    cursor = db.pickups.find({"lineId": line_id}).sort("pickupDate", -1)
    results = []
    today = get_tw_now().replace(hour=0, minute=0, second=0, microsecond=0)

    for doc in cursor:
        is_deletable = False
        try:
            p_date = datetime.strptime(doc.get('pickupDate'), '%Y-%m-%d')
            if today < p_date:
                is_deletable = True
        except Exception:
            is_deletable = False

        results.append({
            "_id": str(doc['_id']),
            "pickupType": doc.get('pickupType'),
            "pickupDate": doc.get('pickupDate'),
            "clothes": doc.get('clothes', []),
            "createdAt": doc['createdAt'].strftime('%Y-%m-%d %H:%M') if 'createdAt' in doc else '',
            "isDeletable": is_deletable
        })
    return jsonify(results)


@user_bp.route('/api/user/orders', methods=['GET'])
def get_user_orders():
    line_id = session.get('user_line_id')
    if not line_id or db is None:
        return jsonify([])

    cursor = db.orders.find({"lineId": line_id, "orderType": "shop"}).sort("createdAt", -1)
    results = []
    for doc in cursor:
        tw_created = doc['createdAt'] + timedelta(hours=8)
        tw_deadline = doc.get('paymentDeadline', doc['createdAt'] + timedelta(hours=2)) + timedelta(hours=8)
        results.append({
            "_id": str(doc['_id']),
            "orderId": doc['orderId'],
            "items": doc.get('items', []),
            "total": doc.get('total', 0),
            "status": doc.get('status', 'pending'),
            "trackingNumber": doc.get('trackingNumber', ''),
            "createdAt": tw_created.strftime('%Y-%m-%d %H:%M'),
            "paymentDeadline": tw_deadline.strftime('%Y-%m-%d %H:%M'),
            "deadline_iso": tw_deadline.isoformat()
        })
    return jsonify(results)


@user_bp.route('/api/user/donations', methods=['GET'])
def get_user_donations():
    line_id = session.get('user_line_id')
    if not line_id or db is None:
        return jsonify([])

    cursor = db.orders.find({"lineId": line_id, "orderType": {"$in": ["donation", "fund", "committee"]}}).sort("createdAt", -1)
    results = []
    for doc in cursor:
        tw_created = doc['createdAt'] + timedelta(hours=8)
        tw_deadline = doc.get('paymentDeadline', doc['createdAt'] + timedelta(hours=2)) + timedelta(hours=8)
        results.append({
            "_id": str(doc['_id']),
            "orderType": doc.get('orderType', 'donation'),
            "orderId": doc['orderId'],
            "items": doc.get('items', []),
            "total": doc.get('total', 0),
            "status": doc.get('status', 'pending'),
            "is_reported": doc.get('is_reported', False),
            "createdAt": tw_created.strftime('%Y-%m-%d %H:%M'),
            "paymentDeadline": tw_deadline.strftime('%Y-%m-%d %H:%M'),
            "deadline_iso": tw_deadline.isoformat()
        })
    return jsonify(results)


@user_bp.route('/api/user/fund-summary', methods=['GET'])
@user_login_required
def get_user_fund_summary():
    line_id = session.get('user_line_id')
    if db is None:
        return jsonify([])

    cursor = db.orders.find({"lineId": line_id, "orderType": "fund", "status": "paid"})
    summary_dict = defaultdict(int)
    for doc in cursor:
        customer = doc.get('customer', {})
        raw_name = customer.get('name', '未具名')
        clean_name = raw_name.replace(" ", "").replace("　", "")
        if not clean_name:
            continue
        summary_dict[clean_name] += doc.get('total', 0)

    results = [{"name": name, "total": total} for name, total in summary_dict.items()]
    results.sort(key=lambda x: x['total'], reverse=True)
    return jsonify(results)
