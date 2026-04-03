from datetime import datetime

from bson import ObjectId
from flask import Blueprint, jsonify, request

from database import db
from utils.decorators import login_required
from utils.helpers import get_object_id

admin_bp = Blueprint('admin', __name__)


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
    """Step 4: 萬能單據查詢 — 依單號前綴路由至對應 collection"""
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

    # 序列化 ObjectId 與 datetime 為 JSON 安全字串
    def serialize(obj):
        if isinstance(obj, dict):
            return {k: serialize(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [serialize(v) for v in obj]
        if isinstance(obj, ObjectId):
            return str(obj)
        if isinstance(obj, datetime):
            return obj.isoformat()
        return obj

    return jsonify(serialize(doc))


@admin_bp.route('/api/admin/receipt/<receipt_id>', methods=['PUT'])
@login_required
def update_receipt(receipt_id):
    """Step 4: 萬能單據修改 — 以 $set 安全更新，保護 _id"""
    if db is None:
        return jsonify({"error": "資料庫未連線"}), 500

    clean_id = receipt_id.strip().upper()
    data = request.get_json()
    if not data:
        return jsonify({"error": "未收到 JSON 資料"}), 400

    # 移除 _id 防止 MongoDB 報錯
    data.pop('_id', None)

    if clean_id.startswith('FB'):
        result = db.feedback.update_one({"feedbackId": clean_id}, {"$set": data})
    elif clean_id.startswith(('ORD', 'DON', 'FND', 'COM')):
        result = db.orders.update_one({"orderId": clean_id}, {"$set": data})
    else:
        return jsonify({"error": f"無法識別的單號格式：{clean_id}"}), 400

    if result.matched_count == 0:
        return jsonify({"error": f"找不到單號：{clean_id}"}), 404

    return jsonify({"success": True, "message": f"單據 {clean_id} 已更新成功"})


@admin_bp.route('/api/admin/receipt/<receipt_id>', methods=['DELETE'])
@login_required
def force_delete_receipt(receipt_id):
    if db is None:
        return jsonify({"error": "資料庫未連線"}), 500

    clean_id = receipt_id.strip().upper()

    if clean_id.startswith('FB'):
        result = db.feedback.delete_one({"feedbackId": clean_id})
        if result.deleted_count > 0:
            return jsonify({"success": True, "message": f"已成功刪除回饋單：{clean_id}"})
        else:
            return jsonify({"error": f"找不到回饋單號：{clean_id}"}), 404

    elif clean_id.startswith(('ORD', 'DON', 'FND', 'COM')):
        result = db.orders.delete_one({"orderId": clean_id})
        if result.deleted_count > 0:
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
