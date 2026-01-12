# --- app.py (完整修正版 - 含年次、衣服主人隱碼) ---
import os
import re
import random
from functools import wraps
from datetime import datetime, timedelta
from flask import Flask, jsonify, render_template, request, session, redirect, url_for, Response
from flask_cors import CORS
from flask_wtf.csrf import CSRFProtect
from pymongo import MongoClient
from bson import ObjectId
from dotenv import load_dotenv
from werkzeug.security import check_password_hash
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# --- 1. 應用程式初始化與設定 ---
load_dotenv()
app = Flask(__name__)

# 安全性設定
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', os.urandom(24))
is_production = os.environ.get('RENDER') is not None
app.config['SESSION_COOKIE_SECURE'] = is_production
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.permanent_session_lifetime = timedelta(hours=8)

# 流量限制
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["2000 per day", "500 per hour"],
    storage_uri="memory://"
)

# CSRF & CORS
csrf = CSRFProtect(app)
CORS(app, resources={r"/api/*": {"origins": "*"}}, supports_credentials=True)

# 管理員密碼
ADMIN_PASSWORD_HASH = os.environ.get('ADMIN_PASSWORD_HASH')

# --- 2. 資料庫連線 ---
MONGO_URI = os.environ.get('MONGO_URI')
db = None
try:
    if MONGO_URI:
        client = MongoClient(MONGO_URI)
        db = client['ChentienTempleDB']
        print("--- MongoDB 連線成功 ---")
    else:
        print("--- 警告：未找到 MONGO_URI ---")
except Exception as e:
    print(f"--- MongoDB 連線失敗: {e} ---")

# --- 3. 工具函式 ---
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'logged_in' not in session:
            if request.path.startswith('/api/'):
                return jsonify({"error": "未授權，請先登入"}), 403
            return redirect(url_for('admin_page'))
        return f(*args, **kwargs)
    return decorated_function

def calculate_business_d2(start_date):
    """計算 D+2 工作日 (跳過週六日)"""
    current = start_date
    added_days = 0
    while added_days < 2:
        current += timedelta(days=1)
        if current.weekday() < 5: # 0-4 是週一到週五
            added_days += 1
    return current

def mask_name(real_name):
    """姓名隱碼處理 (第二字變O)"""
    if not real_name: return ""
    if len(real_name) >= 3:
        return real_name[0] + "O" + real_name[2:]
    elif len(real_name) == 2:
        return real_name[0] + "O"
    return real_name

@app.context_processor
def inject_links():
    if db is None: return dict(links={})
    try:
        links_cursor = db.links.find({})
        links_dict = {link['name']: link['url'] for link in links_cursor}
        return dict(links=links_dict)
    except: return dict(links={})

# --- 4. 前台頁面路由 ---
@app.route('/')
def home(): return render_template('index.html')

@app.route('/services')
def services_page(): return render_template('services.html')

@app.route('/shipclothes')
def ship_clothes_page(): return render_template('shipclothes.html')

@app.route('/gongtan')
def gongtan_page(): return redirect(url_for('services_page', _anchor='gongtan-section'))
@app.route('/shoujing')
def shoujing_page(): return redirect(url_for('services_page', _anchor='shoujing-section'))

@app.route('/products/incense')
def incense_page(): return render_template('incense.html')
@app.route('/products/skincare')
def skincare_page(): return render_template('index.html')
@app.route('/products/yuan-shuai-niang')
def yuan_user_page(): return render_template('index.html')
@app.route('/donation')
def donation_page(): return render_template('index.html')
@app.route('/fund')
def fund_page(): return render_template('index.html')

@app.route('/feedback')
def feedback_page(): return render_template('feedback.html')
@app.route('/faq')
def faq_page(): return render_template('faq.html')

# --- 5. 後台頁面路由 ---
@app.route('/admin')
def admin_page(): return render_template('admin.html')

# --- 6. API: 認證系統 ---
@app.route('/api/session_check', methods=['GET'])
def session_check():
    return jsonify({"logged_in": session.get('logged_in', False)})

@csrf.exempt
@app.route('/api/login', methods=['POST'])
@limiter.limit("5 per minute")
def api_login():
    password = request.json.get('password')
    if ADMIN_PASSWORD_HASH and check_password_hash(ADMIN_PASSWORD_HASH, password):
        session['logged_in'] = True
        session.permanent = True
        return jsonify({"success": True, "message": "登入成功"})
    return jsonify({"success": False, "message": "密碼錯誤"}), 401

@app.route('/api/logout', methods=['POST'])
def api_logout():
    session.pop('logged_in', None)
    return jsonify({"success": True})

# --- 7. API: 信徒回饋 ---
@app.route('/api/feedback', methods=['POST'])
def add_feedback():
    if db is None: return jsonify({"error": "資料庫未連線"}), 500
    data = request.get_json()
    if not data.get('agreed'): return jsonify({"error": "必須勾選同意條款"}), 400

    new_feedback = {
        "realName": data.get('realName'), "nickname": data.get('nickname'),
        "category": data.get('category', []), "content": data.get('content'),
        "lunarBirthday": data.get('lunarBirthday', ''), "birthTime": data.get('birthTime') or '吉時',
        "address": data.get('address', ''), "phone": data.get('phone', ''),
        "agreed": True, "createdAt": datetime.utcnow(), "status": "pending", "isMarked": False
    }
    db.feedback.insert_one(new_feedback)
    return jsonify({"success": True, "message": "回饋已送出"})

@app.route('/api/feedback/pending', methods=['GET'])
@login_required
def get_pending_feedback():
    if db is None: return jsonify({"error": "DB Error"}), 500
    cursor = db.feedback.find({"status": "pending"}).sort("createdAt", 1)
    return jsonify([{**doc, '_id': str(doc['_id']), 'createdAt': doc['createdAt'].strftime('%Y-%m-%d %H:%M:%S')} for doc in cursor])

@app.route('/api/feedback/approved', methods=['GET'])
@login_required
def get_approved_feedback():
    if db is None: return jsonify({"error": "DB Error"}), 500
    cursor = db.feedback.find({"status": "approved"}).sort("createdAt", -1)
    return jsonify([{**doc, '_id': str(doc['_id']), 'createdAt': doc['createdAt'].strftime('%Y-%m-%d %H:%M:%S')} for doc in cursor])

@app.route('/api/feedback/<fid>', methods=['PUT'])
@login_required
def update_feedback(fid):
    data = request.get_json()
    fields = {k: data.get(k) for k in ['realName', 'nickname', 'category', 'content', 'lunarBirthday', 'birthTime', 'address', 'phone']}
    db.feedback.update_one({'_id': ObjectId(fid)}, {'$set': fields})
    return jsonify({"success": True})

@app.route('/api/feedback/<fid>/approve', methods=['PUT'])
@login_required
def approve_feedback(fid):
    db.feedback.update_one({'_id': ObjectId(fid)}, {'$set': {'status': 'approved'}})
    return jsonify({"success": True})

@app.route('/api/feedback/<fid>', methods=['DELETE'])
@login_required
def delete_feedback(fid):
    db.feedback.delete_one({'_id': ObjectId(fid)})
    return jsonify({"success": True})

@app.route('/api/feedback/<fid>/mark', methods=['PUT'])
@login_required
def mark_feedback(fid):
    data = request.get_json()
    db.feedback.update_one({'_id': ObjectId(fid)}, {'$set': {'isMarked': data.get('isMarked', False)}})
    return jsonify({"success": True})

@app.route('/api/feedback/mark-all-approved', methods=['PUT'])
@login_required
def mark_all_approved_feedback():
    db.feedback.update_many({'status': 'approved'}, {'$set': {'isMarked': True}})
    return jsonify({"success": True})

@app.route('/api/feedback/download-unmarked', methods=['POST'])
@login_required
def download_unmarked_feedback():
    if db is None: return jsonify({"error": "DB Error"}), 500
    cursor = db.feedback.find({"status": "approved", "isMarked": False}).sort("address", 1)
    feedback_list = list(cursor)
    if not feedback_list: return jsonify({"error": "無新資料"}), 404

    text = f"匯出時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n{'='*30}\n\n"
    ids = []
    for i, doc in enumerate(feedback_list, 1):
        ids.append(doc['_id'])
        text += f"【{i}】\n姓名: {doc.get('realName')}\n電話: {doc.get('phone')}\n地址: {doc.get('address')}\n"
        text += f"生日: {doc.get('lunarBirthday')} ({doc.get('birthTime')})\n"
        text += f"內容: {doc.get('content')[:50]}...\n{'-'*20}\n\n"
    db.feedback.update_many({'_id': {'$in': ids}}, {'$set': {'isMarked': True}})
    return Response(text, mimetype='text/plain', headers={"Content-Disposition": f"attachment;filename=list_{datetime.now().strftime('%Y%m%d')}.txt"})

# --- 8. API: 收驚衣物寄回功能 (ShipClothes) ---

@app.route('/api/shipclothes/calc-date', methods=['GET'])
def get_pickup_date_preview():
    today = datetime.utcnow() + timedelta(hours=8)
    pickup_date = calculate_business_d2(today)
    return jsonify({"pickupDate": pickup_date.strftime('%Y/%m/%d (%a)')})

@app.route('/api/captcha', methods=['GET'])
def get_captcha():
    num1 = random.randint(1, 10)
    num2 = random.randint(1, 10)
    session['captcha_answer'] = str(num1 + num2)
    return jsonify({"question": f"{num1} + {num2} = ?"})

@app.route('/api/shipclothes', methods=['POST'])
def submit_ship_clothes():
    if db is None: return jsonify({"success": False, "message": "資料庫未連線"}), 500
    data = request.get_json()
    
    # 1. 驗證碼
    user_captcha = data.get('captcha', '').strip()
    correct_answer = session.get('captcha_answer')
    session.pop('captcha_answer', None)
    if not correct_answer or user_captcha != correct_answer:
        return jsonify({"success": False, "message": "驗證碼錯誤"}), 400

    # 2. 必填檢查 (含 birthYear)
    if not all(k in data and data[k] for k in ['name', 'lineGroup', 'lineName', 'birthYear', 'clothes']):
        return jsonify({"success": False, "message": "所有欄位皆為必填"}), 400

    now_tw = datetime.utcnow() + timedelta(hours=8)
    pickup_date = calculate_business_d2(now_tw)

    # 3. 儲存資料
    submission = {
        "name": data['name'],
        "birthYear": data['birthYear'], # 新增年次
        "lineGroup": data['lineGroup'],
        "lineName": data['lineName'],
        "clothes": data['clothes'], # 格式: [{'id': 'A01', 'owner': '王小明'}, ...]
        "submitDate": now_tw,
        "submitDateStr": now_tw.strftime('%Y/%m/%d'),
        "pickupDate": pickup_date,
        "pickupDateStr": pickup_date.strftime('%Y/%m/%d')
    }
    
    db.shipments.insert_one(submission)
    return jsonify({
        "success": True, 
        "pickupDate": pickup_date.strftime('%Y/%m/%d')
    })

@app.route('/api/shipclothes/list', methods=['GET'])
def get_ship_clothes_list():
    if db is None: return jsonify([]), 500
    
    now_tw = datetime.utcnow() + timedelta(hours=8)
    today_date = now_tw.replace(hour=0, minute=0, second=0, microsecond=0)
    start_date = today_date - timedelta(days=1)
    end_date = today_date + timedelta(days=5)
    
    try:
        cursor = db.shipments.find({
            "pickupDate": { "$gte": start_date, "$lte": end_date }
        }).sort("pickupDate", 1)

        results = []
        for doc in cursor:
            # 處理寄件人隱碼
            masked_sender = mask_name(doc['name'])
            
            # 處理衣服主人隱碼
            masked_clothes = []
            for item in doc.get('clothes', []):
                masked_clothes.append({
                    'id': item.get('id', ''),
                    'owner': mask_name(item.get('owner', '')) # 主人姓名隱碼
                })

            results.append({
                "name": masked_sender,
                "birthYear": doc.get('birthYear', ''),
                "lineGroup": doc['lineGroup'],
                "lineName": doc.get('lineName', ''),
                "clothes": masked_clothes,
                "submitDate": doc['submitDateStr'],
                "pickupDate": doc['pickupDateStr']
            })
            
        return jsonify(results)
    except Exception as e: return jsonify({"error": str(e)}), 500

# --- 9. API: 商品與其他管理 (略 - 維持原樣) ---
@app.route('/api/products', methods=['GET'])
@login_required
def get_products():
    if db is None: return jsonify({"error": "DB Error"}), 500
    products = list(db.products.find().sort([("category", 1), ("createdAt", -1)]))
    for p in products: p['_id'] = str(p['_id'])
    return jsonify(products)

@app.route('/api/products', methods=['POST'])
@login_required
def add_product():
    if db is None: return jsonify({"error": "DB Error"}), 500
    data = request.get_json()
    new_product = {
        "name": data.get('name'), "category": data.get('category', '其他'),
        "price": int(data.get('price', 0)), "description": data.get('description', ''),
        "image": data.get('image', ''), "isActive": data.get('isActive', True),
        "createdAt": datetime.utcnow()
    }
    db.products.insert_one(new_product)
    return jsonify({"success": True})

@app.route('/api/products/<pid>', methods=['PUT'])
@login_required
def update_product(pid):
    data = request.get_json()
    fields = {k: data.get(k) for k in ['name', 'category', 'price', 'description', 'image', 'isActive'] if k in data}
    if 'price' in fields: fields['price'] = int(fields['price'])
    db.products.update_one({'_id': ObjectId(pid)}, {'$set': fields})
    return jsonify({"success": True})

@app.route('/api/products/<pid>', methods=['DELETE'])
@login_required
def delete_product(pid):
    db.products.delete_one({'_id': ObjectId(pid)})
    return jsonify({"success": True})

@app.route('/api/announcements', methods=['GET'])
def get_announcements():
    cursor = db.announcements.find().sort([("isPinned", -1), ("_id", -1)])
    results = []
    for doc in cursor:
        doc['_id'] = str(doc['_id'])
        if 'date' in doc and isinstance(doc['date'], datetime): doc['date'] = doc['date'].strftime('%Y/%m/%d')
        results.append(doc)
    return jsonify(results)

@app.route('/api/announcements', methods=['POST'])
@login_required
def add_announcement():
    data = request.get_json()
    date_obj = datetime.strptime(data['date'], '%Y/%m/%d')
    db.announcements.insert_one({
        "date": date_obj, "title": data['title'], "content": data['content'],
        "isPinned": data.get('isPinned', False), "createdAt": datetime.utcnow()
    })
    return jsonify({"success": True})

@app.route('/api/announcements/<aid>', methods=['DELETE'])
@login_required
def delete_announcement(aid):
    db.announcements.delete_one({'_id': ObjectId(aid)})
    return jsonify({"success": True})

@app.route('/api/faq', methods=['GET'])
def get_faqs():
    query = {'category': request.args.get('category')} if request.args.get('category') else {}
    faqs = db.faq.find(query).sort([('isPinned', -1), ('createdAt', -1)])
    return jsonify([{**doc, '_id': str(doc['_id']), 'createdAt': doc['createdAt'].strftime('%Y-%m-%d')} for doc in faqs])

@app.route('/api/faq/categories', methods=['GET'])
def get_faq_categories(): return jsonify(db.faq.distinct('category'))

@app.route('/api/faq', methods=['POST'])
@login_required
def add_faq():
    data = request.get_json()
    db.faq.insert_one({
        "question": data['question'], "answer": data['answer'], "category": data['category'],
        "isPinned": data.get('isPinned', False), "createdAt": datetime.utcnow()
    })
    return jsonify({"success": True})

@app.route('/api/faq/<fid>', methods=['DELETE'])
@login_required
def delete_faq(fid):
    db.faq.delete_one({'_id': ObjectId(fid)})
    return jsonify({"success": True})

@app.route('/api/fund-settings', methods=['GET'])
def get_fund_settings():
    settings = db.temple_fund.find_one({"type": "main_fund"}) or {"goal_amount": 10000000, "current_amount": 0}
    if '_id' in settings: settings['_id'] = str(settings['_id'])
    return jsonify(settings)

@app.route('/api/fund-settings', methods=['POST'])
@login_required
def update_fund_settings():
    data = request.get_json()
    db.temple_fund.update_one(
        {"type": "main_fund"},
        {"$set": {"goal_amount": int(data.get('goal_amount', 0)), "current_amount": int(data.get('current_amount', 0))}},
        upsert=True
    )
    return jsonify({"success": True})

@app.route('/api/links', methods=['GET'])
def get_links():
    return jsonify([{**l, '_id': str(l['_id'])} for l in db.links.find({})])

@app.route('/api/links/<lid>', methods=['PUT'])
@login_required
def update_link(lid):
    data = request.get_json()
    db.links.update_one({'_id': ObjectId(lid)}, {'$set': {'url': data['url']}})
    return jsonify({"success": True})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)