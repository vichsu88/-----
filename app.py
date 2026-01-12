# --- app.py (完整修正版) ---
import os
import re
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
app.config['SESSION_COOKIE_SECURE'] = is_production  # True: 僅限 HTTPS
app.config['SESSION_COOKIE_HTTPONLY'] = True         # 禁止 JS 讀取 Cookie
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'        # 防範 CSRF
app.permanent_session_lifetime = timedelta(hours=8)  # Session 有效期 8 小時

# 流量限制 (Rate Limiting)
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["2000 per day", "500 per hour"],
    storage_uri="memory://"
)

# CSRF 保護
csrf = CSRFProtect(app)

# CORS 設定
CORS(app, resources={r"/api/*": {"origins": "*"}}, supports_credentials=True)

# 管理員密碼雜湊
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

# --- 3. 裝飾器與工具函式 ---
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'logged_in' not in session:
            if request.path.startswith('/api/'):
                return jsonify({"error": "未授權，請先登入"}), 403
            return redirect(url_for('admin_page'))
        return f(*args, **kwargs)
    return decorated_function

@app.context_processor
def inject_links():
    if db is None: return dict(links={})
    try:
        links_cursor = db.links.find({})
        links_dict = {link['name']: link['url'] for link in links_cursor}
        return dict(links=links_dict)
    except: return dict(links={})

# --- 4. 前台頁面路由 ---
# --- 前台頁面路由 ---
@app.route('/')
def home(): return render_template('index.html')

# ★ 合併後的新服務頁面
@app.route('/services')
def services_page(): return render_template('services.html')

# 舊路由轉址 (相容性)
@app.route('/gongtan')
def gongtan_page(): return redirect(url_for('services_page', _anchor='gongtan-section'))
@app.route('/shoujing')
def shoujing_page(): return redirect(url_for('services_page', _anchor='shoujing-section'))

# ★ 新增產品與功能頁面路由 (目前先指向 index 或簡易模板，防止連結失效)
@app.route('/products/incense')
def incense_page(): return render_template('incense.html') # 假設您還保留這個，或者稍後我們重做商品頁

@app.route('/products/skincare')
def skincare_page(): 
    # 暫時無內容，先導回首頁並顯示訊息，或顯示 "敬請期待"
    return render_template('index.html') 

@app.route('/products/yuan-shuai-niang')
def yuan_user_page(): 
    return render_template('index.html')

@app.route('/donation')
def donation_page(): 
    return render_template('index.html')

@app.route('/fund')
def fund_page(): 
    return render_template('index.html')

@app.route('/feedback')
def feedback_page(): return render_template('feedback.html')
@app.route('/faq')
def faq_page(): return render_template('faq.html')

# --- 5. 後台頁面路由 ---
@app.route('/admin')
def admin_page(): return render_template('admin.html')

# --- 6. 核心 API：認證系統 ---
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

# --- 7. 核心 API：信徒回饋 (Feedback) ---

# 新增回饋 (前台)
@app.route('/api/feedback', methods=['POST'])
def add_feedback():
    if db is None: return jsonify({"error": "資料庫未連線"}), 500
    data = request.get_json()
    
    required = ['realName', 'nickname', 'category', 'content']
    if not all(field in data and data[field] for field in required):
        return jsonify({"error": "必填欄位不完整"}), 400
    
    if not data.get('agreed'):
        return jsonify({"error": "必須勾選同意條款"}), 400

    new_feedback = {
        "realName": data.get('realName'),
        "nickname": data.get('nickname'),
        "category": data.get('category', []),
        "content": data.get('content'),
        "lunarBirthday": data.get('lunarBirthday', ''), 
        "birthTime": data.get('birthTime') or '吉時 (不知道)',
        "address": data.get('address', ''),
        "phone": data.get('phone', ''),
        "agreed": True,
        "createdAt": datetime.utcnow(),
        "status": "pending",
        "isMarked": False
    }
    db.feedback.insert_one(new_feedback)
    return jsonify({"success": True, "message": "回饋已送出，待審核中"})

# 取得待審核列表 (舊 -> 新)
@app.route('/api/feedback/pending', methods=['GET'])
@login_required
def get_pending_feedback():
    if db is None: return jsonify({"error": "DB Error"}), 500
    try:
        cursor = db.feedback.find({"status": "pending"}).sort("createdAt", 1)
        results = []
        for doc in cursor:
            doc['_id'] = str(doc['_id'])
            doc['createdAt'] = doc['createdAt'].strftime('%Y-%m-%d %H:%M:%S')
            results.append(doc)
        return jsonify(results)
    except Exception as e: return jsonify({"error": str(e)}), 500

# 取得已刊登列表 (新 -> 舊)
@app.route('/api/feedback/approved', methods=['GET'])
@login_required
def get_approved_feedback():
    if db is None: return jsonify({"error": "DB Error"}), 500
    try:
        cursor = db.feedback.find({"status": "approved"}).sort("createdAt", -1)
        results = []
        for doc in cursor:
            doc['_id'] = str(doc['_id'])
            doc['createdAt'] = doc['createdAt'].strftime('%Y-%m-%d %H:%M:%S')
            results.append(doc)
        return jsonify(results)
    except Exception as e: return jsonify({"error": str(e)}), 500

# 編輯回饋
@app.route('/api/feedback/<feedback_id>', methods=['PUT'])
@login_required
def update_feedback(feedback_id):
    if db is None: return jsonify({"error": "DB Error"}), 500
    data = request.get_json()
    try:
        fields = {k: data.get(k) for k in ['realName', 'nickname', 'category', 'content', 'lunarBirthday', 'birthTime', 'address', 'phone']}
        result = db.feedback.update_one({'_id': ObjectId(feedback_id)}, {'$set': fields})
        if result.matched_count == 0: return jsonify({"error": "找不到資料"}), 404
        return jsonify({"success": True})
    except Exception as e: return jsonify({"error": str(e)}), 500

# 同意刊登
@app.route('/api/feedback/<feedback_id>/approve', methods=['PUT'])
@login_required
def approve_feedback(feedback_id):
    if db is None: return jsonify({"error": "DB Error"}), 500
    db.feedback.update_one({'_id': ObjectId(feedback_id)}, {'$set': {'status': 'approved'}})
    return jsonify({"success": True})

# 刪除回饋
@app.route('/api/feedback/<feedback_id>', methods=['DELETE'])
@login_required
def delete_feedback(feedback_id):
    if db is None: return jsonify({"error": "DB Error"}), 500
    db.feedback.delete_one({'_id': ObjectId(feedback_id)})
    return jsonify({"success": True})

# 標記單筆
@app.route('/api/feedback/<feedback_id>/mark', methods=['PUT'])
@login_required
def mark_feedback(feedback_id):
    if db is None: return jsonify({"error": "DB Error"}), 500
    data = request.get_json()
    db.feedback.update_one({'_id': ObjectId(feedback_id)}, {'$set': {'isMarked': data.get('isMarked', False)}})
    return jsonify({"success": True})

# 全部標記已讀
@app.route('/api/feedback/mark-all-approved', methods=['PUT'])
@login_required
def mark_all_approved_feedback():
    if db is None: return jsonify({"error": "DB Error"}), 500
    db.feedback.update_many({'status': 'approved'}, {'$set': {'isMarked': True}})
    return jsonify({"success": True})

# 匯出並下載未寄送清單
@app.route('/api/feedback/download-unmarked', methods=['POST'])
@login_required
def download_unmarked_feedback():
    if db is None: return jsonify({"error": "DB Error"}), 500
    try:
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
    except Exception as e: return jsonify({"error": str(e)}), 500

# --- 8. 商品管理 API (Products) ---
@app.route('/api/products', methods=['GET'])
@login_required
def get_products():
    if db is None: return jsonify({"error": "DB Error"}), 500
    try:
        products = list(db.products.find().sort([("category", 1), ("createdAt", -1)]))
        for p in products: p['_id'] = str(p['_id'])
        return jsonify(products)
    except Exception as e: return jsonify({"error": str(e)}), 500

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
            "createdAt": datetime.utcnow()
        }
        db.products.insert_one(new_product)
        return jsonify({"success": True})
    except Exception as e: return jsonify({"error": str(e)}), 500

@app.route('/api/products/<product_id>', methods=['PUT'])
@login_required
def update_product(product_id):
    if db is None: return jsonify({"error": "DB Error"}), 500
    data = request.get_json()
    try:
        fields = {k: data.get(k) for k in ['name', 'category', 'price', 'description', 'image', 'isActive'] if k in data}
        if 'price' in fields: fields['price'] = int(fields['price'])
        db.products.update_one({'_id': ObjectId(product_id)}, {'$set': fields})
        return jsonify({"success": True})
    except Exception as e: return jsonify({"error": str(e)}), 500

@app.route('/api/products/<product_id>', methods=['DELETE'])
@login_required
def delete_product(product_id):
    if db is None: return jsonify({"error": "DB Error"}), 500
    db.products.delete_one({'_id': ObjectId(product_id)})
    return jsonify({"success": True})

# --- 9. 公告管理 API (Announcements) ---
@app.route('/api/announcements', methods=['GET'])
def get_announcements():
    if db is None: return jsonify({"error": "DB Error"}), 500
    try:
        cursor = db.announcements.find().sort([("isPinned", -1), ("_id", -1)])
        results = []
        for doc in cursor:
            doc['_id'] = str(doc['_id'])
            if 'date' in doc and isinstance(doc['date'], datetime):
                doc['date'] = doc['date'].strftime('%Y/%m/%d')
            results.append(doc)
        return jsonify(results)
    except Exception as e: return jsonify({"error": str(e)}), 500

@app.route('/api/announcements', methods=['POST'])
@login_required
def add_announcement():
    if db is None: return jsonify({"error": "DB Error"}), 500
    data = request.get_json()
    try:
        date_obj = datetime.strptime(data['date'], '%Y/%m/%d')
        new_ann = {
            "date": date_obj, "title": data['title'], "content": data['content'],
            "isPinned": data.get('isPinned', False), "createdAt": datetime.utcnow()
        }
        db.announcements.insert_one(new_ann)
        return jsonify({"success": True})
    except Exception as e: return jsonify({"error": str(e)}), 400

@app.route('/api/announcements/<ann_id>', methods=['DELETE'])
@login_required
def delete_announcement(ann_id):
    if db is None: return jsonify({"error": "DB Error"}), 500
    db.announcements.delete_one({'_id': ObjectId(ann_id)})
    return jsonify({"success": True})

# --- 10. FAQ 管理 API ---
@app.route('/api/faq', methods=['GET'])
def get_faqs():
    if db is None: return jsonify({"error": "DB Error"}), 500
    query = {'category': request.args.get('category')} if request.args.get('category') else {}
    faqs = db.faq.find(query).sort([('isPinned', -1), ('createdAt', -1)])
    return jsonify([{**doc, '_id': str(doc['_id']), 'createdAt': doc['createdAt'].strftime('%Y-%m-%d')} for doc in faqs])

@app.route('/api/faq/categories', methods=['GET'])
def get_faq_categories():
    if db is None: return jsonify([])
    return jsonify(db.faq.distinct('category'))

@app.route('/api/faq', methods=['POST'])
@login_required
def add_faq():
    if db is None: return jsonify({"error": "DB Error"}), 500
    data = request.get_json()
    if not re.match(r'^[\u4e00-\u9fff]+$', data.get('category', '')): return jsonify({"error": "分類限中文"}), 400
    db.faq.insert_one({
        "question": data['question'], "answer": data['answer'], "category": data['category'],
        "isPinned": data.get('isPinned', False), "createdAt": datetime.utcnow()
    })
    return jsonify({"success": True})

@app.route('/api/faq/<faq_id>', methods=['DELETE'])
@login_required
def delete_faq(faq_id):
    if db is None: return jsonify({"error": "DB Error"}), 500
    db.faq.delete_one({'_id': ObjectId(faq_id)})
    return jsonify({"success": True})

# --- 11. 建廟基金 & 連結 API ---
@app.route('/api/fund-settings', methods=['GET'])
def get_fund_settings():
    if db is None: return jsonify({"error": "DB Error"}), 500
    settings = db.temple_fund.find_one({"type": "main_fund"}) or {"goal_amount": 10000000, "current_amount": 0}
    if '_id' in settings: settings['_id'] = str(settings['_id'])
    return jsonify(settings)

@app.route('/api/fund-settings', methods=['POST'])
@login_required
def update_fund_settings():
    if db is None: return jsonify({"error": "DB Error"}), 500
    data = request.get_json()
    db.temple_fund.update_one(
        {"type": "main_fund"},
        {"$set": {"goal_amount": int(data.get('goal_amount', 0)), "current_amount": int(data.get('current_amount', 0))}},
        upsert=True
    )
    return jsonify({"success": True})

@app.route('/api/links', methods=['GET'])
def get_links():
    if db is None: return jsonify([])
    return jsonify([{**l, '_id': str(l['_id'])} for l in db.links.find({})])

@app.route('/api/links/<link_id>', methods=['PUT'])
@login_required
def update_link(link_id):
    if db is None: return jsonify({"error": "DB Error"}), 500
    data = request.get_json()
    db.links.update_one({'_id': ObjectId(link_id)}, {'$set': {'url': data['url']}})
    return jsonify({"success": True})

# --- 啟動 ---
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)