import logging
from datetime import datetime, timedelta

from flask import Blueprint, jsonify, redirect, render_template, url_for

from database import db

main_bp = Blueprint('main', __name__)
logger = logging.getLogger(__name__)

LINK_PROJECTION = {"name": 1, "url": 1}
HOME_ANNOUNCEMENT_PROJECTION = {"date": 1, "title": 1, "content": 1, "isPinned": 1}
FEEDBACK_PROJECTION = {"feedbackId": 1, "nickname": 1, "content": 1, "category": 1}
FAQ_PROJECTION = {"question": 1, "answer": 1, "category": 1, "isPinned": 1, "createdAt": 1}


@main_bp.app_context_processor
def inject_links():
    if db is None:
        return dict(links={})
    try:
        links_cursor = db.links.find({}, LINK_PROJECTION)
        links_dict = {link['name']: link['url'] for link in links_cursor}
        return dict(links=links_dict)
    except Exception:
        return dict(links={})


@main_bp.route('/profile')
def profile_page():
    return render_template('profile.html')


@main_bp.route('/')
def home():
    announcements_data = []
    try:
        if db is not None:
            cursor = db.announcements.find(
                {},
                HOME_ANNOUNCEMENT_PROJECTION,
            ).sort([("isPinned", -1), ("date", -1)]).limit(10)
            for doc in cursor:
                doc['_id'] = str(doc['_id'])
                if 'date' in doc and isinstance(doc['date'], datetime):
                    doc['date'] = doc['date'].strftime('%Y/%m/%d')
                announcements_data.append(doc)
    except Exception:
        logger.exception("SSR home data failed", extra={"event": "ssr_home_failed"})
    return render_template('index.html', announcements=announcements_data)


@main_bp.route('/services')
def services_page():
    return render_template('services.html')


@main_bp.route('/shipclothes')
def ship_clothes_page():
    return render_template('shipclothes.html')


@main_bp.route('/shop')
def shop_page():
    return render_template('shop.html')


@main_bp.route('/donation')
def donation_page():
    return render_template('donation.html')


@main_bp.route('/fund')
def fund_page():
    return render_template('fund.html')


@main_bp.route('/committee')
def committee_page():
    return render_template('committee.html')


@main_bp.route('/api/public/committee-status', methods=['GET'])
def get_public_committee_status():
    if db is None:
        return jsonify([])

    # 取得後台設定
    setting = db.settings.find_one({"type": "committee_quota"}, {"roles": 1})
    roles = setting.get("roles", []) if setting else []
    role_names = [role.get('name') for role in roles if role.get('name')]

    used_counts = {}
    if role_names:
        pipeline = [
            {"$match": {
                "orderType": "committee",
                "status": {"$in": ["paid", "pending"]},
                "items.name": {"$in": role_names},
            }},
            {"$unwind": "$items"},
            {"$match": {"items.name": {"$in": role_names}}},
            {"$group": {"_id": "$items.name", "used": {"$sum": 1}}},
        ]
        used_counts = {
            item["_id"]: item["used"]
            for item in db.orders.aggregate(pipeline)
            if item.get("_id")
        }

    results = []
    for role in roles:
        name = role.get('name')
        limit = role.get('limit', 0)
        # 計算已佔用名額
        used = used_counts.get(name, 0)
        results.append({
            "name": name,
            "remaining": max(0, limit - used),
            "price": role.get('price', 0) # 傳回後台設定的金額
        })
    return jsonify(results)


@main_bp.route('/feedback')
def feedback_page():
    feedbacks_data = []
    try:
        if db is not None:
            cursor = db.feedback.find({"status": "approved"}, FEEDBACK_PROJECTION).sort("approvedAt", -1).limit(20)
            for doc in cursor:
                feedbacks_data.append({
                    'feedbackId': doc.get('feedbackId', ''),
                    'nickname': doc.get('nickname', '匿名'),
                    'content': doc.get('content', ''),
                    'category': doc.get('category', [])
                })
    except Exception:
        logger.exception("SSR feedback data failed", extra={"event": "ssr_feedback_failed"})
    return render_template('feedback.html', feedbacks=feedbacks_data)


@main_bp.route('/faq')
def faq_page():
    faq_data = []
    try:
        if db is not None:
            cursor = db.faq.find({}, FAQ_PROJECTION).sort([('isPinned', -1), ('createdAt', -1)])
            for doc in cursor:
                doc['_id'] = str(doc['_id'])
                faq_data.append(doc)
    except Exception:
        logger.exception("SSR FAQ data failed", extra={"event": "ssr_faq_failed"})
    return render_template('faq.html', faqs=faq_data)


@main_bp.route('/gongtan')
def gongtan_page():
    return redirect(url_for('main.services_page', _anchor='gongtan-section'))


@main_bp.route('/shoujing')
def shoujing_page():
    return redirect(url_for('main.services_page', _anchor='shoujing-section'))


@main_bp.route('/products/incense')
def incense_page():
    return redirect(url_for('main.shop_page'))


@main_bp.route('/products/skincare')
def skincare_page():
    return redirect(url_for('main.shop_page'))


@main_bp.route('/products/yuan-shuai-niang')
def yuan_user_page():
    return redirect(url_for('main.shop_page'))
