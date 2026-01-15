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

# === Email 樣板產生器 ===

def get_bank_info():
    """從資料庫讀取匯款資訊，若無則使用預設"""
    if db is None: return "請聯繫廟方確認匯款資訊"
    settings = db.settings.find_one({"type": "bank_info"}) or {}
    code = settings.get('bankCode', '808')
    name = settings.get('bankName', '玉山銀行')
    account = settings.get('account', '1234-5678-9012')
    return f"""
    銀行代碼：<strong>{code} ({name})</strong><br>
    銀行帳號：<strong>{account}</strong>
    """

def generate_shop_email_html(order, status_type, tracking_num=None):
    cust = order['customer']
    items = order['items']
    tw_now = datetime.utcnow() + timedelta(hours=8)
    date_str = tw_now.strftime('%Y/%m/%d %H:%M')
    
    # 訂單成立時間
    created_at_dt = order.get('createdAt')
    if created_at_dt and isinstance(created_at_dt, datetime):
        created_at_str = (created_at_dt + timedelta(hours=8)).strftime('%Y/%m/%d %H:%M')
    else:
        created_at_str = date_str

    bank_html = get_bank_info()
    
    if status_type == 'created':
        title = "訂單確認通知"
        color = "#C48945"
        status_text = f"""
        謝謝您的下單！我們已收到您的訂單。<br>
        訂單成立時間：{created_at_str}<br><br>
        <strong>【付款資訊】</strong><br>
        請於 <strong>2 小時內</strong> 完成匯款，以保留您的訂單資格。<br>
        <span style="color:#C48945; font-size:18px; font-weight:bold;">訂單總金額：NT$ {order['total']}</span><br>
        您的匯款後五碼：<strong>{cust['last5']}</strong><br><br>
        <div style="background:#fffcf5; padding:15px; border-left:4px solid #C48945; margin:15px 0; color:#555;">
            {bank_html}
            <div style="margin-top:8px; font-size:13px; color:#d9534f;">※ 若未於 2 小時內付款，系統將取消此筆訂單。</div>
        </div><br>
        <strong>【防詐騙提醒】</strong><br>
        <span style="color:#666; font-size:14px;">所有匯款請依照官方網頁公告之匯款帳號，若有疑慮請向官方 LINE 查證。</span>
        """
        show_price = True
    elif status_type == 'paid':
        title = "收款確認通知"
        color = "#28a745"
        status_text = f"""
        您的款項已確認！<br>
        帥府將盡速為您安排出貨，請您耐心等候。<br><br>
        <strong>確認時間：{date_str}</strong>
        """
        show_price = True
    else: # shipped
        title = "帥府出貨通知"
        color = "#C48945"
        status_text = f"""
        您的訂單已於今日出貨！<br><br>
        <div style="background:#f0ebe5; padding:15px; border:1px solid #C48945; border-radius:8px;">
            <strong>📦 物流單號：{tracking_num}</strong><br>
            <span style="font-size:13px; color:#666;">請依照上方單號，自行至物流網站查詢配送進度。</span>
        </div><br>
        <strong>出貨日期：{date_str}</strong><br><br>
        <span style="color:#666;">商品收到若有問題，請點擊下方按鈕詢問官方 LINE。</span>
        """
        show_price = False

    items_rows = ""
    for item in items:
        spec = f" ({item['variant']})" if 'variant' in item and item['variant'] != '標準' else ""
        price_td = f'<td style="padding:10px; text-align:right;">${item["price"] * item["qty"]}</td>' if show_price else ''
        items_rows += f'<tr style="border-bottom: 1px solid #eee;"><td style="padding: 10px; color:#333;">{item["name"]}{spec}</td><td style="padding: 10px; text-align: center; color:#333;">x{item["qty"]}</td>{price_td}</tr>'
    
    price_th = '<th style="padding:10px; text-align:right;">金額</th>' if show_price else ''
    total_row = f'<tfoot><tr><td colspan="2" style="padding:15px 10px; text-align:right; font-weight:bold; color:#333;">總計 (含運)</td><td style="padding:15px 10px; text-align:right; font-weight:bold; color:#C48945; font-size:18px;">NT$ {order["total"]}</td></tr></tfoot>' if show_price else ''

    return f"""
    <div style="font-family: 'Microsoft JhengHei', sans-serif; max-width: 600px; margin: 0 auto; border: 1px solid #ddd; border-radius: 8px; overflow: hidden; background-color:#fff;">
        <div style="background: {color}; padding: 20px; text-align: center;">
            <h2 style="color: #fff; margin: 0; letter-spacing: 1px;">{title}</h2>
            <p style="color: #fff; opacity: 0.9; margin: 5px 0 0 0; font-size: 14px;">訂單編號：{order['orderId']}</p>
        </div>
        <div style="padding: 30px;">
            <p style="font-size: 16px; color: #333; margin-bottom: 20px;">親愛的 <strong>{cust['name']}</strong> 您好：</p>
            <div style="font-size: 15px; color: #555; line-height: 1.6;">{status_text}</div>
            <div style="margin-top: 30px;">
                <h3 style="font-size:16px; color:#8B4513; border-bottom:2px solid #eee; padding-bottom:10px; margin-bottom:0;">訂單明細</h3>
                <table style="width: 100%; border-collapse: collapse; font-size: 14px;">
                    <thead><tr style="background: #f9f9f9; color:#666;"><th style="padding: 10px; text-align: left;">商品</th><th style="padding: 10px; text-align: center;">數量</th>{price_th}</tr></thead>
                    <tbody>{items_rows}</tbody>{total_row}
                </table>
            </div>
            <div style="text-align: center; margin-top: 40px;">
                <a href="https://line.me/R/ti/p/@566dcres" target="_blank" style="background: #00B900; color: #fff; text-decoration: none; padding: 12px 35px; border-radius: 50px; font-weight: bold; display: inline-block; box-shadow: 0 4px 10px rgba(0,185,0,0.3); letter-spacing: 1px;">加入官方 LINE 客服</a>
            </div>
        </div>
        <div style="background: #eee; padding: 15px; text-align: center; font-size: 12px; color: #999;">承天中承府 ‧ 嘉義市新生路337號<br><span style="font-size:11px;">(此為系統自動發送信件，請勿直接回覆)</span></div>
    </div>
    """

def generate_donation_created_email(order):
    cust = order['customer']
    items = order['items']
    tw_now = datetime.utcnow() + timedelta(hours=8)
    created_at_str = tw_now.strftime('%Y/%m/%d %H:%M')
    bank_html = get_bank_info()
    
    items_rows = ""
    for item in items:
        items_rows += f'<tr style="border-bottom: 1px solid #eee;"><td style="padding: 10px; color:#333;">{item["name"]}</td><td style="padding: 10px; text-align: center; color:#333;">x{item["qty"]}</td><td style="padding: 10px; text-align: right;">${item["price"] * item["qty"]}</td></tr>'

    return f"""
    <div style="font-family: 'Microsoft JhengHei', sans-serif; max-width: 600px; margin: 0 auto; border: 1px solid #ddd; border-radius: 8px; overflow: hidden; background-color:#fff;">
        <div style="background: #C48945; padding: 20px; text-align: center;">
            <h2 style="color: #fff; margin: 0; letter-spacing: 1px;">護持登記確認</h2>
            <p style="color: #fff; opacity: 0.9; margin: 5px 0 0 0; font-size: 14px;">單號：{order['orderId']}</p>
        </div>
        <div style="padding: 30px;">
            <p style="font-size: 16px; color: #333; margin-bottom: 20px;">親愛的 <strong>{cust['name']}</strong> 您好：</p>
            <div style="font-size: 15px; color: #555; line-height: 1.6;">
                感恩您的發心！我們已收到您護持公壇的意願登記。<br>這是一份來自善念的承諾，為了讓這份心意能順利化作助人的力量，請您於 <strong>2 小時內</strong> 完成匯款，以圓滿此次護持。<br><br><strong>【您的護持項目】</strong>
            </div>
            <div style="margin-top: 15px;">
                <table style="width: 100%; border-collapse: collapse; font-size: 14px;">
                    <thead><tr style="background: #f9f9f9; color:#666;"><th style="padding: 10px; text-align: left;">項目</th><th style="padding: 10px; text-align: center;">數量</th><th style="padding: 10px; text-align: right;">金額</th></tr></thead>
                    <tbody>{items_rows}</tbody>
                    <tfoot><tr><td colspan="2" style="padding:15px 10px; text-align:right; font-weight:bold; color:#333;">護持總金額</td><td style="padding:15px 10px; text-align:right; font-weight:bold; color:#C48945; font-size:18px;">NT$ {order['total']}</td></tr></tfoot>
                </table>
            </div>
            <div style="background:#fffcf5; padding:15px; border-left:4px solid #C48945; margin:20px 0; color:#555;">
                <strong>【匯款資訊】</strong><br>{bank_html}
                <div style="margin-top:8px;">您的匯款後五碼：<strong>{cust['last5']}</strong></div>
            </div>
            <div style="font-size: 14px; color: #666; margin-top: 20px; border-top: 1px dashed #ddd; padding-top: 15px;">
                <strong>【重要提醒】</strong><ol style="margin-left: -20px; margin-top: 5px;"><li>確認善款入帳後，我們將寄發「電子感謝狀」給您。</li><li><strong>防詐騙提醒</strong>：帥府人員不會致電要求您操作 ATM 或變更轉帳設定。若有疑慮，請務必點擊下方按鈕向官方 LINE 查證。</li></ol>
            </div>
            <div style="text-align: center; margin-top: 30px;">
                <a href="https://line.me/R/ti/p/@566dcres" target="_blank" style="background: #00B900; color: #fff; text-decoration: none; padding: 12px 35px; border-radius: 50px; font-weight: bold; display: inline-block; box-shadow: 0 4px 10px rgba(0,185,0,0.3); letter-spacing: 1px;">加入官方 LINE 客服</a>
            </div>
        </div>
        <div style="background: #eee; padding: 15px; text-align: center; font-size: 12px; color: #999;">承天中承府 ‧ 嘉義市新生路337號</div>
    </div>
    """

def generate_donation_paid_email(cust, order_id, items):
    items_str = "<br>".join([f"• {i['name']} x {i['qty']}" for i in items])
    return f"""
    <div style="font-family: 'KaiTi', 'Microsoft JhengHei', serif; max-width: 600px; margin: 0 auto; border: 4px double #C48945; padding: 40px; background-color: #fffcf5; color: #333;">
        <div style="text-align: center;">
            <h1 style="color: #C48945; font-size: 32px; margin-bottom: 10px;">感謝狀</h1>
            <p style="font-size: 16px; color: #888;">承天中承府 ‧ 煙島中壇元帥</p>
        </div>
        <hr style="border: 0; border-top: 1px solid #C48945; margin: 20px 0;">
        <p style="font-size: 18px; line-height: 1.8;">
            親愛的 <strong>{cust['name']}</strong> 您好：<br><br>
            感謝您的無私護持！您的善款已確認入帳。<br>
            承天中承府的公壇，不只是神明的駐地，更是十方善信共同守護的心靈家園。每一次開壇辦事、每一份為信徒解惑的努力，背後都仰賴著志工們的汗水，以及像您這樣發心護持的善信。<br>
            是您的這份心意，讓帥府的香火得以延續，讓濟世的聖務能夠圓滿。
        </p>
        <div style="background: #f0ebe5; padding: 20px; border-radius: 8px; margin: 20px 0; border-left: 5px solid #8B4513;">
            <h3 style="margin-top:0; color:#8B4513; font-size:20px;">【稟報通知】</h3>
            <p style="margin-bottom:0; font-size:16px; line-height:1.6;">
                您的名字與護持項目，將錄入芳名錄。<br>我們將於 <strong>下一次公壇辦事日</strong>，由 <strong>元帥娘</strong> 親自向 <strong>煙島中壇元帥</strong> 逐一稟報，將您的心意上達天聽。
            </p>
        </div>
        <p style="font-size: 18px; font-weight: bold; color: #C48945; margin-bottom: 10px;">【護持項目明細】</p>
        <div style="padding-left: 15px; margin-bottom: 20px; font-size: 16px; line-height: 1.6;">{items_str}</div>
        <p style="font-size: 18px; line-height: 1.8;">祈求元帥庇佑您：<br><strong>闔家平安，萬事如意</strong></p>
        <p style="margin-top: 40px; text-align: right; font-size: 16px;">承天中承府 敬謝<br>{datetime.now().strftime('%Y 年 %m 月 %d 日')}</p>
        <div style="text-align: center; margin-top: 40px;">
            <a href="https://line.me/R/ti/p/@566dcres" target="_blank" style="background: #00B900; color: #fff; text-decoration: none; padding: 10px 25px; border-radius: 50px; font-size: 14px; display: inline-block;">加入官方 LINE 客服</a>
            <div style="margin-top: 10px; font-size: 12px; color: #999;">(此為系統自動發送之電子感謝狀，請妥善保存)</div>
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
# 5. 後台頁面路由 & API
# =========================================
@app.route('/admin')
def admin_page(): return render_template('admin.html')

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

# --- Feedback API (新增 3 階段支援 + 寄信) ---
@app.route('/api/feedback', methods=['POST'])
def add_feedback():
    if db is None: return jsonify({"error": "DB Error"}), 500
    data = request.get_json()
    if not data.get('agreed'): return jsonify({"error": "必須勾選同意條款"}), 400
    new_feedback = {
        "realName": data.get('realName'), "nickname": data.get('nickname'),
        "category": data.get('category', []), "content": data.get('content'),
        "lunarBirthday": data.get('lunarBirthday', ''), "birthTime": data.get('birthTime') or '吉時',
        "address": data.get('address', ''), "phone": data.get('phone', ''),
        "email": data.get('email', ''), # 確保前端有傳 email
        "agreed": True, "createdAt": datetime.utcnow(), 
        "status": "pending", "isMarked": False
    }
    db.feedback.insert_one(new_feedback)
    return jsonify({"success": True, "message": "回饋已送出"})

# 1. 待審核 (pending)
@app.route('/api/feedback/pending', methods=['GET']) # 相容舊網址
@app.route('/api/feedback/status/pending', methods=['GET'])
@login_required
def get_pending_feedback():
    cursor = db.feedback.find({"status": "pending"}).sort("createdAt", 1)
    return jsonify([{**doc, '_id': str(doc['_id']), 'createdAt': doc['createdAt'].strftime('%Y-%m-%d %H:%M:%S')} for doc in cursor])

# 2. 已核准/待寄送 (approved)
@app.route('/api/feedback/approved', methods=['GET']) # 相容舊網址
@app.route('/api/feedback/status/approved', methods=['GET'])
@login_required
def get_approved_feedback():
    cursor = db.feedback.find({"status": "approved"}).sort("createdAt", -1)
    return jsonify([{**doc, '_id': str(doc['_id']), 'createdAt': doc['createdAt'].strftime('%Y-%m-%d %H:%M:%S')} for doc in cursor])

# 3. 已寄送 (sent) - 新增
@app.route('/api/feedback/status/sent', methods=['GET'])
@login_required
def get_sent_feedback():
    cursor = db.feedback.find({"status": "sent"}).sort("sentAt", -1)
    return jsonify([{**doc, '_id': str(doc['_id']), 'sentAt': doc.get('sentAt', doc['createdAt']).strftime('%Y-%m-%d %H:%M')} for doc in cursor])

# 核准回饋 (自動寄信)
@app.route('/api/feedback/<fid>/approve', methods=['PUT'])
@login_required
def approve_feedback(fid):
    fb = db.feedback.find_one({'_id': ObjectId(fid)})
    if not fb: return jsonify({"error": "No data"}), 404
    
    # 產生編號 (FB + 日期 + 隨機)
    fb_id = f"FB{datetime.now().strftime('%Y%m%d')}{random.randint(10,99)}"
    
    db.feedback.update_one({'_id': ObjectId(fid)}, {
        '$set': {
            'status': 'approved', 
            'feedbackId': fb_id,
            'approvedAt': datetime.utcnow()
        }
    })
    
    # 寄信通知
    if fb.get('email'):
        subject = "【承天中承府】您的回饋已核准刊登"
        body = f"""
        親愛的 {fb['realName']} 您好：
        感謝您的感應故事分享，我們已審核通過並刊登於官網。
        這份法布施將讓更多人感受到元帥的威靈。
        
        為了感謝您的發心，我們將準備一份「小神衣」與您結緣。
        待結緣品寄出時，會再發信通知您留意查收。
        
        承天中承府 敬上
        """
        send_email(fb['email'], subject, body)
        
    return jsonify({"success": True})

# 寄送禮物 (更新狀態 + 寄信)
@app.route('/api/feedback/<fid>/ship', methods=['PUT'])
@login_required
def ship_feedback(fid):
    data = request.get_json()
    tracking = data.get('trackingNumber', '')
    fb = db.feedback.find_one({'_id': ObjectId(fid)})
    if not fb: return jsonify({"error": "No data"}), 404
    
    db.feedback.update_one({'_id': ObjectId(fid)}, {
        '$set': {
            'status': 'sent', 
            'trackingNumber': tracking,
            'sentAt': datetime.utcnow()
        }
    })
    
    if fb.get('email'):
        subject = "【承天中承府】結緣品寄出通知"
        body = f"""
        親愛的 {fb['realName']} 您好：
        
        元帥娘親自開符加持的「小神衣」已於今日寄出！
        物流單號：{tracking}
        
        願元帥庇佑您平安順遂，萬事如意。
        
        承天中承府 敬上
        """
        send_email(fb['email'], subject, body)
        
    return jsonify({"success": True})

# 刪除回饋 (寄送遺憾信)
@app.route('/api/feedback/<fid>', methods=['DELETE'])
@login_required
def delete_feedback(fid):
    fb = db.feedback.find_one({'_id': ObjectId(fid)})
    if fb and fb.get('email'):
        subject = "【承天中承府】關於您的回饋投稿"
        body = f"""
        親愛的 {fb['realName']} 您好：
        
        感謝您撥冗分享與元帥的故事。
        經內部審核，您的投稿內容可能因版面規劃或其他考量，此次暫無法刊登，敬請見諒。
        
        感謝您的支持與諒解。
        承天中承府 敬上
        """
        send_email(fb['email'], subject, body)
        
    db.feedback.delete_one({'_id': ObjectId(fid)})
    return jsonify({"success": True})

@app.route('/api/feedback/<fid>', methods=['PUT'])
@login_required
def update_feedback(fid):
    data = request.get_json()
    fields = {k: data.get(k) for k in ['realName', 'nickname', 'category', 'content', 'lunarBirthday', 'birthTime', 'address', 'phone']}
    db.feedback.update_one({'_id': ObjectId(fid)}, {'$set': fields})
    return jsonify({"success": True})

@app.route('/api/feedback/download-unmarked', methods=['POST'])
@login_required
def download_unmarked_feedback():
    return jsonify({"error": "Deprecated"}), 410

# 匯出未寄送名單 (TXT)
@app.route('/api/feedback/export-txt', methods=['POST'])
@login_required
def export_feedback_txt():
    cursor = db.feedback.find({"status": "approved"}).sort("approvedAt", 1)
    if db.feedback.count_documents({"status": "approved"}) == 0:
        return jsonify({"error": "無資料"}), 404
    
    si = io.StringIO()
    si.write(f"匯出時間: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n")
    for doc in cursor:
        si.write(f"【編號】{doc.get('feedbackId', '無')}\n")
        si.write(f"姓名：{doc['realName']}\n")
        si.write(f"電話：{doc['phone']}\n")
        si.write(f"地址：{doc['address']}\n")
        si.write("-" * 30 + "\n")
    
    return Response(si.getvalue(), mimetype='text/plain', headers={"Content-Disposition": "attachment;filename=feedback_list.txt"})

# --- Settings API (匯款資訊) ---
@app.route('/api/settings/bank', methods=['GET', 'POST'])
@login_required
def handle_bank_settings():
    if request.method == 'GET':
        settings = db.settings.find_one({"type": "bank_info"}) or {}
        settings['_id'] = str(settings.get('_id', ''))
        return jsonify(settings)
    else:
        data = request.get_json()
        db.settings.update_one(
            {"type": "bank_info"},
            {"$set": {
                "bankCode": data.get('bankCode'),
                "bankName": data.get('bankName'),
                "account": data.get('account')
            }},
            upsert=True
        )
        return jsonify({"success": True})

# --- 其他 API ---
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
    if not correct_answer or user_captcha != correct_answer: return jsonify({"success": False, "message": "驗證碼錯誤"}), 400
    if not all(k in data and data[k] for k in ['name', 'lineGroup', 'lineName', 'birthYear', 'clothes']): return jsonify({"success": False, "message": "所有欄位皆為必填"}), 400
    now_tw = datetime.utcnow() + timedelta(hours=8)
    pickup_date = calculate_business_d2(now_tw)
    db.shipments.insert_one({
        "name": data['name'], "birthYear": data['birthYear'], "lineGroup": data['lineGroup'], "lineName": data['lineName'],
        "clothes": data['clothes'], "submitDate": now_tw, "submitDateStr": now_tw.strftime('%Y/%m/%d'),
        "pickupDate": pickup_date, "pickupDateStr": pickup_date.strftime('%Y/%m/%d')
    })
    return jsonify({"success": True, "pickupDate": pickup_date.strftime('%Y/%m/%d')})

@app.route('/api/shipclothes/list', methods=['GET'])
def get_ship_clothes_list():
    if db is None: return jsonify([]), 500
    now_tw = datetime.utcnow() + timedelta(hours=8)
    today_date = now_tw.replace(hour=0, minute=0, second=0, microsecond=0)
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
    if db is None: return jsonify([]), 500
    cursor = db.orders.find({"status": "paid", "orderType": "donation"}).sort("updatedAt", -1).limit(30)
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
    start_str = request.args.get('start')
    end_str = request.args.get('end')
    query = {"orderType": "donation"}
    if start_str and end_str:
        try:
            start_date = datetime.strptime(start_str, '%Y-%m-%d')
            end_date = datetime.strptime(end_str, '%Y-%m-%d') + timedelta(days=1)
            query["createdAt"] = {"$gte": start_date, "$lt": end_date}
        except: pass
    cursor = db.orders.find(query).sort([("status", 1), ("createdAt", -1)])
    results = []
    for doc in cursor:
        doc['_id'] = str(doc['_id'])
        doc['createdAt'] = doc['createdAt'].strftime('%Y-%m-%d %H:%M')
        doc['paidAt'] = doc.get('paidAt').strftime('%Y-%m-%d %H:%M') if doc.get('paidAt') else ''
        results.append(doc)
    return jsonify(results)

# 捐贈匯出 (TXT 格式)
@app.route('/api/donations/export-txt', methods=['POST'])
@login_required
def export_donations_txt():
    data = request.get_json()
    start_str = data.get('start')
    end_str = data.get('end')
    query = {"orderType": "donation", "status": "paid"}
    if start_str and end_str:
        try:
            start_date = datetime.strptime(start_str, '%Y-%m-%d')
            end_date = datetime.strptime(end_str, '%Y-%m-%d') + timedelta(days=1)
            query["updatedAt"] = {"$gte": start_date, "$lt": end_date}
        except: pass
    cursor = db.orders.find(query).sort("updatedAt", 1)
    
    si = io.StringIO()
    si.write(f"捐贈稟報清單\n匯出日期：{datetime.now().strftime('%Y-%m-%d')}\n")
    si.write("="*40 + "\n\n")
    
    idx = 1
    for doc in cursor:
        cust = doc.get('customer', {})
        items_str = "、".join([f"{i['name']}x{i['qty']}" for i in doc.get('items', [])])
        paid_date = doc.get('updatedAt').strftime('%Y/%m/%d') if doc.get('updatedAt') else ''
        
        si.write(f"【{idx}】\n")
        si.write(f"日期：{paid_date}\n")
        si.write(f"姓名：{cust.get('name', '')}\n")
        si.write(f"農曆：{cust.get('lunarBirthday', '')}\n")
        si.write(f"地址：{cust.get('address', '')}\n")
        si.write(f"項目：{items_str}\n")
        si.write("-" * 20 + "\n")
        idx += 1
        
    return Response(si.getvalue(), mimetype='text/plain', headers={"Content-Disposition": f"attachment; filename=donation_list.txt"})

@app.route('/api/donations/cleanup-unpaid', methods=['DELETE'])
@login_required
def cleanup_unpaid_orders():
    cutoff = datetime.utcnow() - timedelta(hours=76)
    # 刪除前先寄信
    cursor = db.orders.find({"status": "pending", "createdAt": {"$lt": cutoff}})
    for order in cursor:
        if order.get('customer', {}).get('email'):
            subject = f"【承天中承府】訂單/捐贈登記已取消 ({order['orderId']})"
            body = f"親愛的 {order['customer']['name']} 您好：\n您的訂單/捐贈登記 ({order['orderId']}) 因超過付款期限，系統已自動取消。如需服務請重新下單。"
            send_email(order['customer']['email'], subject, body)
    
    result = db.orders.delete_many({"status": "pending", "createdAt": {"$lt": cutoff}})
    return jsonify({"success": True, "count": result.deleted_count})

@app.route('/api/orders', methods=['POST'])
def create_order():
    if db is None: return jsonify({"error": "DB Error"}), 500
    data = request.get_json()
    order_type = data.get('orderType', 'shop')
    order_id = f"{'DON' if order_type == 'donation' else 'ORD'}{datetime.now().strftime('%Y%m%d%H%M%S')}{random.randint(10,99)}"
    customer_info = {
        "name": data.get('name'), "phone": data.get('phone'), "email": data.get('email', ''),
        "address": data.get('address'), "last5": data.get('last5'),
        "lunarBirthday": data.get('lunarBirthday', ''), "prayer": data.get('prayer', '') 
    }
    order = {
        "orderId": order_id, "orderType": order_type, "customer": customer_info,
        "items": data['items'], "total": data['total'], "status": "pending",
        "createdAt": datetime.utcnow(), "updatedAt": datetime.utcnow()
    }
    db.orders.insert_one(order)
    
    if order_type == 'donation':
        email_subject = f"【承天中承府】護持登記確認通知 ({order_id})"
        email_html = generate_donation_created_email(order)
        send_email(customer_info['email'], email_subject, email_html, is_html=True)
    else:
        email_subject = f"【承天中承府】訂單確認通知 ({order_id})"
        email_html = generate_shop_email_html(order, 'created')
        send_email(customer_info['email'], email_subject, email_html, is_html=True)
    return jsonify({"success": True, "orderId": order_id})

@app.route('/api/orders', methods=['GET'])
@login_required
def get_orders():
    cursor = db.orders.find({"orderType": {"$ne": "donation"}}).sort("createdAt", -1)
    results = []
    for doc in cursor:
        doc['_id'] = str(doc['_id'])
        if 'createdAt' in doc: doc['createdAt'] = (doc['createdAt'] + timedelta(hours=8)).strftime('%Y-%m-%d %H:%M')
        if 'shippedAt' in doc and doc['shippedAt']: doc['shippedAt'] = (doc['shippedAt'] + timedelta(hours=8)).strftime('%Y-%m-%d %H:%M')
        else: doc['shippedAt'] = ''
        results.append(doc)
    return jsonify(results)

@app.route('/api/orders/cleanup-shipped', methods=['DELETE'])
@login_required
def cleanup_shipped_orders():
    cutoff = datetime.utcnow() - timedelta(days=14)
    result = db.orders.delete_many({"status": "shipped", "shippedAt": {"$lt": cutoff}})
    return jsonify({"success": True, "count": result.deleted_count})

@app.route('/api/orders/<oid>/confirm', methods=['PUT'])
@login_required
def confirm_order_payment(oid):
    order = db.orders.find_one({'_id': ObjectId(oid)})
    if not order: return jsonify({"error": "No order"}), 404
    now = datetime.utcnow()
    db.orders.update_one({'_id': ObjectId(oid)}, {'$set': {'status': 'paid', 'updatedAt': now, 'paidAt': now}})
    cust = order['customer']
    if order.get('orderType') == 'donation':
        email_subject = f"【承天中承府】電子感謝狀 - 功德無量 ({order['orderId']})"
        email_html = generate_donation_paid_email(cust, order['orderId'], order['items'])
        send_email(cust.get('email'), email_subject, email_html, is_html=True)
    else:
        email_subject = f"【承天中承府】收款確認通知 ({order['orderId']})"
        email_html = generate_shop_email_html(order, 'paid')
        send_email(cust.get('email'), email_subject, email_html, is_html=True)
    return jsonify({"success": True})

@app.route('/api/orders/<oid>/resend-email', methods=['POST'])
@login_required
def resend_order_email(oid):
    data = request.get_json()
    new_email = data.get('email')
    order = db.orders.find_one({'_id': ObjectId(oid)})
    if not order: return jsonify({"error": "No order"}), 404
    cust = order['customer']
    target_email = cust.get('email')
    if new_email and new_email != target_email:
        db.orders.update_one({'_id': ObjectId(oid)}, {'$set': {'customer.email': new_email}})
        cust['email'] = new_email
        target_email = new_email
        
    if order.get('orderType') == 'donation':
        if order.get('status') == 'paid':
            email_subject = f"【補寄感謝狀】承天中承府 - 功德無量 ({order['orderId']})"
            email_html = generate_donation_paid_email(cust, order['orderId'], order['items'])
        else:
            email_subject = f"【補寄】護持登記確認通知 ({order['orderId']})"
            email_html = generate_donation_created_email(order)
    else:
        email_subject = f"【承天中承府】訂單信件補寄 ({order['orderId']})"
        if order.get('status') == 'shipped': email_html = generate_shop_email_html(order, 'shipped', order.get('trackingNumber'))
        elif order.get('status') == 'paid': email_html = generate_shop_email_html(order, 'paid')
        else: email_html = generate_shop_email_html(order, 'created')
    send_email(target_email, email_subject, email_html, is_html=True)
    return jsonify({"success": True})

@app.route('/api/orders/<oid>', methods=['DELETE'])
@login_required
def delete_order(oid):
    order = db.orders.find_one({'_id': ObjectId(oid)})
    if order and order.get('customer', {}).get('email'):
        subject = f"【承天中承府】訂單/登記已取消 ({order['orderId']})"
        body = f"親愛的 {order['customer']['name']} 您好：\n您的訂單/登記 ({order['orderId']}) 已被取消。如為誤操作或有任何疑問，請聯繫官方 LINE。"
        send_email(order['customer']['email'], subject, body)
    db.orders.delete_one({'_id': ObjectId(oid)})
    return jsonify({"success": True})

@app.route('/api/products', methods=['GET'])
def get_products():
    products = list(db.products.find().sort([("category", 1), ("createdAt", -1)]))
    for p in products: p['_id'] = str(p['_id'])
    return jsonify(products)

@app.route('/api/products', methods=['POST'])
@login_required
def add_product():
    data = request.get_json()
    new_product = {
        "name": data.get('name'), "category": data.get('category', '其他'), "price": int(data.get('price', 0)),
        "description": data.get('description', ''), "image": data.get('image', ''), "isActive": data.get('isActive', True),
        "isDonation": data.get('isDonation', False), "variants": data.get('variants', []), "createdAt": datetime.utcnow()
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
    db.announcements.insert_one({
        "date": datetime.strptime(data['date'], '%Y/%m/%d'), "title": data['title'],
        "content": data['content'], "isPinned": data.get('isPinned', False), "createdAt": datetime.utcnow()
    })
    return jsonify({"success": True})

@app.route('/api/announcements/<aid>', methods=['PUT'])
@login_required
def update_announcement(aid):
    data = request.get_json()
    db.announcements.update_one({'_id': ObjectId(aid)}, {'$set': {
        "date": datetime.strptime(data['date'], '%Y/%m/%d'), "title": data['title'],
        "content": data['content'], "isPinned": data.get('isPinned', False)
    }})
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
    if not re.match(r'^[\u4e00-\u9fff]+$', data.get('category', '')): return jsonify({"error": "分類限中文"}), 400
    db.faq.insert_one({
        "question": data['question'], "answer": data['answer'], "category": data['category'],
        "isPinned": data.get('isPinned', False), "createdAt": datetime.utcnow()
    })
    return jsonify({"success": True})

@app.route('/api/faq/<fid>', methods=['PUT'])
@login_required
def update_faq(fid):
    data = request.get_json()
    db.faq.update_one({'_id': ObjectId(fid)}, {'$set': {
        "question": data['question'], "answer": data['answer'], "category": data['category'], "isPinned": data.get('isPinned', False)
    }})
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
    db.temple_fund.update_one({"type": "main_fund"}, {"$set": {"goal_amount": int(data.get('goal_amount', 0)), "current_amount": int(data.get('current_amount', 0))}}, upsert=True)
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

@app.route('/api/orders/<oid>/ship', methods=['PUT'])
@login_required
def ship_order(oid):
    data = request.get_json() or {}
    tracking_num = data.get('trackingNumber', '').strip()
    order = db.orders.find_one({'_id': ObjectId(oid)})
    if not order: return jsonify({"error": "No order"}), 404
    now = datetime.utcnow()
    db.orders.update_one({'_id': ObjectId(oid)}, {'$set': {
        'status': 'shipped', 'updatedAt': now, 'shippedAt': now, 'trackingNumber': tracking_num
    }})
    cust = order['customer']
    email_subject = f"【承天中承府】訂單出貨通知 ({order['orderId']})"
    email_html = generate_shop_email_html(order, 'shipped', tracking_num)
    send_email(cust.get('email'), email_subject, email_html, is_html=True)
    return jsonify({"success": True})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)