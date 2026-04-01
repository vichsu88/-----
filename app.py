import os
import requests
import secrets
import urllib.parse
import random
import io
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from flask import Flask, jsonify, render_template, request, session, redirect, url_for, Response
from flask_cors import CORS
from flask_wtf.csrf import CSRFProtect
from pymongo import MongoClient
from bson import ObjectId
from dotenv import load_dotenv
from werkzeug.security import check_password_hash
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from utils.helpers import get_tw_now, validate_real_name, calculate_business_d2, mask_name, get_object_id
from utils.decorators import login_required, user_login_required
from utils.email import (
    send_email,
    generate_feedback_email_html,
    generate_shop_email_html,
    generate_donation_created_email,
    generate_donation_paid_email,
)

# =========================================
# 1. 應用程式初始化
# =========================================
load_dotenv()
app = Flask(__name__)

# 安全性設定
is_production = os.environ.get('RENDER') is not None
_secret_key = os.environ.get('SECRET_KEY')
if not _secret_key:
    if is_production:
        raise RuntimeError("SECRET_KEY 環境變數未設定，無法啟動生產環境")
    _secret_key = 'dev-insecure-key-do-not-use-in-production'
app.config['SECRET_KEY'] = _secret_key
app.config['SESSION_COOKIE_SECURE'] = is_production
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.permanent_session_lifetime = timedelta(hours=8)

# === 郵件設定 (SendGrid API) ===
SENDGRID_API_KEY = os.environ.get('SENDGRID_API_KEY')
MAIL_SENDER = os.environ.get('MAIL_USERNAME')

# === LINE 登入設定 ===
LINE_CHANNEL_ID = os.environ.get('LINE_CHANNEL_ID')
LINE_CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET')
LINE_CALLBACK_URL = os.environ.get('LINE_CALLBACK_URL')

# 流量限制
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["3000 per day", "1000 per hour"],
    storage_uri="memory://"
)

# CSRF & CORS
csrf = CSRFProtect(app)
allowed_origins = [
    "http://localhost:5000",
    "http://127.0.0.1:5000",
    "http://140.119.143.95:5000",
    "https://yandao.onrender.com",
]
CORS(app, resources={r"/api/*": {"origins": allowed_origins}}, supports_credentials=True)

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
# 3. 工具函式（已移至 utils/ 模組，此處保留供參考）
# =========================================

@app.context_processor
def inject_links():
    if db is None: 
        return dict(links={})
    try:
        links_cursor = db.links.find({})
        links_dict = {link['name']: link['url'] for link in links_cursor}
        return dict(links=links_dict)
    except Exception: 
        return dict(links={})

# =========================================
# 4. 前台頁面路由 (包含 SSR 資料預載)
# =========================================
@app.route('/profile')
def profile_page(): 
    return render_template('profile.html')

@app.route('/')
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

@app.route('/services')
def services_page(): return render_template('services.html')

@app.route('/shipclothes')
def ship_clothes_page(): return render_template('shipclothes.html')

@app.route('/shop')
def shop_page(): return render_template('shop.html')

@app.route('/donation')
def donation_page(): return render_template('donation.html')

@app.route('/fund')
def fund_page(): return render_template('fund.html')

@app.route('/committee')
def committee_page(): return render_template('committee.html')

@app.route('/api/committee/status', methods=['GET'])
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

@app.route('/feedback')
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

@app.route('/faq')
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

# =========================================
# LINE 登入與會員 API
# =========================================
@app.route('/api/line/login')
def line_login():
    if not LINE_CHANNEL_ID:
        return "伺服器尚未設定 LINE_CHANNEL_ID", 500
        
    state = secrets.token_hex(16)
    session['line_state'] = state
    next_url = request.args.get('next', '/')
    session['line_next_url'] = next_url

    url = (
        "https://access.line.me/oauth2/v2.1/authorize?"
        "response_type=code&"
        f"client_id={LINE_CHANNEL_ID}&"
        f"redirect_uri={urllib.parse.quote(LINE_CALLBACK_URL)}&"
        f"state={state}&"
        "scope=profile%20openid"
    )
    return redirect(url)

@app.route('/api/line/callback')
def line_callback():
    code = request.args.get('code')
    state = request.args.get('state')
    session_state = session.get('line_state')

    if state != session_state:
        return "登入狀態驗證失敗，請重新操作", 400

    token_url = "https://api.line.me/oauth2/v2.1/token"
    headers = {'Content-Type': 'application/x-www-form-urlencoded'}
    data = {
        'grant_type': 'authorization_code',
        'code': code,
        'redirect_uri': LINE_CALLBACK_URL,
        'client_id': LINE_CHANNEL_ID,
        'client_secret': LINE_CHANNEL_SECRET
    }
    
    token_res = requests.post(token_url, headers=headers, data=data)
    if token_res.status_code != 200:
        return f"獲取 Token 失敗: {token_res.text}", 400
        
    access_token = token_res.json().get('access_token')
    profile_url = "https://api.line.me/v2/profile"
    profile_headers = {'Authorization': f'Bearer {access_token}'}
    profile_res = requests.get(profile_url, headers=profile_headers)
    
    if profile_res.status_code != 200:
        return "獲取使用者資料失敗", 400
        
    profile = profile_res.json()
    line_id = profile.get('userId')
    display_name = profile.get('displayName')
    picture_url = profile.get('pictureUrl', '')

    if db is not None:
        db.users.update_one(
            {'lineId': line_id},
            {'$set': {
                'lineId': line_id,
                'displayName': display_name,
                'pictureUrl': picture_url,
                'lastLoginAt': datetime.now(timezone.utc).replace(tzinfo=None)
            },
            '$setOnInsert': {'createdAt': datetime.now(timezone.utc).replace(tzinfo=None)}},
            upsert=True
        )

    session['user_line_id'] = line_id
    session['user_display_name'] = display_name
    session.permanent = True 

    next_url = session.pop('line_next_url', '/')
    return redirect(next_url)

@app.route('/api/user/me', methods=['GET'])
def get_current_user():
    line_id = session.get('user_line_id')
    if not line_id:
        return jsonify({"logged_in": False})
        
    if db is not None:
        user = db.users.find_one({'lineId': line_id}, {'_id': 0})
        if user:
            has_received = db.feedback.count_documents({"lineId": line_id, "status": "sent"}) > 0
            user['has_received_gift'] = has_received
            
            # --- 抓取委員會稱謂邏輯 ---
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

@app.route('/api/user/profile', methods=['PUT'])
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

@app.route('/api/user/feedbacks', methods=['GET'])
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

# =========================================
# 收驚衣服預約取件 API (看板與個人專區)
# =========================================
@app.route('/api/pickup/reserve', methods=['POST'])
@user_login_required
def create_pickup_reservation():
    line_id = session.get('user_line_id')
    data = request.get_json()
    pickup_type = data.get('pickupType') 
    pickup_date = data.get('pickupDate')
    clothes = data.get('clothes', [])
    
    if not pickup_type or not pickup_date or not clothes:
        return jsonify({"error": "資料不完整"}), 400

    if db is not None:
        incoming_ids = [c.get('clothId', '').strip() for c in clothes if c.get('clothId')]
        today_str = get_tw_now().strftime('%Y-%m-%d')
        
        duplicate_order = db.pickups.find_one({
            "clothes.clothId": {"$in": incoming_ids},
            "pickupDate": {"$gte": today_str}
        })
        
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
        "createdAt": datetime.now(timezone.utc).replace(tzinfo=None)
    }
    
    if db is not None:
        db.pickups.insert_one(new_reservation)
        return jsonify({"success": True, "message": "預約成功"})
        
    return jsonify({"error": "資料庫連線失敗"}), 500

@app.route('/api/pickup/public', methods=['GET'])
def get_public_pickups():
    """給門市人員與大眾看的電子佈告欄 (自動過濾與遮蔽)"""
    if db is None: 
        return jsonify([])
    
    threshold_date = (get_tw_now() - timedelta(days=1)).strftime('%Y-%m-%d')
    cursor = db.pickups.find({"pickupDate": {"$gte": threshold_date}}).sort("pickupDate", 1)
    
    # 【優化】使用 defaultdict 取代原先的鍵值檢查
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

@app.route('/api/user/pickups', methods=['GET'])
@user_login_required
def get_user_pickups():
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

@app.route('/api/pickup/<pid>', methods=['DELETE'])
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
        p_date = datetime.strptime(pickup.get('pickupDate'), '%Y-%m-%d')
        today = get_tw_now().replace(hour=0, minute=0, second=0, microsecond=0)
        
        if today >= p_date:
            return jsonify({"error": "已超過取消期限 (限取件日前一天)"}), 400
    except Exception:
        return jsonify({"error": "日期資料異常"}), 400

    db.pickups.delete_one({"_id": oid})
    return jsonify({"success": True})

# =========================================
# 5. 後台頁面路由 & API
# =========================================
@app.route('/api/admin/receipt/<receipt_id>', methods=['DELETE'])
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

@app.route('/admin')
def admin_page(): 
    return render_template('admin.html')

@app.route('/api/session_check', methods=['GET'])
def session_check():
    return jsonify({"logged_in": session.get('admin_logged_in', False)})

@csrf.exempt
@app.route('/api/login', methods=['POST'])
@limiter.limit("5 per minute")
def api_login():
    password = request.json.get('password')
    if ADMIN_PASSWORD_HASH and check_password_hash(ADMIN_PASSWORD_HASH, password):
        session['admin_logged_in'] = True
        session.permanent = True
        return jsonify({"success": True, "message": "登入成功"})
    return jsonify({"success": False, "message": "密碼錯誤"}), 401

@app.route('/api/logout', methods=['POST'])
def api_logout():
    session.pop('admin_logged_in', None)
    return jsonify({"success": True})

# --- Feedback API ---
def enrich_feedback_for_admin(cursor):
    """【優化】解決 N+1 Query：批次取得 User 與 sent 狀態，避免在迴圈內反覆查詢資料庫"""
    docs = list(cursor)
    if not docs: 
        return []
        
    line_ids = [d.get('lineId') for d in docs if d.get('lineId')]
    
    # 批次獲取使用者資料
    users_map = {}
    if line_ids:
        for u in db.users.find({"lineId": {"$in": line_ids}}):
            users_map[u['lineId']] = u
            
    # 批次獲取送出狀態
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
        
        if 'createdAt' in doc: 
            doc['createdAt'] = doc['createdAt'].strftime('%Y-%m-%d %H:%M:%S')
        if 'approvedAt' in doc: 
            doc['approvedAt'] = doc['approvedAt'].strftime('%Y-%m-%d %H:%M')
        if 'sentAt' in doc: 
            doc['sentAt'] = doc['sentAt'].strftime('%Y-%m-%d %H:%M')
            
        results.append(doc)
    return results

@app.route('/api/feedback', methods=['POST'])
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

@app.route('/api/feedback/approved', methods=['GET']) 
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
            'createdAt': doc['createdAt'].strftime('%Y-%m-%d') if 'createdAt' in doc else '' 
        })
    return jsonify(results)

@app.route('/api/feedback/status/pending', methods=['GET'])
@login_required
def get_pending_feedback():
    cursor = db.feedback.find({"status": "pending"}).sort("createdAt", 1)
    return jsonify(enrich_feedback_for_admin(cursor))

@app.route('/api/feedback/status/approved', methods=['GET'])
@login_required
def get_admin_approved_feedback():
    cursor = db.feedback.find({"status": "approved"}).sort("approvedAt", -1)
    return jsonify(enrich_feedback_for_admin(cursor))

@app.route('/api/feedback/status/sent', methods=['GET'])
@login_required
def get_sent_feedback():
    cursor = db.feedback.find({"status": "sent"}).sort("sentAt", -1)
    return jsonify(enrich_feedback_for_admin(cursor))

@app.route('/api/feedback/<fid>/approve', methods=['PUT'])
@login_required
def approve_feedback(fid):
    oid = get_object_id(fid)
    if not oid: 
        return jsonify({"error": "無效的 ID 格式"}), 400
    fb = db.feedback.find_one({'_id': oid})
    if not fb: 
        return jsonify({"error": "No data"}), 404
    
    fb_id = f"FB{datetime.now().strftime('%Y%m%d')}{random.randint(10,99)}"
    db.feedback.update_one({'_id': oid}, {'$set': {'status': 'approved', 'feedbackId': fb_id, 'approvedAt': datetime.now(timezone.utc).replace(tzinfo=None)}})
    
    user = db.users.find_one({"lineId": fb.get('lineId')}) if fb.get('lineId') else {}
    email = user.get('email') or fb.get('email')
    if email:
        fb_for_email = fb.copy()
        fb_for_email['realName'] = user.get('realName', '信徒')
        send_email(email, "【承天中承府】您的回饋已核准刊登", generate_feedback_email_html(fb_for_email, 'approved'), SENDGRID_API_KEY, MAIL_SENDER, is_html=True)
    return jsonify({"success": True})

@app.route('/api/feedback/<fid>/ship', methods=['PUT'])
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
    
    db.feedback.update_one({'_id': oid}, {'$set': {'status': 'sent', 'trackingNumber': tracking, 'sentAt': datetime.now(timezone.utc).replace(tzinfo=None)}})
    
    user = db.users.find_one({"lineId": fb.get('lineId')}) if fb.get('lineId') else {}
    email = user.get('email') or fb.get('email')
    if email:
        fb_for_email = fb.copy()
        fb_for_email['realName'] = user.get('realName', '信徒')
        send_email(email, "【承天中承府】結緣品寄出通知", generate_feedback_email_html(fb_for_email, 'sent', tracking), SENDGRID_API_KEY, MAIL_SENDER, is_html=True)
    return jsonify({"success": True})

@app.route('/api/feedback/<fid>', methods=['DELETE'])
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
        send_email(email, "【承天中承府】感謝您的投稿與分享", generate_feedback_email_html(fb_for_email, 'rejected'), SENDGRID_API_KEY, MAIL_SENDER, is_html=True)
        
    db.feedback.delete_one({'_id': oid})
    return jsonify({"success": True})

@app.route('/api/feedback/<fid>', methods=['PUT'])
@login_required
def update_feedback(fid):
    oid = get_object_id(fid)
    if not oid: 
        return jsonify({"error": "無效的 ID 格式"}), 400
    data = request.get_json()
    db.feedback.update_one({'_id': oid}, {'$set': {'nickname': data.get('nickname'), 'category': data.get('category'), 'content': data.get('content')}})
    return jsonify({"success": True})

@app.route('/api/feedback/export-sent-txt', methods=['POST'])
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
    return Response(si.getvalue(), mimetype='text/plain', headers={"Content-Disposition": "attachment;filename=sent_feedback_list.txt"})

@app.route('/api/feedback/export-txt', methods=['POST'])
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
    return Response(si.getvalue(), mimetype='text/plain', headers={"Content-Disposition": "attachment;filename=feedback_list.txt"})

@app.route('/api/settings/bank', methods=['GET', 'POST'])
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

@app.route('/api/public/bank-info', methods=['GET'])
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

@app.route('/api/shipclothes/calc-date', methods=['GET'])
def get_pickup_date_preview():
    pickup_date = calculate_business_d2(get_tw_now())
    return jsonify({"pickupDate": pickup_date.strftime('%Y/%m/%d (%a)')})

@app.route('/api/shipclothes', methods=['POST'])
def submit_ship_clothes():
    if db is None: 
        return jsonify({"success": False, "message": "資料庫未連線"}), 500
    data = request.get_json()
    user_captcha = data.get('captcha', '').strip()
    correct_answer = session.get('captcha_answer')
    session.pop('captcha_answer', None)
    
    if not correct_answer or user_captcha != correct_answer: 
        return jsonify({"success": False, "message": "驗證碼錯誤"}), 400
    
    if not all(k in data and data[k] for k in ['name', 'lineGroup', 'lineName', 'birthYear', 'clothes']): 
        return jsonify({"success": False, "message": "所有欄位皆為必填"}), 400
        
    now_tw = get_tw_now()
    pickup_date = calculate_business_d2(now_tw)
    
    db.shipments.insert_one({
        "name": data['name'], "birthYear": data['birthYear'], "lineGroup": data['lineGroup'], "lineName": data['lineName'],
        "clothes": data['clothes'], "submitDate": now_tw, "submitDateStr": now_tw.strftime('%Y/%m/%d'),
        "pickupDate": pickup_date, "pickupDateStr": pickup_date.strftime('%Y/%m/%d')
    })
    return jsonify({"success": True, "pickupDate": pickup_date.strftime('%Y/%m/%d')})

@app.route('/api/shipclothes/list', methods=['GET'])
def get_ship_clothes_list():
    if db is None: 
        return jsonify([]), 500
    today_date = get_tw_now().replace(hour=0, minute=0, second=0, microsecond=0)
    start_date = today_date - timedelta(days=1)
    end_date = today_date + timedelta(days=5)
    
    cursor = db.shipments.find({"pickupDate": { "$gte": start_date, "$lte": end_date }}).sort("pickupDate", 1)
    results = []
    for doc in cursor:
        masked_clothes = [{'id': i.get('id',''), 'owner': mask_name(i.get('owner',''))} for i in doc.get('clothes', [])]
        results.append({
            "name": mask_name(doc['name']), "birthYear": doc.get('birthYear', ''),
            "lineGroup": doc['lineGroup'], "lineName": doc.get('lineName', ''),
            "clothes": masked_clothes, "submitDate": doc['submitDateStr'], "pickupDate": doc['pickupDateStr']
        })
    return jsonify(results)

@app.route('/api/donations/public', methods=['GET'])
def get_public_donations():
    if db is None: 
        return jsonify([]), 500
        
    target_type = request.args.get('type', 'donation')
    query = {"status": "paid"}
    
    if target_type == 'all':
        query["orderType"] = {"$in": ["donation", "fund", "committee"]}
    else:
        query["orderType"] = target_type
        
    cursor = db.orders.find(query).sort("updatedAt", -1).limit(1000)
    results = []
    for doc in cursor:
        items_summary = [f"{i['name']} x{i['qty']}" for i in doc.get('items', [])]
        results.append({
            "name": mask_name(doc.get('customer', {}).get('name', '善信')),
            "wish": doc.get('customer', {}).get('prayer', '祈求平安'),
            "items": ", ".join(items_summary)
        })
    return jsonify(results)

@app.route('/api/donations/admin', methods=['GET'])
@login_required
def get_admin_donations():
    type_filter = request.args.get('type') 
    status_filter = request.args.get('status') 
    report_filter = request.args.get('reported') 
    
    query = {}
    if type_filter: 
        query['orderType'] = type_filter
    else: 
        query['orderType'] = {"$in": ["donation", "fund", "committee"]}
        
    if status_filter: 
        query['status'] = status_filter
        
    if type_filter == 'donation' and report_filter is not None:
        query['is_reported'] = (report_filter == '1')

    start_str = request.args.get('start')
    end_str = request.args.get('end')
    if start_str and end_str:
        try:
            start_date = datetime.strptime(start_str, '%Y-%m-%d')
            end_date = datetime.strptime(end_str, '%Y-%m-%d') + timedelta(days=1)
            query["createdAt"] = {"$gte": start_date, "$lt": end_date}
        except Exception: 
            pass

    cursor = db.orders.find(query).sort([("is_reported", 1), ("createdAt", -1)])
    results = []
    for doc in cursor:
        doc['_id'] = str(doc['_id'])
        doc['createdAt'] = (doc['createdAt'] + timedelta(hours=8)).strftime('%Y-%m-%d %H:%M')
        if doc.get('reportedAt'):
            doc['reportedAt'] = (doc['reportedAt'] + timedelta(hours=8)).strftime('%Y-%m-%d')
        results.append(doc)
    return jsonify(results)

@app.route('/api/donations/export-txt', methods=['POST'])
@login_required
def export_donations_txt():
    data = request.get_json() or {}
    start_str = data.get('start')
    end_str = data.get('end')
    
    order_type = data.get('type', 'donation') 
    query = {"orderType": order_type, "status": "paid"}
    
    if start_str and end_str:
        try:
            start_date = datetime.strptime(start_str, '%Y-%m-%d')
            end_date = datetime.strptime(end_str, '%Y-%m-%d') + timedelta(days=1)
            query["updatedAt"] = {"$gte": start_date, "$lt": end_date}
        except Exception: 
            pass
            
    cursor = db.orders.find(query).sort("updatedAt", 1)
    orders = list(cursor)
    if not orders:
        return jsonify({"error": "目前無資料"}), 404
    
    title_map = {'fund': '建廟基金護持清單', 'committee': '委員會護持清單', 'donation': '捐贈稟報清單'}
    report_title = title_map.get(order_type, '護持清單')

    si = io.StringIO()
    si.write(f"{report_title}\n匯出日期：{datetime.now().strftime('%Y-%m-%d')}\n")
    si.write("="*40 + "\n\n")
    
    idx = 1
    for doc in orders:
        cust = doc.get('customer', {})
        items_str = "、".join([f"{i['name']}x{i['qty']}" for i in doc.get('items', [])])
        paid_date = doc.get('updatedAt').strftime('%Y/%m/%d') if doc.get('updatedAt') else ''
        
        si.write(f"【{idx}】\n")
        si.write(f"日期：{paid_date}\n")
        si.write(f"姓名：{cust.get('name', '')}\n")
        si.write(f"農曆：{cust.get('lunarBirthday', '')}\n")
        si.write(f"地址：{cust.get('address', '')}\n")
        
        if order_type in ['fund', 'committee']:
            si.write(f"金額：${doc.get('total', 0)}\n")
            si.write(f"末五碼：{cust.get('last5', '無')}\n")
            
        si.write(f"項目：{items_str}\n")
        si.write("-" * 20 + "\n")
        idx += 1
        
    return Response(si.getvalue(), mimetype='text/plain', headers={"Content-Disposition": f"attachment; filename={order_type}_list.txt"})

@app.route('/api/donations/cleanup-unpaid', methods=['DELETE'])
@login_required
def cleanup_unpaid_orders():
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=76)
    cursor = db.orders.find({"status": "pending", "createdAt": {"$lt": cutoff}})
    for order in cursor:
        if order.get('customer', {}).get('email'):
            subject = f"【承天中承府】訂單/捐贈登記已取消 ({order['orderId']})"
            body = f"親愛的 {order['customer'].get('name', '信徒')} 您好：\n您的訂單/捐贈登記 ({order['orderId']}) 因超過付款期限，系統已自動取消。如需服務請重新下單。"
            send_email(order['customer']['email'], subject, body, SENDGRID_API_KEY, MAIL_SENDER)

    result = db.orders.delete_many({"status": "pending", "createdAt": {"$lt": cutoff}})
    return jsonify({"success": True, "count": result.deleted_count})

@csrf.exempt
@app.route('/api/orders', methods=['POST'])
@user_login_required
def create_order():
    if db is None: 
        return jsonify({"error": "DB Error"}), 500
    data = request.get_json()
    line_id = session.get('user_line_id')
    
    order_type = data.get('orderType', 'shop')
    
    # 共用姓名驗證
    is_valid, error_msg = validate_real_name(data.get('name', '').strip())
    if not is_valid:
        return jsonify({"error": f"系統阻擋：{error_msg}"}), 400
    
    # 建廟基金 (fund) 防護
    if order_type == 'fund':
        for item in data.get('items', []):
            item_name = item.get('name')
            item_qty = int(item.get('qty', 0))
            
            if item_name in ['副主委', '委員', '顧問'] and item_qty != 1:
                return jsonify({"error": f"【{item_name}】每次結帳限購 1 名，數量不可更改。"}), 400
            
            if item_name == '副主委':
                used_count = db.orders.count_documents({
                    "orderType": "fund",
                    "status": {"$in": ["paid", "pending"]},
                    "items.name": "副主委"
                })
                if used_count >= 7:
                    return jsonify({"error": "非常抱歉，【副主委】7名額已全數被預約完畢！"}), 400

    # 委員會 (committee) 專屬防護與名額檢查
    if order_type == 'committee':
        def check_limit(name, max_limit):
            used = db.orders.count_documents({
                "orderType": "committee", 
                "status": {"$in": ["paid", "pending"]}, 
                "items.name": name
            })
            return used >= max_limit

        for item in data.get('items', []):
            item_name = item.get('name')
            item_qty = int(item.get('qty', 0))
            
            if item_qty != 1 and item_name != '[建廟] 建廟功德金':
                return jsonify({"error": f"【{item_name}】每次結帳限購 1 名。"}), 400
            
            if item_name == '[本府] 主委' and check_limit(item_name, 1): 
                return jsonify({"error": "【[本府] 主委】名額已滿！"}), 400
            if item_name == '[本府] 副主委' and check_limit(item_name, 7): 
                return jsonify({"error": "【[本府] 副主委】名額已滿！"}), 400
            if item_name == '[建廟] 籌備主委' and check_limit(item_name, 1): 
                return jsonify({"error": "【[建廟] 籌備主委】名額已滿！"}), 400
            if item_name == '[建廟] 籌備副主委' and check_limit(item_name, 0): 
                return jsonify({"error": "【[建廟] 籌備副主委】名額已滿！"}), 400

    prefix = "ORD"
    if order_type == 'donation': prefix = "DON"
    elif order_type == 'fund': prefix = "FND"
    elif order_type == 'committee': prefix = "COM" 
    
    order_id = f"{prefix}{datetime.now().strftime('%Y%m%d%H%M%S')}{random.randint(10,99)}"
    
    customer_info = {
        "name": data.get('name'), 
        "phone": data.get('phone'), 
        "email": data.get('email', ''),
        "address": data.get('address'), 
        "last5": data.get('last5'),
        "lunarBirthday": data.get('lunarBirthday', ''),
        "shippingMethod": data.get('shippingMethod', 'home'), 
        "storeInfo": data.get('storeInfo', ''),                
        "shippingFee": data.get('shippingFee', 120)            
    }
    
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    deadline = now + timedelta(hours=2)
    
    order = {
        "orderId": order_id, "orderType": order_type, "customer": customer_info,
        "items": data['items'], "total": data['total'], "status": "pending",
        "lineId": line_id,
        "paymentDeadline": deadline,
        "createdAt": now, "updatedAt": now
    }

    if order_type == 'donation':
        order['is_reported'] = False

    db.orders.insert_one(order)
    
    subject = f"【承天中承府】訂單確認 ({order_id})"
    if order_type == 'donation': 
        subject = f"【承天中承府】捐香登記確認 ({order_id})"
    elif order_type == 'fund': 
        subject = f"【承天中承府】建廟護持確認 ({order_id})"
    elif order_type == 'committee': 
        subject = f"【承天中承府】委員會發心護持確認 ({order_id})"
    
    if order_type in ['donation', 'fund', 'committee']:
        html = generate_donation_created_email(order, db=db)
    else:
        html = generate_shop_email_html(order, 'created', db=db)

    send_email(customer_info['email'], subject, html, SENDGRID_API_KEY, MAIL_SENDER, is_html=True)
    return jsonify({"success": True, "orderId": order_id})

@app.route('/api/donations/mark-reported', methods=['POST'])
@login_required
def mark_donations_reported():
    data = request.get_json()
    ids = data.get('ids', [])
    if not ids: 
        return jsonify({"success": False, "message": "無選取訂單"})
    
    object_ids = [get_object_id(i) for i in ids if get_object_id(i)]
    if object_ids:
        db.orders.update_many(
            {"_id": {"$in": object_ids}},
            {"$set": {"is_reported": True, "reportedAt": datetime.now(timezone.utc).replace(tzinfo=None)}}
        )
    return jsonify({"success": True})

@app.route('/api/user/orders', methods=['GET'])
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

@app.route('/api/user/fund-summary', methods=['GET'])
@user_login_required
def get_user_fund_summary():
    """【優化】取得登入信徒的建廟基金累計總額 (依姓名分組)，使用 defaultdict 取代傳統檢查"""
    line_id = session.get('user_line_id')
    if db is None:
        return jsonify([])

    cursor = db.orders.find({
        "lineId": line_id,
        "orderType": "fund",
        "status": "paid"
    })

    summary_dict = defaultdict(int)

    for doc in cursor:
        customer = doc.get('customer', {})
        raw_name = customer.get('name', '未具名')
        clean_name = raw_name.replace(" ", "").replace("　", "")
        if not clean_name:
            continue
        summary_dict[clean_name] += doc.get('total', 0)

    results = [
        {"name": name, "total": total}
        for name, total in summary_dict.items()
    ]
    results.sort(key=lambda x: x['total'], reverse=True)

    return jsonify(results)

@app.route('/api/user/donations', methods=['GET'])
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

@app.route('/api/orders', methods=['GET'])
@login_required
def get_orders():
    cursor = db.orders.find({"orderType": "shop"}).sort("createdAt", -1)
    results = []
    for doc in cursor:
        doc['_id'] = str(doc['_id'])
        doc['createdAt'] = (doc['createdAt'] + timedelta(hours=8)).strftime('%Y-%m-%d %H:%M')
        results.append(doc)
    return jsonify(results)

@app.route('/api/orders/cleanup-shipped', methods=['DELETE'])
@login_required
def cleanup_shipped_orders():
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=14)
    result = db.orders.delete_many({"status": "shipped", "shippedAt": {"$lt": cutoff}})
    return jsonify({"success": True, "count": result.deleted_count})

@app.route('/api/orders/<oid>/confirm', methods=['PUT'])
@login_required
def confirm_order_payment(oid):
    oid_obj = get_object_id(oid)
    if not oid_obj: 
        return jsonify({"error": "無效的 ID 格式"}), 400

    order = db.orders.find_one({'_id': oid_obj})
    if not order: 
        return jsonify({"error": "No order"}), 404
        
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    db.orders.update_one({'_id': oid_obj}, {'$set': {'status': 'paid', 'updatedAt': now, 'paidAt': now}})
    cust = order['customer']
    
    if order.get('orderType') in ['donation', 'fund','committee']:
        email_subject = f"【承天中承府】電子感謝狀 - 功德無量 ({order['orderId']})"
        email_html = generate_donation_paid_email(cust, order['orderId'], order['items'], order['total'])
        send_email(cust.get('email'), email_subject, email_html, SENDGRID_API_KEY, MAIL_SENDER, is_html=True)
    else:
        email_subject = f"【承天中承府】收款確認通知 ({order['orderId']})"
        email_html = generate_shop_email_html(order, 'paid', db=db)
        send_email(cust.get('email'), email_subject, email_html, SENDGRID_API_KEY, MAIL_SENDER, is_html=True)
    return jsonify({"success": True})

@app.route('/api/orders/<oid>/resend-email', methods=['POST'])
@login_required
def resend_order_email(oid):
    oid_obj = get_object_id(oid)
    if not oid_obj: 
        return jsonify({"error": "無效的 ID 格式"}), 400

    data = request.get_json()
    new_email = data.get('email')
    order = db.orders.find_one({'_id': oid_obj})
    if not order: 
        return jsonify({"error": "No order"}), 404
        
    cust = order['customer']
    target_email = cust.get('email')
    
    if new_email and new_email != target_email:
        db.orders.update_one({'_id': oid_obj}, {'$set': {'customer.email': new_email}})
        cust['email'] = new_email
        target_email = new_email
        
    if order.get('orderType') == 'donation':
        if order.get('status') == 'paid':
            email_subject = f"【補寄感謝狀】承天中承府 - 功德無量 ({order['orderId']})"
            email_html = generate_donation_paid_email(cust, order['orderId'], order['items'], order['total'])
        else:
            email_subject = f"【補寄】護持登記確認通知 ({order['orderId']})"
            email_html = generate_donation_created_email(order, db=db)
    else:
        email_subject = f"【承天中承府】訂單信件補寄 ({order['orderId']})"
        if order.get('status') == 'shipped':
            email_html = generate_shop_email_html(order, 'shipped', order.get('trackingNumber'), db=db)
        elif order.get('status') == 'paid':
            email_html = generate_shop_email_html(order, 'paid', db=db)
        else:
            email_html = generate_shop_email_html(order, 'created', db=db)

    send_email(target_email, email_subject, email_html, SENDGRID_API_KEY, MAIL_SENDER, is_html=True)
    return jsonify({"success": True})

@app.route('/api/orders/<oid>', methods=['DELETE'])
@login_required
def delete_order(oid):
    oid_obj = get_object_id(oid)
    if not oid_obj: 
        return jsonify({"error": "無效的 ID 格式"}), 400

    order = db.orders.find_one({'_id': oid_obj})
    if order and order.get('customer', {}).get('email'):
        subject = f"【承天中承府】訂單/登記已取消 ({order['orderId']})"
        body = f"親愛的 {order['customer'].get('name', '信徒')} 您好：\n您的訂單/登記 ({order['orderId']}) 已被取消。如為誤操作或有任何疑問，請聯繫官方 LINE。"
        send_email(order['customer']['email'], subject, body, SENDGRID_API_KEY, MAIL_SENDER)

    db.orders.delete_one({'_id': oid_obj})
    return jsonify({"success": True})

@app.route('/api/products', methods=['GET'])
def get_products():
    products = list(db.products.find().sort([("category", 1), ("createdAt", -1)]))
    for p in products: 
        p['_id'] = str(p['_id'])
    return jsonify(products)

@app.route('/api/products', methods=['POST'])
@login_required
def add_product():
    data = request.get_json()
    new_product = {
        "name": data.get('name'), "category": data.get('category', '其他'),
        "series": data.get('series', ''),"seriesSort": int(data.get('seriesSort', 0)),"price": int(data.get('price', 0)),"description": data.get('description', ''), "image": data.get('image', ''), "isActive": data.get('isActive', True),
        "isDonation": data.get('isDonation', False), "variants": data.get('variants', []), "createdAt": datetime.now(timezone.utc).replace(tzinfo=None)
    }
    db.products.insert_one(new_product)
    return jsonify({"success": True})

@app.route('/api/products/<pid>', methods=['PUT'])
@login_required
def update_product(pid):
    oid = get_object_id(pid)
    if not oid: 
        return jsonify({"error": "無效的 ID 格式"}), 400

    data = request.get_json()
    fields = {k: data.get(k) for k in ['name', 'category', 'price', 'description', 'image', 'isActive', 'variants', 'isDonation', 'series', 'seriesSort'] if k in data}
    if 'price' in fields: fields['price'] = int(fields['price'])
    if 'seriesSort' in fields: fields['seriesSort'] = int(fields['seriesSort'])
    db.products.update_one({'_id': oid}, {'$set': fields})
    return jsonify({"success": True})

@app.route('/api/products/<pid>', methods=['DELETE'])
@login_required
def delete_product(pid):
    oid = get_object_id(pid)
    if not oid: 
        return jsonify({"error": "無效的 ID 格式"}), 400

    db.products.delete_one({'_id': oid})
    return jsonify({"success": True})

@app.route('/api/announcements', methods=['GET'])
def get_announcements():
    cursor = db.announcements.find().sort([("isPinned", -1), ("_id", -1)])
    results = []
    for doc in cursor:
        doc['_id'] = str(doc['_id'])
        if 'date' in doc and isinstance(doc['date'], datetime): 
            doc['date'] = doc['date'].strftime('%Y/%m/%d')
        results.append(doc)
    return jsonify(results)

@app.route('/api/announcements', methods=['POST'])
@login_required
def add_announcement():
    data = request.get_json()
    try:
        date_obj = datetime.strptime(data['date'].replace('-', '/'), '%Y/%m/%d')
    except ValueError:
        return jsonify({"error": "日期格式錯誤，請使用 YYYY/MM/DD"}), 400
        
    db.announcements.insert_one({
        "date": date_obj, 
        "title": data['title'],
        "content": data['content'], 
        "isPinned": data.get('isPinned', False), 
        "createdAt": datetime.now(timezone.utc).replace(tzinfo=None)
    })
    return jsonify({"success": True})

@app.route('/api/announcements/<aid>', methods=['PUT'])
@login_required
def update_announcement(aid):
    oid = get_object_id(aid)
    if not oid: 
        return jsonify({"error": "無效的 ID 格式"}), 400

    data = request.get_json()
    try:
        date_obj = datetime.strptime(data['date'].replace('-', '/'), '%Y/%m/%d')
    except ValueError:
        return jsonify({"error": "日期格式錯誤"}), 400

    db.announcements.update_one({'_id': oid}, {'$set': {
        "date": date_obj, 
        "title": data['title'],
        "content": data['content'], 
        "isPinned": data.get('isPinned', False)
    }})
    return jsonify({"success": True})

@app.route('/api/announcements/<aid>', methods=['DELETE'])
@login_required
def delete_announcement(aid):
    oid = get_object_id(aid)
    if not oid: 
        return jsonify({"error": "無效的 ID 格式"}), 400

    db.announcements.delete_one({'_id': oid})
    return jsonify({"success": True})

@app.route('/api/faq', methods=['GET'])
def get_faqs():
    query = {'category': request.args.get('category')} if request.args.get('category') else {}
    faqs = db.faq.find(query).sort([('isPinned', -1), ('createdAt', -1)])
    return jsonify([{**doc, '_id': str(doc['_id']), 'createdAt': doc['createdAt'].strftime('%Y-%m-%d')} for doc in faqs])

@app.route('/api/faq/categories', methods=['GET'])
def get_faq_categories(): 
    return jsonify(db.faq.distinct('category'))

@app.route('/api/faq', methods=['POST'])
@login_required
def add_faq():
    data = request.get_json()
    if not re.match(r'^[\u4e00-\u9fff]+$', data.get('category', '')): 
        return jsonify({"error": "分類限中文"}), 400
        
    db.faq.insert_one({
        "question": data['question'], "answer": data['answer'], "category": data['category'],
        "isPinned": data.get('isPinned', False), "createdAt": datetime.now(timezone.utc).replace(tzinfo=None)
    })
    return jsonify({"success": True})

@app.route('/api/faq/<fid>', methods=['PUT'])
@login_required
def update_faq(fid):
    oid = get_object_id(fid)
    if not oid: 
        return jsonify({"error": "無效的 ID 格式"}), 400

    data = request.get_json()
    db.faq.update_one({'_id': oid}, {'$set': {
        "question": data['question'], "answer": data['answer'], "category": data['category'], "isPinned": data.get('isPinned', False)
    }})
    return jsonify({"success": True})

@app.route('/api/faq/<fid>', methods=['DELETE'])
@login_required
def delete_faq(fid):
    oid = get_object_id(fid)
    if not oid: 
        return jsonify({"error": "無效的 ID 格式"}), 400

    db.faq.delete_one({'_id': oid})
    return jsonify({"success": True})

@app.route('/api/fund-settings', methods=['GET'])
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

@app.route('/api/fund-settings', methods=['POST'])
@login_required
def update_fund_settings():
    data = request.get_json()
    db.temple_fund.update_one(
        {"type": "main_fund"}, 
        {"$set": {"goal_amount": int(data.get('goal_amount', 10000000))}}, 
        upsert=True
    )
    return jsonify({"success": True})

@app.route('/api/links', methods=['GET'])
def get_links():
    return jsonify([{**l, '_id': str(l['_id'])} for l in db.links.find({})])

@app.route('/api/links/<lid>', methods=['PUT'])
@login_required
def update_link(lid):
    oid = get_object_id(lid)
    if not oid: 
        return jsonify({"error": "無效的 ID 格式"}), 400

    data = request.get_json()
    db.links.update_one({'_id': oid}, {'$set': {'url': data['url']}})
    return jsonify({"success": True})

@app.route('/api/orders/<oid>/ship', methods=['PUT'])
@login_required
def ship_order(oid):
    oid_obj = get_object_id(oid)
    if not oid_obj: 
        return jsonify({"error": "無效的 ID 格式"}), 400

    data = request.get_json() or {}
    tracking_num = data.get('trackingNumber', '').strip()
    order = db.orders.find_one({'_id': oid_obj})
    if not order: 
        return jsonify({"error": "No order"}), 404
        
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    db.orders.update_one({'_id': oid_obj}, {'$set': {
        'status': 'shipped', 'updatedAt': now, 'shippedAt': now, 'trackingNumber': tracking_num
    }})
    cust = order['customer']
    email_subject = f"【承天中承府】訂單出貨通知 ({order['orderId']})"
    email_html = generate_shop_email_html(order, 'shipped', tracking_num, db=db)
    send_email(cust.get('email'), email_subject, email_html, SENDGRID_API_KEY, MAIL_SENDER, is_html=True)
    return jsonify({"success": True})

@app.route('/api/debug-connection')
def debug_connection():
    status = {}
    try:
        db.command('ping') 
        status['database'] = "✅ MongoDB 連線成功"
    except Exception as e:
        status['database'] = f"❌ MongoDB 連線失敗: {str(e)}"
    return jsonify(status)
    
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)