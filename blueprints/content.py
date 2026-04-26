import re
from datetime import datetime, timedelta, timezone

from flask import Blueprint, jsonify, request, session, Response

from database import db
from utils.decorators import admin_required
from utils.helpers import get_object_id, get_tw_now, calculate_business_d2, mask_name
from utils.security import as_string, get_json_object

content_bp = Blueprint('content', __name__)


def _to_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _to_bool(value, default=False):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ('1', 'true', 'yes', 'on')
    return default


def _clean_variants(variants):
    if not isinstance(variants, list):
        return []
    cleaned = []
    for item in variants[:50]:
        if not isinstance(item, dict):
            continue
        cleaned.append({
            "name": as_string(item.get('name')).strip(),
            "price": _to_int(item.get('price'), 0),
        })
    return cleaned


# --- ShipClothes ---

@content_bp.route('/api/shipclothes/calc-date', methods=['GET'])
def get_pickup_date_preview():
    pickup_date = calculate_business_d2(get_tw_now())
    return jsonify({"pickupDate": pickup_date.strftime('%Y/%m/%d (%a)')})


@content_bp.route('/api/shipclothes', methods=['POST'])
def submit_ship_clothes():
    if db is None:
        return jsonify({"success": False, "message": "資料庫未連線"}), 500
    data = get_json_object()
    user_captcha = as_string(data.get('captcha')).strip()
    correct_answer = session.get('captcha_answer')
    session.pop('captcha_answer', None)

    if not correct_answer or user_captcha != correct_answer:
        return jsonify({"success": False, "message": "驗證碼錯誤"}), 400

    if not all(as_string(data.get(k)).strip() for k in ['name', 'lineGroup', 'lineName', 'birthYear']) or not isinstance(data.get('clothes'), list):
        return jsonify({"success": False, "message": "所有欄位皆為必填"}), 400

    clothes = []
    for item in data.get('clothes', [])[:100]:
        if not isinstance(item, dict):
            continue
        clothes.append({
            "id": as_string(item.get('id')).strip(),
            "owner": as_string(item.get('owner')).strip(),
        })
    if not clothes:
        return jsonify({"success": False, "message": "所有欄位皆為必填"}), 400

    now_tw = get_tw_now()
    pickup_date = calculate_business_d2(now_tw)

    db.shipments.insert_one({
        "name": as_string(data.get('name')).strip(), "birthYear": as_string(data.get('birthYear')).strip(),
        "lineGroup": as_string(data.get('lineGroup')).strip(), "lineName": as_string(data.get('lineName')).strip(),
        "clothes": clothes, "submitDate": now_tw,
        "submitDateStr": now_tw.strftime('%Y/%m/%d'),
        "pickupDate": pickup_date, "pickupDateStr": pickup_date.strftime('%Y/%m/%d')
    })
    return jsonify({"success": True, "pickupDate": pickup_date.strftime('%Y/%m/%d')})


@content_bp.route('/api/shipclothes/list', methods=['GET'])
def get_ship_clothes_list():
    if db is None:
        return jsonify([]), 500
    today_date = get_tw_now().replace(hour=0, minute=0, second=0, microsecond=0)
    start_date = today_date - timedelta(days=1)
    end_date = today_date + timedelta(days=5)

    projection = {
        "name": 1,
        "birthYear": 1,
        "lineGroup": 1,
        "lineName": 1,
        "clothes": 1,
        "submitDateStr": 1,
        "pickupDateStr": 1,
    }
    cursor = db.shipments.find(
        {"pickupDate": {"$gte": start_date, "$lte": end_date}},
        projection,
    ).sort("pickupDate", 1)
    results = []
    for doc in cursor:
        masked_clothes = [{'id': i.get('id', ''), 'owner': mask_name(i.get('owner', ''))} for i in doc.get('clothes', [])]
        results.append({
            "name": mask_name(doc['name']), "birthYear": doc.get('birthYear', ''),
            "lineGroup": doc['lineGroup'], "lineName": doc.get('lineName', ''),
            "clothes": masked_clothes, "submitDate": doc['submitDateStr'], "pickupDate": doc['pickupDateStr']
        })
    return jsonify(results)


# --- Products ---

@content_bp.route('/api/products', methods=['GET'])
def get_products():
    products = list(db.products.find().sort([("category", 1), ("createdAt", -1)]))
    for p in products:
        p['_id'] = str(p['_id'])
    return jsonify(products)


@content_bp.route('/api/products', methods=['POST'])
@admin_required(roles=['super_admin', 'cms'])
def add_product():
    data = get_json_object()
    new_product = {
        "name": as_string(data.get('name')).strip(), "category": as_string(data.get('category'), '其他').strip(),
        "series": as_string(data.get('series')).strip(), "seriesSort": _to_int(data.get('seriesSort'), 0),
        "price": _to_int(data.get('price'), 0), "description": as_string(data.get('description')).strip(),
        "image": as_string(data.get('image')).strip(), "isActive": _to_bool(data.get('isActive'), True),
        "isDonation": _to_bool(data.get('isDonation'), False), "variants": _clean_variants(data.get('variants', [])),
        "createdAt": datetime.now(timezone.utc).replace(tzinfo=None)
    }
    db.products.insert_one(new_product)
    return jsonify({"success": True})


@content_bp.route('/api/products/<pid>', methods=['PUT'])
@admin_required(roles=['super_admin', 'cms'])
def update_product(pid):
    oid = get_object_id(pid)
    if not oid:
        return jsonify({"error": "無效的 ID 格式"}), 400

    data = get_json_object()
    fields = {k: data.get(k) for k in ['name', 'category', 'price', 'description', 'image', 'isActive', 'variants', 'isDonation', 'series', 'seriesSort'] if k in data}
    for key in ('name', 'category', 'description', 'image', 'series'):
        if key in fields:
            fields[key] = as_string(fields[key]).strip()
    if 'price' in fields: fields['price'] = _to_int(fields['price'], 0)
    if 'seriesSort' in fields: fields['seriesSort'] = _to_int(fields['seriesSort'], 0)
    if 'isActive' in fields: fields['isActive'] = _to_bool(fields['isActive'], True)
    if 'isDonation' in fields: fields['isDonation'] = _to_bool(fields['isDonation'], False)
    if 'variants' in fields: fields['variants'] = _clean_variants(fields['variants'])
    db.products.update_one({'_id': oid}, {'$set': fields})
    return jsonify({"success": True})


@content_bp.route('/api/products/<pid>', methods=['DELETE'])
@admin_required(roles=['super_admin', 'cms'])
def delete_product(pid):
    oid = get_object_id(pid)
    if not oid:
        return jsonify({"error": "無效的 ID 格式"}), 400

    db.products.delete_one({'_id': oid})
    return jsonify({"success": True})


# --- Announcements ---

@content_bp.route('/api/announcements', methods=['GET'])
def get_announcements():
    cursor = db.announcements.find(
        {},
        {"date": 1, "title": 1, "content": 1, "isPinned": 1, "createdAt": 1},
    ).sort([("isPinned", -1), ("_id", -1)])
    results = []
    for doc in cursor:
        doc['_id'] = str(doc['_id'])
        if 'date' in doc and isinstance(doc['date'], datetime):
            doc['date'] = doc['date'].strftime('%Y/%m/%d')
        results.append(doc)
    return jsonify(results)


@content_bp.route('/api/announcements', methods=['POST'])
@admin_required(roles=['super_admin', 'cms'])
def add_announcement():
    data = get_json_object()
    try:
        date_obj = datetime.strptime(as_string(data.get('date')).replace('-', '/'), '%Y/%m/%d')
    except ValueError:
        return jsonify({"error": "日期格式錯誤，請使用 YYYY/MM/DD"}), 400

    db.announcements.insert_one({
        "date": date_obj,
        "title": as_string(data.get('title')).strip(),
        "content": as_string(data.get('content')).strip(),
        "isPinned": _to_bool(data.get('isPinned'), False),
        "createdAt": datetime.now(timezone.utc).replace(tzinfo=None)
    })
    return jsonify({"success": True})


@content_bp.route('/api/announcements/<aid>', methods=['PUT'])
@admin_required(roles=['super_admin', 'cms'])
def update_announcement(aid):
    oid = get_object_id(aid)
    if not oid:
        return jsonify({"error": "無效的 ID 格式"}), 400

    data = get_json_object()
    try:
        date_obj = datetime.strptime(as_string(data.get('date')).replace('-', '/'), '%Y/%m/%d')
    except ValueError:
        return jsonify({"error": "日期格式錯誤"}), 400

    db.announcements.update_one({'_id': oid}, {'$set': {
        "date": date_obj,
        "title": as_string(data.get('title')).strip(),
        "content": as_string(data.get('content')).strip(),
        "isPinned": _to_bool(data.get('isPinned'), False)
    }})
    return jsonify({"success": True})


@content_bp.route('/api/announcements/<aid>', methods=['DELETE'])
@admin_required(roles=['super_admin', 'cms'])
def delete_announcement(aid):
    oid = get_object_id(aid)
    if not oid:
        return jsonify({"error": "無效的 ID 格式"}), 400

    db.announcements.delete_one({'_id': oid})
    return jsonify({"success": True})


# --- FAQ ---

@content_bp.route('/api/faq', methods=['GET'])
def get_faqs():
    category = as_string(request.args.get('category')).strip()
    query = {'category': category} if category else {}
    faqs = db.faq.find(
        query,
        {"question": 1, "answer": 1, "category": 1, "isPinned": 1, "createdAt": 1},
    ).sort([('isPinned', -1), ('createdAt', -1)])
    return jsonify([{**doc, '_id': str(doc['_id']), 'createdAt': doc['createdAt'].strftime('%Y-%m-%d')} for doc in faqs])


@content_bp.route('/api/faq/categories', methods=['GET'])
def get_faq_categories():
    return jsonify(db.faq.distinct('category'))


@content_bp.route('/api/faq', methods=['POST'])
@admin_required(roles=['super_admin', 'cms'])
def add_faq():
    data = get_json_object()
    category = as_string(data.get('category')).strip()
    if not re.match(r'^[\u4e00-\u9fff]+$', category):
        return jsonify({"error": "分類限中文"}), 400

    db.faq.insert_one({
        "question": as_string(data.get('question')).strip(), "answer": as_string(data.get('answer')).strip(), "category": category,
        "isPinned": _to_bool(data.get('isPinned'), False),
        "createdAt": datetime.now(timezone.utc).replace(tzinfo=None)
    })
    return jsonify({"success": True})


@content_bp.route('/api/faq/<fid>', methods=['PUT'])
@admin_required(roles=['super_admin', 'cms'])
def update_faq(fid):
    oid = get_object_id(fid)
    if not oid:
        return jsonify({"error": "無效的 ID 格式"}), 400

    data = get_json_object()
    db.faq.update_one({'_id': oid}, {'$set': {
        "question": as_string(data.get('question')).strip(), "answer": as_string(data.get('answer')).strip(),
        "category": as_string(data.get('category')).strip(), "isPinned": _to_bool(data.get('isPinned'), False)
    }})
    return jsonify({"success": True})


@content_bp.route('/api/faq/<fid>', methods=['DELETE'])
@admin_required(roles=['super_admin', 'cms'])
def delete_faq(fid):
    oid = get_object_id(fid)
    if not oid:
        return jsonify({"error": "無效的 ID 格式"}), 400

    db.faq.delete_one({'_id': oid})
    return jsonify({"success": True})


# --- Fund Settings ---

@content_bp.route('/api/fund-settings', methods=['GET'])
def get_fund_settings():
    settings = db.temple_fund.find_one({"type": "main_fund"}) or {"goal_amount": 10000000}

    pipeline = [
        {"$match": {"status": "paid", "orderType": "fund"}},
        {"$group": {"_id": None, "total_current": {"$sum": "$total"}}}
    ]

    if db is not None:
        result = list(db.orders.aggregate(pipeline))
        calculated_current = result[0]['total_current'] if result else 0

        vice_chair_used = db.orders.count_documents({
            "orderType": "fund",
            "status": {"$in": ["paid", "pending"]},
            "items.name": "副主委"
        })
        settings['vice_chair_remain'] = max(0, 7 - vice_chair_used)
    else:
        calculated_current = 0
        settings['vice_chair_remain'] = 7

    settings['current_amount'] = calculated_current
    if '_id' in settings:
        settings['_id'] = str(settings['_id'])
    return jsonify(settings)


@content_bp.route('/api/fund-settings', methods=['POST'])
@admin_required(roles=['super_admin', 'finance', 'cms'])
def update_fund_settings():
    data = get_json_object()
    db.temple_fund.update_one(
        {"type": "main_fund"},
        {"$set": {"goal_amount": _to_int(data.get('goal_amount'), 10000000)}},
        upsert=True
    )
    return jsonify({"success": True})


# --- Links ---

@content_bp.route('/api/links', methods=['GET'])
def get_links():
    return jsonify([{**l, '_id': str(l['_id'])} for l in db.links.find({})])


@content_bp.route('/api/links/<lid>', methods=['PUT'])
@admin_required(roles=['super_admin', 'cms'])
def update_link(lid):
    oid = get_object_id(lid)
    if not oid:
        return jsonify({"error": "無效的 ID 格式"}), 400

    data = get_json_object()
    db.links.update_one({'_id': oid}, {'$set': {'url': as_string(data.get('url')).strip()}})
    return jsonify({"success": True})
