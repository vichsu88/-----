import os
import re
import random
import smtplib
import csv
import io
from email.mime.text import MIMEText
from email.header import Header
from functools import wraps
from datetime import datetime, timedelta
from flask import Flask, jsonify, render_template, request, session, redirect, url_for, Response, make_response
from flask_cors import CORS
from flask_wtf.csrf import CSRFProtect
from pymongo import MongoClient
from bson import ObjectId
from dotenv import load_dotenv
from werkzeug.security import check_password_hash
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# =========================================
# 1. 應用程式初始化
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

# 郵件設定
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
        if current.weekday() < 5: 
            added_days += 1
    return current

def mask_name(real_name):
    """姓名隱碼處理 (第二字變O)"""
    if not real_name: return ""
    if len(real_name) >= 2:
        return real_name[0] + "O" + real_name[2:]
    return real_name

def send_email(to_email, subject, body, is_html=False):
    """發送郵件工具"""
    if not MAIL_USERNAME or not MAIL_PASSWORD or not to_email:
        print("Email not set or credential missing")
        return
    try:
        msg_type = 'html' if is_html else 'plain'
        msg = MIMEText(body, msg_type, 'utf-8')
        msg['Subject'] = Header(subject, 'utf-8')
        msg['From'] = MAIL_USERNAME
        msg['To'] = to_email
        
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(MAIL_USERNAME, MAIL_PASSWORD)
        server.send_message(msg)
        server.quit()
        print(f"Email sent to {to_email}")
    except Exception as e:
        print(f"Email Error: {e}")

# ★ 補回遺漏的感謝狀生成函式
def generate_donation_email_html(cust, order_id, items):
    items_str = "<br>".join([f"• {i['name']} x {i['qty']}" for i in items])
    return f"""
    <div style="font-family: 'KaiTi', 'Microsoft JhengHei', serif; max-width: 600px; margin: 0 auto; border: 4px double #C48945; padding: 40px; background-color: #fffcf5; color: #333;">
        <div style="text-align: center;">
            <h1 style="color: #C48945; font-size: 32px; margin-bottom: 10px;">感謝狀</h1>
            <p style="font-size: 16px; color: #888;">承天中承府 ‧ 煙島中壇元帥</p>
        </div>
        <hr style="border: 0; border-top: 1px solid #C48945; margin: 20px 0;">
        <p style="font-size: 18px; line-height: 1.8;">
            茲感謝信士 <strong>{cust['name']}</strong><br>
            發心護持公壇聖務，捐贈項目如下：
        </p>
        <div style="background: #f0ebe5; padding: 20px; border-radius: 8px; margin: 20px 0;">
            {items_str}
        </div>
        <p style="font-size: 18px; line-height: 1.8;">
            您的心意將上達天聽，祈求元帥庇佑您：<br>
            <strong>{cust.get('prayer', '闔家平安，萬事如意')}</strong>
        </p>
        <p style="margin-top: 40px; text-align: right; font-size: 16px;">
            承天中承府 敬謝<br>
            {datetime.now().strftime('%Y 年 %m 月 %d 日')}
        </p>
        <div style="text-align: center; margin-top: 30px; font-size: 12px; color: #999;">
            (此為系統自動發送之電子感謝狀，請妥善保存)
        </div>
    </div>
    """

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

@app.route('/donation')
def donation_page(): return render_template('donation.html')

@app.route('/fund')
def fund_page(): return render_template('fund.html')

@app.route('/feedback')
def feedback_page(): return render_template('feedback.html')

@app.route('/faq')
def faq_page(): return render_template('faq.html')

# 轉址路由
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
# 7. API: 信徒回饋 & 衣物 & 捐贈芳名錄
# =========================================

# --- Feedback API ---
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
    cursor = db.feedback.find({"status": "pending"}).sort("createdAt", 1)
    return jsonify([{**doc, '_id': str(doc['_id']), 'createdAt': doc['createdAt'].strftime('%Y-%m-%d %H:%M:%S')} for doc in cursor])

@app.route('/api/feedback/approved', methods=['GET'])
@login_required
def get_approved_feedback():
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

# --- ShipClothes API ---
@app.route('/api/shipclothes/calc-date', methods=['GET'])
def get_pickup_date_preview():
    today = datetime.utcnow() + timedelta(hours=8)
    pickup_date = calculate_business_d2(today)
    return jsonify({"pickupDate": pickup_date.strftime('%Y/%m/%d (%a)')})

@app.route('/api/shipclothes', methods=['POST'])
def submit_ship_clothes():
    if db is None: return jsonify({"success": False, "message": "資料庫未連線"}), 500
    data = request.get_json()
    
    user_captcha = data.get('captcha', '').strip()
    correct_answer = session.get('captcha_answer')
    session.pop('captcha_answer', None)
    if not correct_answer or user_captcha != correct_answer:
        return jsonify({"success": False, "message": "驗證碼錯誤"}), 400

    if not all(k in data and data[k] for k in ['name', 'lineGroup', 'lineName', 'birthYear', 'clothes']):
        return jsonify({"success": False, "message": "所有欄位皆為必填"}), 400

    now_tw = datetime.utcnow() + timedelta(hours=8)
    pickup_date = calculate_business_d2(now_tw)

    submission = {
        "name": data['name'],
        "birthYear": data['birthYear'],
        "lineGroup": data['lineGroup'],
        "lineName": data['lineName'],
        "clothes": data['clothes'],
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
            masked_sender = mask_name(doc['name'])
            masked_clothes = []
            for item in doc.get('clothes', []):
                masked_clothes.append({'id': item.get('id', ''), 'owner': mask_name(item.get('owner', ''))})
            results.append({
                "name": masked_sender, "birthYear": doc.get('birthYear', ''),
                "lineGroup": doc['lineGroup'], "lineName": doc.get('lineName', ''),
                "clothes": masked_clothes, "submitDate": doc['submitDateStr'], "pickupDate": doc['pickupDateStr']
            })
        return jsonify(results)
    except Exception as e: return jsonify({"error": str(e)}), 500

# --- Donation Public API ---
@app.route('/api/donations/public', methods=['GET'])
def get_public_donations():
    """前台芳名錄：只抓已付款捐贈，最新的30筆"""
    if db is None: return jsonify([]), 500
    try:
        cursor = db.orders.find({"status": "paid", "orderType": "donation"}).sort("updatedAt", -1).limit(30)
        results = []
        for doc in cursor:
            customer = doc.get('customer', {})
            items_summary = []
            for item in doc.get('items', []):
                items_summary.append(f"{item['name']} x{item['qty']}")
            results.append({
                "name": mask_name(customer.get('name', '善信')),
                "wish": customer.get('prayer', '祈求平安'),
                "items": ", ".join(items_summary)
            })
        return jsonify(results)
    except Exception as e:
        return jsonify([])

# =========================================
# 8. ★ 後台捐贈管理 API (新增區塊)
# =========================================

@app.route('/api/donations/admin', methods=['GET'])
@login_required
def get_admin_donations():
    """後台取得捐贈訂單，支援日期篩選"""
    start_str = request.args.get('start')
    end_str = request.args.get('end')
    
    query = {"orderType": "donation"}
    
    if start_str and end_str:
        try:
            start_date = datetime.strptime(start_str, '%Y-%m-%d')
            end_date = datetime.strptime(end_str, '%Y-%m-%d') + timedelta(days=1) # 含當天
            query["createdAt"] = {"$gte": start_date, "$lt": end_date}
        except: pass
    
    cursor = db.orders.find(query).sort([("status", 1), ("createdAt", -1)]) # 未付款在前，新單在前
    results = []
    for doc in cursor:
        doc['_id'] = str(doc['_id'])
        doc['createdAt'] = doc['createdAt'].strftime('%Y-%m-%d %H:%M')
        # 如果有付款時間就顯示付款時間，否則顯示建立時間
        doc['paidAt'] = doc.get('paidAt').strftime('%Y-%m-%d %H:%M') if doc.get('paidAt') else ''
        results.append(doc)
    return jsonify(results)

@app.route('/api/donations/export', methods=['POST'])
@login_required
def export_donations_report():
    """匯出稟報清單 (CSV)"""
    data = request.get_json()
    start_str = data.get('start')
    end_str = data.get('end')
    
    query = {"orderType": "donation", "status": "paid"} # 只匯出已付款
    
    if start_str and end_str:
        try:
            start_date = datetime.strptime(start_str, '%Y-%m-%d')
            end_date = datetime.strptime(end_str, '%Y-%m-%d') + timedelta(days=1)
            query["updatedAt"] = {"$gte": start_date, "$lt": end_date} # 用付款時間篩選
        except: pass
        
    cursor = db.orders.find(query).sort("updatedAt", 1)
    
    # 產生 CSV
    si = io.StringIO()
    cw = csv.writer(si)
    # 表頭：捐贈日期(付款日)、姓名、農曆生日、地址、捐贈項目、祈願內容
    cw.writerow(['捐贈日期', '姓名', '農曆生日', '地址', '捐贈項目', '祈願內容'])
    
    for doc in cursor:
        cust = doc.get('customer', {})
        items_str = "、".join([f"{i['name']}x{i['qty']}" for i in doc.get('items', [])])
        paid_date = doc.get('updatedAt').strftime('%Y/%m/%d') if doc.get('updatedAt') else ''
        
        cw.writerow([
            paid_date,
            cust.get('name', ''),
            cust.get('lunarBirthday', ''),
            cust.get('address', ''),
            items_str,
            cust.get('prayer', '')
        ])
        
    output = make_response(si.getvalue())
    output.headers["Content-Disposition"] = f"attachment; filename=donation_report_{datetime.now().strftime('%Y%m%d')}.csv"
    output.headers["Content-type"] = "text/csv"
    return output

@app.route('/api/donations/cleanup', methods=['DELETE'])
@login_required
def cleanup_old_donations():
    """刪除所有超過 60 天的資料 (含 Shop 與 Donation)"""
    cutoff = datetime.utcnow() - timedelta(days=60)
    result = db.orders.delete_many({"createdAt": {"$lt": cutoff}})
    return jsonify({"success": True, "count": result.deleted_count})

@app.route('/api/donations/cleanup-unpaid', methods=['DELETE'])
@login_required
def cleanup_unpaid_orders():
    """刪除超過 76 小時未付款的訂單"""
    cutoff = datetime.utcnow() - timedelta(hours=76)
    result = db.orders.delete_many({"status": "pending", "createdAt": {"$lt": cutoff}})
    return jsonify({"success": True, "count": result.deleted_count})

# =========================================
# 9. API: 訂單系統 (Shop & Donation)
# =========================================
@app.route('/api/orders', methods=['POST'])
def create_order():
    if db is None: return jsonify({"error": "DB Error"}), 500
    data = request.get_json()
    
    order_type = data.get('orderType', 'shop')
    order_id = f"{'DON' if order_type == 'donation' else 'ORD'}{datetime.now().strftime('%Y%m%d%H%M%S')}{random.randint(10,99)}"
    
    customer_info = {
        "name": data.get('name'),
        "phone": data.get('phone'),
        "email": data.get('email', ''),
        "address": data.get('address'),
        "last5": data.get('last5'),
        "lunarBirthday": data.get('lunarBirthday', ''),
        "prayer": data.get('prayer', '') 
    }

    order = {
        "orderId": order_id,
        "orderType": order_type,
        "customer": customer_info,
        "items": data['items'],
        "total": data['total'],
        "status": "pending",
        "createdAt": datetime.utcnow(),
        "updatedAt": datetime.utcnow()
    }
    db.orders.insert_one(order)
    
    # 寄送確認信
    items_str = "\n".join([f"- {i['name']} x {i['qty']}" for i in data['items']])
    type_text = "【捐贈確認】" if order_type == 'donation' else "【訂購確認】"
    email_subject = f"承天中承府 - {type_text} 訂單 {order_id}"
    email_body = f"""
    親愛的 {customer_info['name']} 信士 您好：
    感謝您的{'護持與捐贈' if order_type == 'donation' else '訂購'}。
    單號：{order_id}
    --------------------------------
    {items_str}
    --------------------------------
    總金額：NT$ {data['total']}
    匯款後五碼：{customer_info['last5']}
    請於 2 小時內完成匯款，確認收款後我們將寄出確認信。
    """
    send_email(customer_info['email'], email_subject, email_body)

    return jsonify({"success": True, "orderId": order_id})

@app.route('/api/orders', methods=['GET'])
@login_required
def get_orders():
    """一般訂單列表 (排除 Donation)"""
    cursor = db.orders.find({"orderType": {"$ne": "donation"}}).sort("createdAt", -1)
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
    
    # ★ 更新狀態與時間
    now = datetime.utcnow()
    db.orders.update_one(
        {'_id': ObjectId(oid)}, 
        {'$set': {'status': 'paid', 'updatedAt': now, 'paidAt': now}}
    )
    
    # 寄信邏輯
    cust = order['customer']
    if order.get('orderType') == 'donation':
        email_subject = f"【感謝狀】承天中承府 - 感謝您的護持 ({order['orderId']})"
        email_html = generate_donation_email_html(cust, order['orderId'], order['items'])
        send_email(cust.get('email'), email_subject, email_html, is_html=True)
    else:
        email_body = f"您好，訂單 {order['orderId']} 款項已確認，預計 D+2 日出貨。"
        send_email(cust.get('email'), f"收款確認 - {order['orderId']}", email_body)
    
    return jsonify({"success": True})

@app.route('/api/orders/<oid>/resend-email', methods=['POST'])
@login_required
def resend_order_email(oid):
    """重寄確認信/感謝狀功能"""
    data = request.get_json()
    new_email = data.get('email')
    
    order = db.orders.find_one({'_id': ObjectId(oid)})
    if not order: return jsonify({"error": "No order"}), 404

    # 如果有提供新 Email，先更新資料庫
    cust = order['customer']
    target_email = cust.get('email')
    if new_email and new_email != target_email:
        db.orders.update_one({'_id': ObjectId(oid)}, {'$set': {'customer.email': new_email}})
        cust['email'] = new_email
        target_email = new_email

    # 重寄邏輯
    if order.get('orderType') == 'donation':
        email_subject = f"【補寄感謝狀】承天中承府 - 感謝您的護持 ({order['orderId']})"
        email_html = generate_donation_email_html(cust, order['orderId'], order['items'])
        send_email(target_email, email_subject, email_html, is_html=True)
    else:
        email_body = f"您好，這是補寄的收款確認信。訂單 {order['orderId']} 款項已確認。"
        send_email(target_email, f"收款確認(補寄) - {order['orderId']}", email_body)

    return jsonify({"success": True})

@app.route('/api/orders/<oid>', methods=['DELETE'])
@login_required
def delete_order(oid):
    db.orders.delete_one({'_id': ObjectId(oid)})
    return jsonify({"success": True})

# =========================================
# 10. API: 商品管理 (完整)
# =========================================
@app.route('/api/products', methods=['GET'])
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
        "isDonation": data.get('isDonation', False), # 支援捐贈標記
        "variants": data.get('variants', []),
        "createdAt": datetime.utcnow()
    }
    db.products.insert_one(new_product)
    return jsonify({"success": True})

@app.route('/api/products/<pid>', methods=['PUT'])
@login_required
def update_product(pid):
    data = request.get_json()
    fields = {k: data.get(k) for k in ['name', 'category', 'price', 'description', 'image', 'isActive', 'variants', 'isDonation'] if k in data}
    if 'price' in fields: fields['price'] = int(fields['price'])
    db.products.update_one({'_id': ObjectId(pid)}, {'$set': fields})
    return jsonify({"success": True})

@app.route('/api/products/<pid>', methods=['DELETE'])
@login_required
def delete_product(pid):
    db.products.delete_one({'_id': ObjectId(pid)})
    return jsonify({"success": True})

# =========================================
# 11. API: 公告、FAQ、基金、外部連結
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
    if not re.match(r'^[\u4e00-\u9fff]+$', data.get('category', '')): return jsonify({"error": "分類限中文"}), 400
    db.faq.insert_one({
        "question": data['question'], "answer": data['answer'], "category": data['category'],
        "isPinned": data.get('isPinned', False), "createdAt": datetime.utcnow()
    })
    return jsonify({"success": True})

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