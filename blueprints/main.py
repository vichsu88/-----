from datetime import datetime, timedelta

from flask import Blueprint, jsonify, redirect, render_template, url_for

from database import db

main_bp = Blueprint('main', __name__)


@main_bp.app_context_processor
def inject_links():
    if db is None:
        return dict(links={})
    try:
        links_cursor = db.links.find({})
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
            cursor = db.announcements.find().sort([("isPinned", -1), ("date", -1)]).limit(10)
            for doc in cursor:
                doc['_id'] = str(doc['_id'])
                if 'date' in doc and isinstance(doc['date'], datetime):
                    doc['date'] = doc['date'].strftime('%Y/%m/%d')
                announcements_data.append(doc)
    except Exception as e:
        print(f"SSR Error (Home): {e}")
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


@main_bp.route('/api/committee/status', methods=['GET'])
def get_committee_status():
    if db is None:
        return jsonify({})

    def get_remain(name, max_limit):
        used = db.orders.count_documents({
            "orderType": "committee",
            "status": {"$in": ["paid", "pending"]},
            "items.name": name
        })
        return max(0, max_limit - used)

    return jsonify({
        "hon_main": get_remain('[本府] 主委', 1),
        "hon_vice": get_remain('[本府] 副主委', 7),
        "bld_main": get_remain('[建廟] 籌備主委', 1),
        "bld_vice": 0
    })


@main_bp.route('/feedback')
def feedback_page():
    feedbacks_data = []
    try:
        if db is not None:
            cursor = db.feedback.find({"status": "approved"}).sort("approvedAt", -1).limit(20)
            for doc in cursor:
                feedbacks_data.append({
                    'feedbackId': doc.get('feedbackId', ''),
                    'nickname': doc.get('nickname', '匿名'),
                    'content': doc.get('content', ''),
                    'category': doc.get('category', [])
                })
    except Exception as e:
        print(f"SSR Error (Feedback): {e}")
    return render_template('feedback.html', feedbacks=feedbacks_data)


@main_bp.route('/faq')
def faq_page():
    faq_data = []
    try:
        if db is not None:
            cursor = db.faq.find().sort([('isPinned', -1), ('createdAt', -1)])
            for doc in cursor:
                doc['_id'] = str(doc['_id'])
                faq_data.append(doc)
    except Exception as e:
        print(f"SSR Error (FAQ): {e}")
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
