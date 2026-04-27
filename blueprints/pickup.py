from collections import defaultdict
import logging
from datetime import datetime, timedelta
from utils.line_bot import send_admin_notification
from flask import Blueprint, jsonify, request, session
from database import db
from utils.decorators import user_login_required
from utils.helpers import get_tw_now, get_object_id, mask_name
from utils.security import as_string, get_json_object
from utils.timezone import utc_now

pickup_bp = Blueprint('pickup', __name__)
logger = logging.getLogger(__name__)


@pickup_bp.route('/api/pickup/reserve', methods=['POST'])
@user_login_required
def create_pickup_reservation():
    line_id = session.get('user_line_id')
    data = get_json_object()
    pickup_type = as_string(data.get('pickupType')).strip()
    pickup_date = as_string(data.get('pickupDate')).strip()
    clothes = data.get('clothes', [])

    if not isinstance(clothes, list):
        clothes = []

    normalized_clothes = []
    for item in clothes[:100]:
        if not isinstance(item, dict):
            continue
        normalized_clothes.append({
            "clothId": as_string(item.get('clothId')).strip(),
            "name": as_string(item.get('name')).strip(),
            "birthYear": as_string(item.get('birthYear')).strip(),
        })
    clothes = normalized_clothes

    if not pickup_type or not pickup_date or not clothes:
        return jsonify({"error": "資料不完整"}), 400

    incoming_ids = [c.get('clothId', '').strip() for c in clothes if c.get('clothId')]
    if not incoming_ids:
        return jsonify({"error": "請至少填寫一個衣服編號"}), 400

    if db is not None:
        today_str = get_tw_now().strftime('%Y-%m-%d')

        duplicate_order = db.pickups.find_one({
            "clothes.clothId": {"$in": incoming_ids},
            "pickupDate": {"$gte": today_str}
        }, {"clothes.clothId": 1})

        if duplicate_order:
            found_id = ""
            for item in duplicate_order.get('clothes', []):
                if item.get('clothId') in incoming_ids:
                    found_id = item.get('clothId')
                    break
            error_msg = f"衣服編號【{found_id}】目前的預約尚未過期！如需重新安排，請先至「個人專區」刪除舊紀錄。"
            return jsonify({"error": error_msg}), 400

    new_reservation = {
        "lineId": line_id,
        "pickupType": pickup_type,
        "pickupDate": pickup_date,
        "clothes": clothes,
        "createdAt": utc_now()
    }

    if db is not None:
        db.pickups.insert_one(new_reservation)
        # 👇👇👇 從這裡開始是新增的推播邏輯 👇👇👇
        try:
            cloth_count = len(clothes)
            notify_msg = (
                f"🔔 收到一筆新的寄衣服預約！\n"
                f"-------------------\n"
                f"📍 方式：{pickup_type}\n"
                f"📅 日期：{pickup_date}\n"
                f"👕 件數：共 {cloth_count} 件\n"
                f"-------------------\n"
                f"請記得到後台確認喔！"
            )
            send_admin_notification(notify_msg)
        except Exception:
            # 即使推播失敗，也不要影響使用者預約成功的流程
            logger.exception("Pickup notification failed", extra={"event": "pickup_notification_failed"})
        # 👆👆👆 新增結束 👆👆👆

        return jsonify({"success": True, "message": "預約成功"})

    return jsonify({"error": "資料庫連線失敗"}), 500


@pickup_bp.route('/api/pickup/public', methods=['GET'])
def get_public_pickups():
    if db is None:
        return jsonify([])

    threshold_date = (get_tw_now() - timedelta(days=1)).strftime('%Y-%m-%d')
    projection = {
        "pickupDate": 1,
        "pickupType": 1,
        "clothes.clothId": 1,
        "clothes.name": 1,
        "clothes.birthYear": 1,
    }
    cursor = db.pickups.find(
        {"pickupDate": {"$gte": threshold_date}},
        projection,
    ).sort("pickupDate", 1)

    results = defaultdict(lambda: {'self': [], 'delivery': []})

    for doc in cursor:
        date_str = doc['pickupDate']
        p_type = doc['pickupType']

        masked_clothes = []
        for c in doc.get('clothes', []):
            masked_clothes.append({
                "clothId": c.get('clothId', ''),
                "name": mask_name(c.get('name', '')),
                "birthYear": c.get('birthYear', '')
            })

        if masked_clothes:
            results[date_str][p_type].append({"clothes": masked_clothes})

    formatted_results = []
    for d in sorted(results.keys()):
        formatted_results.append({
            "date": d,
            "self": results[d]['self'],
            "delivery": results[d]['delivery']
        })

    return jsonify(formatted_results)


@pickup_bp.route('/api/pickup/<pid>', methods=['DELETE'])
@user_login_required
def delete_pickup(pid):
    line_id = session.get('user_line_id')
    oid = get_object_id(pid)
    if not oid:
        return jsonify({"error": "格式錯誤"}), 400

    pickup = db.pickups.find_one({"_id": oid, "lineId": line_id})
    if not pickup:
        return jsonify({"error": "找不到預約"}), 404

        try:
            p_date = datetime.strptime(pickup.get('pickupDate'), '%Y-%m-%d').date()
            today = get_tw_now().date()

            if today >= p_date:
                return jsonify({"error": "已超過取消期限 (限取件日前一天)"}), 400
    except Exception:
        return jsonify({"error": "日期資料異常"}), 400

    db.pickups.delete_one({"_id": oid})
    return jsonify({"success": True})
