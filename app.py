# --- app.py (完整整合版：含商城、訂單、寄衣、回饋、後台) ---
import os
import re
import random
import smtplib
from email.mime.text import MIMEText
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

# =========================================
# 1. 應用程式初始化與設定
# =========================================
load_dotenv()
app = Flask(__name__)

# 安全性設定
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', os.urandom(24))
is_production = os.environ.get('RENDER') is not None
app.config['SESSION_COOKIE_SECURE'] = is_production
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.permanent_session_lifetime = timedelta(hours=8)

# 郵件設定 (若無設定也不會報錯，僅跳過寄信)
MAIL_USERNAME = os.environ.get('MAIL_USERNAME')
MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD')

# 流量限制
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["3000 per day", "1000 per hour"],
    storage_uri="memory://"
)

# CSRF & CORS
csrf = CSRFProtect(app)
CORS(app, resources={r"/api/*": {"origins": "*"}}, supports_credentials=True)

# 管理員密碼
ADMIN_PASSWORD_HASH = os.environ.get('ADMIN_PASSWORD_HASH')

# =========================================
# 2. 資料庫連線
# =========================================
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

# =========================================
# 3. 工具函式
# =========================================
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

def send_email(to_email, subject, body):
    """發送郵件工具"""
    if not MAIL_USERNAME or not MAIL_PASSWORD or not to_email:
        return
    try:
        msg = MIMEText(body, 'plain', 'utf-8')
        msg['Subject'] = subject
        msg['From'] = MAIL_USERNAME
        msg['To'] = to_email
        
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(MAIL_USERNAME, MAIL_PASSWORD)
        server.send_message(msg)
        server.quit()
    except Exception as e:
        print(f"Email Error: {e}")

@app.context_processor
def inject_links():
    if db is None: return dict(links={})
    try:
        links_cursor = db.links.find({})
        links_dict = {link['name']: link['url'] for link in links_cursor}
        return dict(links=links_dict)
    except: return dict(links={})

# =========================================
# 4. 前台頁面路由
# =========================================
@app.route('/')
def home(): return render_template('index.html')

@app.route('/services')
def services_page(): return render_template('services.html')

@app.route('/shipclothes')
def ship_clothes_page(): return render_template('shipclothes.html')

@app.route('/shop')
def shop_page(): return render_template('shop.html')

# 舊路由轉址與產品分類導向
@app.route('/gongtan')
def gongtan_page(): return redirect(url_for('services_page', _anchor='gongtan-section'))
@app.route('/shoujing')
def shoujing_page(): return redirect(url_for('services_page', _anchor='shoujing-section'))
@app.route('/products/incense')
def incense_page(): return redirect(url_for('shop_page'))
@app.route('/products/skincare')
def skincare_page(): return redirect(url_for('shop_page'))
@app.route('/products/yuan-shuai-niang')
def yuan_user_page(): return redirect(url_for('shop_page'))
@app.route('/donation')
def donation_page(): return redirect(url_for('shop_page'))
@app.route('/fund')
def fund_page(): return redirect(url_for('fund.html'))

@app.route('/feedback')
def feedback_page(): return render_template('feedback.html')
@app.route('/faq')
def faq_page(): return render_template('faq.html')

# =========================================
# 5. 後台頁面路由
# =========================================
@app.route('/admin')
def admin_page(): return render_template('admin.html')

# =========================================
# 6. API: 認證系統
# =========================================
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

# =========================================
# 7. API: 信徒回饋 (Feedback)
# =========================================
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

# =========================================
# 8. API: 收驚衣物寄回 (ShipClothes)
# =========================================
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

    # 2. 必填檢查
    if not all(k in data and data[k] for k in ['name', 'lineGroup', 'lineName', 'birthYear', 'clothes']):
        return jsonify({"success": False, "message": "所有欄位皆為必填"}), 400

    now_tw = datetime.utcnow() + timedelta(hours=8)
    pickup_date = calculate_business_d2(now_tw)

    # 3. 儲存資料
    submission = {
        "name": data['name'],
        "birthYear": data['birthYear'],
        "lineGroup": data['lineGroup'],
        "lineName": data['lineName'],
        "clothes": data['clothes'], # [{'id': 'A01', 'owner': '王大明'}]
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
            # 寄件人隱碼
            masked_sender = mask_name(doc['name'])
            # 衣服主人隱碼
            masked_clothes = []
            for item in doc.get('clothes', []):
                masked_clothes.append({
                    'id': item.get('id', ''),
                    'owner': mask_name(item.get('owner', ''))
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

# =========================================
# 9. API: 訂單系統 (Orders)
# =========================================
# --- app.py (請替換原本的 create_order 函式) ---

@app.route('/api/orders', methods=['POST'])
def create_order():
    if db is None: return jsonify({"error": "DB Error"}), 500
    data = request.get_json()
    
    # 產生訂單編號
    order_id = f"ORD{datetime.now().strftime('%Y%m%d%H%M%S')}{random.randint(10,99)}"
    
    # 建立客戶資料 (支援建廟基金所需的農曆生日)
    customer_info = {
        "name": data.get('name'),
        "phone": data.get('phone'),
        "address": data.get('address'),
        "last5": data.get('last5'),
        "email": data.get('email', ''),
        "lunarBirthday": data.get('lunarBirthday', '') # ★ 新增：建廟基金專用
    }

    order = {
        "orderId": order_id,
        "customer": customer_info,
        "items": data['items'],
        "total": data['total'],
        "status": "pending",
        "createdAt": datetime.utcnow()
    }
    db.orders.insert_one(order)
    
    # --- 寄送確認信 (內容優化) ---
    # 組合商品明細字串
    items_str = "\n".join([f"- {i['name']} x {i['qty']} (NT$ {i['price']*i['qty']})" for i in data['items']])
    
    email_subject = f"【承天中承府】感謝您的護持與訂購 - 單號 {order_id}"
    email_body = f"""
    親愛的 {customer_info['name']} 大德 您好：

    感謝您的發心護持與訂購。
    我們已收到您的訂單資訊，將盡快為您確認款項。

    【訂單資訊】
    訂單編號：{order_id}
    訂購項目：
    {items_str}
    --------------------------------
    總金額：NT$ {data['total']}
    
    【您的匯款資訊】
    帳號後五碼：{customer_info['last5']}
    
    【本府收款帳戶】
    銀行代碼：000 (範例銀行)
    銀行帳號：1234-5678-9012
    
    ※ 請務必於填單後 2 小時內完成匯款。
    ※ 建廟基金項目，我們將於每月初一、十五統一稟奏疏文，將您的功德上達天聽。

    承天中承府 敬上
    """
    
    send_email(customer_info['email'], email_subject, email_body)

    return jsonify({"success": True, "orderId": order_id})    
    # 寄送確認信 (需設定 .env 才生效)
    email_body = f"""感謝您的訂購！訂單編號：{order['orderId']}\n總金額：NT$ {order['total']}\n請於2小時內匯款。"""
    send_email(data.get('email'), f"訂單確認 - {order['orderId']}", email_body)

    return jsonify({"success": True, "orderId": order['orderId']})

@app.route('/api/orders', methods=['GET'])
@login_required
def get_orders():
    cursor = db.orders.find().sort("createdAt", -1)
    results = []
    for doc in cursor:
        doc['_id'] = str(doc['_id'])
        doc['createdAt'] = doc['createdAt'].strftime('%Y-%m-%d %H:%M')
        results.append(doc)
    return jsonify(results)

@app.route('/api/orders/<oid>/confirm', methods=['PUT'])
@login_required
def confirm_order_payment(oid):
    order = db.orders.find_one({'_id': ObjectId(oid)})
    if not order: return jsonify({"error": "No order"}), 404
    db.orders.update_one({'_id': ObjectId(oid)}, {'$set': {'status': 'paid'}})
    
    # 寄信通知出貨
    email_body = f"""您好，我們已收到款項！\n訂單編號：{order['orderId']}\n預計於 D+2 工作日出貨。"""
    send_email(order['customer'].get('email'), f"收款確認 - {order['orderId']}", email_body)
    
    return jsonify({"success": True})

@app.route('/api/orders/<oid>', methods=['DELETE'])
@login_required
def delete_order(oid):
    db.orders.delete_one({'_id': ObjectId(oid)})
    return jsonify({"success": True})

# =========================================
# 10. API: 商品管理 (Products)
# =========================================
@app.route('/api/products', methods=['GET'])
def get_products():
    if db is None: return jsonify({"error": "DB Error"}), 500
    products = list(db.products.find().sort([("category", 1), ("createdAt", -1)]))
    for p in products: p['_id'] = str(p['_id'])
    return jsonify(products)

# --- app.py (請替換 add_product 和 update_product) ---

@app.route('/api/products', methods=['POST'])
@login_required
def add_product():
    if db is None: return jsonify({"error": "DB Error"}), 500
    data = request.get_json()
    try:
        new_product = {
            "name": data.get('name'), 
            "category": data.get('category', '其他'),
            "price": int(data.get('price', 0)), 
            "description": data.get('description', ''),
            "image": data.get('image', ''), 
            "isActive": data.get('isActive', True),
            "variants": data.get('variants', []), # ★ 新增：儲存規格陣列
            "createdAt": datetime.utcnow()
        }
        db.products.insert_one(new_product)
        return jsonify({"success": True})
    except Exception as e: return jsonify({"error": str(e)}), 500

@app.route('/api/products/<pid>', methods=['PUT'])
@login_required
def update_product(pid):
    if db is None: return jsonify({"error": "DB Error"}), 500
    data = request.get_json()
    try:
        # ★ 新增：更新 variants
        fields = {k: data.get(k) for k in ['name', 'category', 'price', 'description', 'image', 'isActive', 'variants'] if k in data}
        if 'price' in fields: fields['price'] = int(fields['price'])
        db.products.update_one({'_id': ObjectId(pid)}, {'$set': fields})
        return jsonify({"success": True})
    except Exception as e: return jsonify({"error": str(e)}), 500

@app.route('/api/products/<pid>', methods=['DELETE'])
@login_required
def delete_product(pid):
    db.products.delete_one({'_id': ObjectId(pid)})
    return jsonify({"success": True})

# =========================================
# 11. API: 公告、FAQ、基金、連結
# =========================================
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
@app.route('/api/announcements/<aid>', methods=['PUT'])
@login_required
def update_announcement(aid):
    if db is None: return jsonify({"error": "DB Error"}), 500
    data = request.get_json()
    try:
        date_obj = datetime.strptime(data['date'], '%Y/%m/%d')
        update_fields = {
            "date": date_obj,
            "title": data['title'],
            "content": data['content'],
            "isPinned": data.get('isPinned', False)
        }
        db.announcements.update_one({'_id': ObjectId(aid)}, {'$set': update_fields})
        return jsonify({"success": True})
    except Exception as e: return jsonify({"error": str(e)}), 500
@app.route('/api/faq', methods=['GET'])
def get_faqs():
    query = {'category': request.args.get('category')} if request.args.get('category') else {}
    faqs = db.faq.find(query).sort([('isPinned', -1), ('createdAt', -1)])
    return jsonify([{**doc, '_id': str(doc['_id']), 'createdAt': doc['createdAt'].strftime('%Y-%m-%d')} for doc in faqs])
@app.route('/api/faq/<fid>', methods=['PUT'])
@login_required
def update_faq(fid):
    if db is None: return jsonify({"error": "DB Error"}), 500
    data = request.get_json()
    try:
        update_fields = {
            "question": data['question'],
            "answer": data['answer'],
            "category": data['category'],
            "isPinned": data.get('isPinned', False)
        }
        db.faq.update_one({'_id': ObjectId(fid)}, {'$set': update_fields})
        return jsonify({"success": True})
    except Exception as e: return jsonify({"error": str(e)}), 500
@app.route('/api/faq/categories', methods=['GET'])
def get_faq_categories(): return jsonify(db.faq.distinct('category'))

@app.route('/api/faq', methods=['POST'])
@login_required
def add_faq():
    data = request.get_json()
    if not re.match(r'^[\u4e00-\u9fff]+$', data.get('category', '')): return jsonify({"error": "分類限中文"}), 400
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

# --- 啟動伺服器 ---
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)