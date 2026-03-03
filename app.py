import os
import requests
import secrets
import urllib.parse
import re
import random
import json
import threading
import urllib.request
import urllib.error
import io
import csv
from email.mime.text import MIMEText
from email.header import Header
from functools import wraps
from datetime import datetime, timedelta
from flask import Flask, jsonify, render_template, request, session, redirect, url_for, Response, make_response
from flask_cors import CORS
from flask_wtf.csrf import CSRFProtect
from pymongo import MongoClient
from bson import ObjectId
from bson.errors import InvalidId  # [資安修正] 引入錯誤型別
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

# === 郵件設定 (改用 SendGrid API) ===
# 請在 Render 環境變數設定 SENDGRID_API_KEY
SENDGRID_API_KEY = os.environ.get('SENDGRID_API_KEY')
# === LINE 登入設定 ===
LINE_CHANNEL_ID = os.environ.get('LINE_CHANNEL_ID')
LINE_CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET')
LINE_CALLBACK_URL = os.environ.get('LINE_CALLBACK_URL')
# MAIL_USERNAME 作為 "寄件人信箱" (必須與 SendGrid 驗證的 Sender Identity 一致)
MAIL_SENDER = os.environ.get('MAIL_USERNAME') 

# 流量限制
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["3000 per day", "1000 per hour"],
    storage_uri="memory://"
)

# CSRF & CORS
csrf = CSRFProtect(app)
# 設定允許的來源列表 (白名單)
allowed_origins = [
    "http://localhost:5000",
    "http://127.0.0.1:5000",
    "http://140.119.143.95:5000",
    "https://yandao.onrender.com",
]

CORS(app, 
     resources={r"/api/*": {"origins": allowed_origins}}, 
     supports_credentials=True)

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
        if 'admin_logged_in' not in session:
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

def get_object_id(fid):
    """
    [資安修正] 安全地轉換 ObjectId
    若格式錯誤，回傳 None，避免 500 Server Error
    """
    try:
        return ObjectId(fid)
    except (InvalidId, TypeError):
        return None

# === 新版寄信功能 (SendGrid API + 雙階段背景執行) ===

def send_email_task(to_email, subject, body, is_html=False):
    """
    【背景任務】加強 Debug 版
    """
    print(f"--- 準備寄信給: {to_email} ---") # Debug: 確認有進入函式

    if not SENDGRID_API_KEY:
        print("❌ 錯誤: 環境變數 SENDGRID_API_KEY 未設定")
        return
    if not MAIL_SENDER:
        print("❌ 錯誤: 環境變數 MAIL_USERNAME 未設定 (這應該是您的寄件者 Email)")
        return

    # SendGrid API 網址
    url = "https://api.sendgrid.com/v3/mail/send"

    # 建構 JSON 資料
    payload = {
        "personalizations": [{"to": [{"email": to_email}]}],
        "from": {"email": MAIL_SENDER},
        "subject": subject,
        "content": [{
            "type": "text/html" if is_html else "text/plain",
            "value": body
        }]
    }

    headers = {
        "Authorization": f"Bearer {SENDGRID_API_KEY}",
        "Content-Type": "application/json"
    }

    try:
        req = urllib.request.Request(
            url, 
            data=json.dumps(payload).encode('utf-8'), 
            headers=headers, 
            method='POST'
        )
        
        with urllib.request.urlopen(req) as response:
            print(f"✅ SendGrid 寄信成功! Status: {response.status}")

    except urllib.error.HTTPError as e:
        # 讀取詳細錯誤訊息
        try:
            error_body = e.read().decode('utf-8')
        except:
            error_body = "無法讀取內容"
        print(f"❌ SendGrid API 回傳錯誤 ({e.code}):")
        print(f"   錯誤內容: {error_body}")
        print(f"   檢查重點: 1. API Key 是否正確? 2. MAIL_USERNAME ({MAIL_SENDER}) 是否已在 SendGrid 驗證過?")
        
    except Exception as e:
        print(f"❌ 寄信發生未知例外錯誤: {str(e)}")

def send_email(to_email, subject, body, is_html=False):
    """
    【主程式呼叫點】
    老闆只負責發號施令，建立一個新執行緒 (Thread) 去寄信，
    然後立刻返回，確保訂單流程不卡頓。
    """
    if not to_email:
        return
        
    # 啟動背景執行緒 (Fire-and-forget)
    thread = threading.Thread(
        target=send_email_task, 
        args=(to_email, subject, body, is_html)
    )
    thread.start()

# === Email 樣板產生器 ===

def get_bank_info(usage='shop'):
    """
    從資料庫讀取匯款資訊
    usage: 'fund' (建廟) 或 'shop' (一般/捐香)
    """
    if db is None: return "請聯繫廟方確認匯款資訊"
    
    # 決定要抓哪一組設定 (fund 用原本的 bank_info，shop 用新的 bank_info_shop)
    setting_key = "bank_info" if usage == 'fund' else "bank_info_shop"
    
    # 預設值 (避免空值報錯)
    defaults = {
        'fund': {'code': '103', 'name': '新光銀行', 'account': '0666-50-971133-3'},
        'shop': {'code': '808', 'name': '玉山銀行', 'account': '尚未設定'}
    }
    
    settings = db.settings.find_one({"type": setting_key}) or {}
    
    code = settings.get('bankCode', defaults[usage]['code'])
    name = settings.get('bankName', defaults[usage]['name'])
    account = settings.get('account', defaults[usage]['account'])
    
    return f"""
    銀行代碼：<strong>{code} ({name})</strong><br>
    銀行帳號：<strong>{account}</strong>
    """

# --- 回饋信件樣板 ---
def generate_feedback_email_html(feedback, status_type, tracking_num=None):
    """產生信徒回饋相關的 Email HTML"""
    name = feedback.get('realName', '信徒')
    
    if status_type == 'rejected':
        title = "感謝您的投稿與分享"
        content_body = f"""
        非常感謝您撥冗寫下與元帥的故事，我們已經收到您的投稿。<br><br>
        每一份分享都是對帥府最珍貴的支持。經內部審閱與討論後，由於目前的版面規劃與內容篩選考量，很遺憾此次<strong>暫時無法將您的文章刊登於官網</strong>，還請您見諒。<br><br>
        雖然文字未能在網上呈現，但您對元帥的這份心意，帥府上下都已深深感受到。歡迎您持續關注我們，也期待未來還有機會聽到您的分享。<br><br>
        闔家平安，萬事如意
        """
    elif status_type == 'approved':
        title = "您的回饋已核准刊登"
        content_body = f"""
        感謝分享您與元帥的故事！您的文章已審核通過，並正式<strong>刊登於承天中承府官方網站</strong>。這份法布施將讓更多有緣人感受到元帥的威靈與慈悲。<br><br>
        為了感謝您的發心，元帥娘特別準備了一份「小神衣」要與您結緣。<br><br>
        <div style="background:#fffcf5; padding:15px; border-left:4px solid #C48945; margin:15px 0; color:#555;">
            <strong>⚡ 元帥娘開符加持中</strong><br>
            目前元帥娘正在親自為小神衣進行「開符」與加持儀式，以確保將滿滿的祝福送到您手中。待儀式圓滿並寄出後，系統會再發送一封信件通知您，這段時間請您留意 Email 信箱。
        </div>
        <br>
        再次感謝您的分享！
        """
    elif status_type == 'sent':
        title = "小神衣寄出通知"
        content_body = f"""
        讓您久等了！<br>
        經過元帥娘開符加持的「小神衣」已於今日為您寄出。這份結緣品承載著帥府的祝福，希望能常伴您左右，護佑平安。<br><br>
        <div style="background:#f0ebe5; padding:15px; border:1px solid #C48945; border-radius:8px;">
            <strong>📦 物流單號：{tracking_num}</strong><br>
            <span style="font-size:13px; color:#666;">您可以透過此單號查詢配送進度。</span>
        </div><br>
        收到後若有任何問題，歡迎隨時透過官方 LINE 與我們聯繫。<br><br>
        願 煙島中壇元帥 庇佑您<br>
        身體健康，順心如意
        """
    else:
        title = "承天中承府通知"
        content_body = ""

    return f"""
    <div style="font-family: 'Microsoft JhengHei', sans-serif; max-width: 600px; margin: 0 auto; border: 1px solid #ddd; border-radius: 8px; overflow: hidden; background-color:#fff;">
        <div style="background: #C48945; padding: 20px; text-align: center;">
            <h2 style="color: #fff; margin: 0; letter-spacing: 1px;">{title}</h2>
        </div>
        <div style="padding: 30px;">
            <p style="font-size: 16px; color: #333; margin-bottom: 20px;">親愛的 <strong>{name}</strong> 您好：</p>
            <div style="font-size: 15px; color: #555; line-height: 1.6;">
                {content_body}
            </div>
            <div style="text-align: center; margin-top: 40px;">
                <a href="https://line.me/R/ti/p/@566dcres" target="_blank" style="background: #00B900; color: #fff; text-decoration: none; padding: 12px 35px; border-radius: 50px; font-weight: bold; display: inline-block; box-shadow: 0 4px 10px rgba(0,185,0,0.3); letter-spacing: 1px;">加入官方 LINE 客服</a>
            </div>
        </div>
        <div style="background: #eee; padding: 15px; text-align: center; font-size: 12px; color: #999;">承天中承府 ‧ 嘉義市新生路337號<br><span style="font-size:11px;">(此為系統自動發送信件，請勿直接回覆)</span></div>
    </div>
    """

def generate_shop_email_html(order, status_type, tracking_num=None):
    cust = order['customer']
    items = order['items']
    tw_now = datetime.utcnow() + timedelta(hours=8)
    date_str = tw_now.strftime('%Y/%m/%d %H:%M')
    
    created_at_dt = order.get('createdAt')
    if created_at_dt and isinstance(created_at_dt, datetime):
        created_at_str = (created_at_dt + timedelta(hours=8)).strftime('%Y/%m/%d %H:%M')
    else:
        created_at_str = date_str

    # 強制使用 shop 帳號
    bank_html = get_bank_info('shop')
    
    # 判斷配送方式來決定顯示地址還是門市
    shipping_method = cust.get('shippingMethod', 'home')
    if shipping_method == '711':
        delivery_info_html = f"<strong>7-11 取貨門市：</strong>{cust.get('storeInfo', '未提供')}"
        shipping_label = "運費 (7-11 店到店)"
        shipping_fee_display = "60"
    else:
        delivery_info_html = f"<strong>收件地址：</strong>{cust.get('address', '未提供')}"
        shipping_label = "運費 (宅配)"
        shipping_fee_display = "120"
        
    # 如果資料庫裡有存實際運費，就用實際的 (相容舊資料)
    if 'shippingFee' in cust:
        shipping_fee_display = str(cust['shippingFee'])

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
        <strong>【配送資訊】</strong><br>
        {delivery_info_html}<br>
        聯絡電話：{cust.get('phone')}<br><br>
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
    else: 
        title = "帥府出貨通知"
        color = "#C48945"
        status_text = f"""
        您的訂單已於今日出貨！<br><br>
        <div style="background:#f0ebe5; padding:15px; border:1px solid #C48945; border-radius:8px;">
            <strong>📦 物流單號：{tracking_num}</strong><br>
            <span style="font-size:13px; color:#666;">請依照上方單號，自行至物流網站查詢配送進度。</span>
        </div><br>
        <strong>出貨日期：{date_str}</strong><br>
        {delivery_info_html}<br><br>
        <span style="color:#666;">商品收到若有問題，請點擊下方按鈕詢問官方 LINE。</span>
        """
        show_price = False

    items_rows = ""
    for item in items:
        spec = f" ({item['variant']})" if 'variant' in item and item['variant'] != '標準' else ""
        price_td = f'<td style="padding:10px; text-align:right;">${item["price"] * item["qty"]}</td>' if show_price else ''
        items_rows += f'<tr style="border-bottom: 1px solid #eee;"><td style="padding: 10px; color:#333;">{item["name"]}{spec}</td><td style="padding: 10px; text-align: center; color:#333;">x{item["qty"]}</td>{price_td}</tr>'
    
    # 這裡的 total_row 要加入運費顯示
    price_th = '<th style="padding:10px; text-align:right;">金額</th>' if show_price else ''
    total_row = f'''
    <tfoot>
        <tr>
            <td colspan="2" style="padding:10px 10px; text-align:right; color:#666;">{shipping_label}</td>
            <td style="padding:10px 10px; text-align:right; color:#666;">+ {shipping_fee_display}</td>
        </tr>
        <tr>
            <td colspan="2" style="padding:15px 10px; text-align:right; font-weight:bold; color:#333;">總計</td>
            <td style="padding:15px 10px; text-align:right; font-weight:bold; color:#C48945; font-size:18px;">NT$ {order["total"]}</td>
        </tr>
    </tfoot>''' if show_price else ''

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
    # ★ 修改這裡：判斷是 'fund' 還是 'donation'
    order_type = order.get('orderType', 'donation')
    # 如果是 fund 用原帳號，如果是 donation 用 shop 帳號
    bank_type = 'fund' if order_type == 'fund' else 'shop'
    bank_html = get_bank_info(bank_type)
    
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
                您的名字與護持項目，將錄入芳名錄。<br>我們將由 <strong>元帥娘</strong> 親自向 <strong>煙島中壇元帥</strong> 逐一稟報，將您的心意上達天聽。
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
# 4. 前台頁面路由 (修正：加入 SSR 資料預載)
# =========================================
@app.route('/profile')
def profile_page(): 
    return render_template('profile.html')
@app.route('/')
def home():
    # SEO 優化：伺服器端渲染 (SSR) 最新消息
    announcements_data = []
    try:
        if db is not None:
            # 預設抓取最新的 10 筆公告，讓爬蟲可以讀取
            cursor = db.announcements.find().sort([("isPinned", -1), ("date", -1)]).limit(10)
            for doc in cursor:
                doc['_id'] = str(doc['_id'])
                if 'date' in doc and isinstance(doc['date'], datetime):
                    doc['date'] = doc['date'].strftime('%Y/%m/%d')
                announcements_data.append(doc)
    except Exception as e:
        print(f"SSR Error (Home): {e}")
    
    # 將資料傳遞給 index.html
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

@app.route('/feedback')
def feedback_page():
    # SEO 優化：伺服器端渲染 (SSR) 信徒回饋
    # 讓爬蟲可以抓取到信徒分享的故事，增加長尾關鍵字曝光
    feedbacks_data = []
    try:
        if db is not None:
            # 只抓取已核准的，並依照核准時間排序，取前 20 筆
            cursor = db.feedback.find({"status": "approved"}).sort("approvedAt", -1).limit(20)
            for doc in cursor:
                # 簡單過濾敏感個資，只傳遞需要的欄位
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
    # SEO 優化：伺服器端渲染 (SSR) 常見問題
    faq_data = []
    try:
        if db is not None:
            # 抓取所有 FAQ 讓搜尋引擎建立索引
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
    """將使用者導向 LINE 的授權登入頁面"""
    if not LINE_CHANNEL_ID:
        return "伺服器尚未設定 LINE_CHANNEL_ID", 500
        
    # 產生一個隨機字串防護 CSRF 攻擊，並存入 session
    state = secrets.token_hex(16)
    session['line_state'] = state
    
    # 記錄信徒原本在哪個頁面點擊登入的 (例如 ?next=/feedback)
    next_url = request.args.get('next', '/')
    session['line_next_url'] = next_url

    # 組裝 LINE 授權網址
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
    """LINE 授權完畢後，回傳資料到這個網址"""
    code = request.args.get('code')
    state = request.args.get('state')
    session_state = session.get('line_state')

    # 1. 檢查 state 是否正確 (防偽造跨站請求)
    if state != session_state:
        return "登入狀態驗證失敗，請重新操作", 400

    # 2. 用 code 向 LINE 換取 Access Token
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

    # 3. 用 Access Token 獲取使用者的 LINE Profile
    profile_url = "https://api.line.me/v2/profile"
    profile_headers = {'Authorization': f'Bearer {access_token}'}
    profile_res = requests.get(profile_url, headers=profile_headers)
    
    if profile_res.status_code != 200:
        return "獲取使用者資料失敗", 400
        
    profile = profile_res.json()
    line_id = profile.get('userId')
    display_name = profile.get('displayName')
    picture_url = profile.get('pictureUrl', '')

    # 4. 存入 MongoDB 的 users 集合 (如果沒有這個人就新增，有就更新)
    if db is not None:
        db.users.update_one(
            {'lineId': line_id},
            {'$set': {
                'lineId': line_id,
                'displayName': display_name,
                'pictureUrl': picture_url,
                'lastLoginAt': datetime.utcnow()
            },
            '$setOnInsert': {'createdAt': datetime.utcnow()}},
            upsert=True
        )

    # 5. 在 Session 發放「一般會員登入證」
    session['user_line_id'] = line_id
    session['user_display_name'] = display_name
    session.permanent = True # 保持登入狀態

    # 6. 導回他們原本所在的頁面 (例如 /feedback)
    next_url = session.pop('line_next_url', '/')
    return redirect(next_url)

@app.route('/api/user/me', methods=['GET'])
def get_current_user():
    """前端用來檢查目前是否有登入，並取得基本資料"""
    line_id = session.get('user_line_id')
    if not line_id:
        return jsonify({"logged_in": False})
        
    if db is not None:
        user = db.users.find_one({'lineId': line_id}, {'_id': 0})
        if user:
            # 檢查是否領過小神衣 (只要有一筆回饋狀態是 sent 就代表領過了)
            has_received = db.feedback.count_documents({"lineId": line_id, "status": "sent"}) > 0
            user['has_received_gift'] = has_received
            return jsonify({"logged_in": True, "user": user})
            
    return jsonify({"logged_in": False})
@app.route('/api/user/profile', methods=['PUT'])
def update_user_profile():
    """讓信徒在個人專區修改自己的基本資料"""
    line_id = session.get('user_line_id')
    if not line_id:
        return jsonify({"error": "請先使用 LINE 登入"}), 401
        
    data = request.get_json()
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
def get_user_feedbacks():
    """撈出該登入信徒過去所有的回饋紀錄"""
    line_id = session.get('user_line_id')
    if not line_id:
        return jsonify({"error": "請先使用 LINE 登入"}), 401
        
    if db is not None:
        # 依時間新到舊排序
        cursor = db.feedback.find({"lineId": line_id}).sort("createdAt", -1)
        results = []
        for doc in cursor:
            # 截取前 50 個字作為預覽
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
                "trackingNumber": doc.get('trackingNumber', ''),
                "feedbackId": doc.get('feedbackId', '')
            })
        return jsonify(results)
    return jsonify([]), 500
# =========================================
# 收驚衣服預約取件 API (看板與個人專區)
# =========================================

def mask_name(name):
    """將姓名第二字遮蔽為 O，例如：許秉承 -> 許O承，王大 -> 王O"""
    if not name: return ""
    if len(name) == 1: return name
    if len(name) == 2: return name[0] + "O"
    return name[0] + "O" + name[2:]

@app.route('/api/pickup/reserve', methods=['POST'])
def create_pickup_reservation():
    """信徒送出預約單"""
    line_id = session.get('user_line_id')
    if not line_id:
        return jsonify({"error": "請先使用 LINE 登入"}), 401
        
    data = request.get_json()
    pickup_type = data.get('pickupType') # 'self' 或 'delivery'
    pickup_date = data.get('pickupDate')
    clothes = data.get('clothes', [])
    
    if not pickup_type or not pickup_date or not clothes:
        return jsonify({"error": "資料不完整"}), 400
    # ==========================================
    # ★ 新增檢查邏輯：防止衣服編號重複預約
    # ==========================================
    if db is not None:
        # 1. 取出這次請求中所有的衣服編號
        incoming_ids = [c.get('clothId', '').strip() for c in clothes if c.get('clothId')]
        
        # 2. 到資料庫檢查，這些編號是否已經存在於任何預約單中
        # 查詢條件：clothes 陣列裡的 clothId 欄位，包含在 incoming_ids 之中
        duplicate_order = db.pickups.find_one({
            "clothes.clothId": {"$in": incoming_ids}
        })
        
        # 3. 如果找到了重複的單子
        if duplicate_order:
            # 找出具體是哪一件重複，方便提示使用者
            found_id = ""
            for item in duplicate_order.get('clothes', []):
                if item.get('clothId') in incoming_ids:
                    found_id = item.get('clothId')
                    break
            
            error_msg = f"衣服編號【{found_id}】已經預約過了！請先至「個人專區」刪除舊的預約，才能重新安排。"
            return jsonify({"error": error_msg}), 400
    # ==========================================
    # ★ 檢查結束
    # ==========================================
    new_reservation = {
        "lineId": line_id,
        "pickupType": pickup_type,
        "pickupDate": pickup_date,
        "clothes": clothes,
        "createdAt": datetime.utcnow()
    }
    
    if db is not None:
        db.pickups.insert_one(new_reservation)
        return jsonify({"success": True, "message": "預約成功"})
    return jsonify({"error": "資料庫連線失敗"}), 500

@app.route('/api/pickup/public', methods=['GET'])
def get_public_pickups():
    """給門市人員與大眾看的電子佈告欄 (自動過濾與遮蔽)"""
    if db is None: return jsonify([])
    
    # 邏輯：計算台灣時間昨天的日期。
    # 這樣假設今天是 2/27，系統就只會抓 2/26 (包含) 以後的資料。
    # 2/25 的預約就會永遠從這份名單上消失！
    taiwan_now = datetime.utcnow() + timedelta(hours=8)
    threshold_date = (taiwan_now - timedelta(days=1)).strftime('%Y-%m-%d')
    
    cursor = db.pickups.find({"pickupDate": {"$gte": threshold_date}}).sort("pickupDate", 1)
    
# 依照日期將資料分組
    results = {}
    for doc in cursor:
        date_str = doc['pickupDate']
        p_type = doc['pickupType'] 
        
        if date_str not in results:
            results[date_str] = {'self': [], 'delivery': []}
            
        # ★ 修改這裡：把同一單的衣服包在一起，而不是打散
        masked_clothes = []
        for c in doc.get('clothes', []):
            masked_clothes.append({
                "clothId": c.get('clothId', ''),
                "name": mask_name(c.get('name', '')), # 執行姓名遮蔽
                "birthYear": c.get('birthYear', '')
            })
            
        # 將整組衣服作為「一包」塞進看板陣列中
        if masked_clothes:
            results[date_str][p_type].append({
                "clothes": masked_clothes
            })
            
    # 轉成陣列格式方便前端卡片渲染
    formatted_results = []
    for d in sorted(results.keys()):
        formatted_results.append({
            "date": d,
            "self": results[d]['self'],
            "delivery": results[d]['delivery']
        })
        
    return jsonify(formatted_results)

# === 修改原本的查詢 API，加入可否刪除的判斷 ===
@app.route('/api/user/pickups', methods=['GET'])
def get_user_pickups():
    """給信徒「個人專區」看的自己專屬預約紀錄 (不遮蔽姓名)"""
    line_id = session.get('user_line_id')
    if not line_id or db is None:
        return jsonify([])
        
    cursor = db.pickups.find({"lineId": line_id}).sort("pickupDate", -1)
    results = []
    
    # 取得台灣今天的日期 (用於比對)
    tw_now = datetime.utcnow() + timedelta(hours=8)
    today = tw_now.replace(hour=0, minute=0, second=0, microsecond=0)

    for doc in cursor:
        # 判斷是否可刪除：今天 < 取件日 (例如今天 3/1 < 取件 3/2，則可刪除)
        is_deletable = False
        try:
            p_date = datetime.strptime(doc.get('pickupDate'), '%Y-%m-%d')
            if today < p_date:
                is_deletable = True
        except:
            is_deletable = False

        results.append({
            "_id": str(doc['_id']),
            "pickupType": doc.get('pickupType'),
            "pickupDate": doc.get('pickupDate'),
            "clothes": doc.get('clothes', []),
            "createdAt": doc['createdAt'].strftime('%Y-%m-%d %H:%M'),
            "isDeletable": is_deletable  # 傳給前端
        })
    return jsonify(results)

# === 新增：刪除預約的 API ===
@app.route('/api/pickup/<pid>', methods=['DELETE'])
def delete_pickup(pid):
    line_id = session.get('user_line_id')
    if not line_id: return jsonify({"error": "請先登入"}), 401
    
    oid = get_object_id(pid)
    if not oid: return jsonify({"error": "格式錯誤"}), 400

    # 1. 確保是該使用者的預約
    pickup = db.pickups.find_one({"_id": oid, "lineId": line_id})
    if not pickup: return jsonify({"error": "找不到預約"}), 404

    # 2. 再次檢查日期 (防止有人繞過前端直接呼叫 API)
    try:
        p_date = datetime.strptime(pickup.get('pickupDate'), '%Y-%m-%d')
        tw_now = datetime.utcnow() + timedelta(hours=8)
        today = tw_now.replace(hour=0, minute=0, second=0, microsecond=0)
        
        if today >= p_date:
            return jsonify({"error": "已超過取消期限 (限取件日前一天)"}), 400
    except:
        return jsonify({"error": "日期資料異常"}), 400

    db.pickups.delete_one({"_id": oid})
    return jsonify({"success": True})
# =========================================
# 5. 後台頁面路由 & API
# =========================================
@app.route('/admin')
def admin_page(): return render_template('admin.html')

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
    """【後台專用輔助函式】自動將回饋與會員資料表合併，並標記是否領過神衣"""
    results = []
    for doc in cursor:
        line_id = doc.get('lineId')
        user = db.users.find_one({"lineId": line_id}) if line_id else {}
        # 檢查該 LINE ID 過去是否有 status=sent 的紀錄
        has_received = db.feedback.count_documents({"lineId": line_id, "status": "sent"}) > 0 if line_id else False

        # 如果會員資料有填，就用會員的；如果沒有（舊資料），就用原本存在回饋裡的
        doc['realName'] = user.get('realName') or doc.get('realName', '未填寫')
        doc['phone'] = user.get('phone') or doc.get('phone', '未填寫')
        doc['address'] = user.get('address') or doc.get('address', '未填寫')
        doc['email'] = user.get('email') or doc.get('email', '')
        
        # 👇 新增這行：把農曆生日抓出來
        doc['lunarBirthday'] = user.get('lunarBirthday') or '未提供'
        
        doc['has_received'] = has_received

        doc['_id'] = str(doc['_id'])
        if 'createdAt' in doc: doc['createdAt'] = doc['createdAt'].strftime('%Y-%m-%d %H:%M:%S')
        if 'approvedAt' in doc: doc['approvedAt'] = doc['approvedAt'].strftime('%Y-%m-%d %H:%M')
        if 'sentAt' in doc: doc['sentAt'] = doc['sentAt'].strftime('%Y-%m-%d %H:%M')
        results.append(doc)
    return results
@app.route('/api/feedback', methods=['POST'])
def add_feedback():
    if db is None: return jsonify({"error": "DB Error"}), 500
    line_id = session.get('user_line_id')
    if not line_id: return jsonify({"error": "請先使用 LINE 登入"}), 401
        
    data = request.get_json()
    if not data.get('agreed'): return jsonify({"error": "必須勾選同意條款"}), 400
    
    # 極簡化：只存回饋內容，個資一律去 users 資料表抓
    new_feedback = {
        "lineId": line_id,
        "nickname": data.get('nickname'),
        "category": data.get('category', []), 
        "content": data.get('content'),
        "agreed": True, 
        "createdAt": datetime.utcnow(), 
        "status": "pending", 
        "isMarked": False
    }
    db.feedback.insert_one(new_feedback)
    return jsonify({"success": True, "message": "回饋已送出"})

# 這是給 [前台] 看的，保護隱私不回傳個資
@app.route('/api/feedback/approved', methods=['GET']) 
def get_public_approved_feedback():
    cursor = db.feedback.find({"status": "approved"}).sort("approvedAt", -1)
    results = []
    for doc in cursor:
        results.append({
            '_id': str(doc['_id']),
            'feedbackId': doc.get('feedbackId', ''),
            'nickname': doc.get('nickname', '匿名'),  
            'category': doc.get('category', []),      
            'content': doc.get('content', ''),        
            'createdAt': doc['createdAt'].strftime('%Y-%m-%d') 
        })
    return jsonify(results)

# 以下是給 [後台] 管理員看的，包含合併後的完整個資與標籤
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
    if not oid: return jsonify({"error": "無效的 ID 格式"}), 400
    fb = db.feedback.find_one({'_id': oid})
    if not fb: return jsonify({"error": "No data"}), 404
    
    fb_id = f"FB{datetime.now().strftime('%Y%m%d')}{random.randint(10,99)}"
    db.feedback.update_one({'_id': oid}, {'$set': {'status': 'approved', 'feedbackId': fb_id, 'approvedAt': datetime.utcnow()}})
    
    # 抓取會員 Email 寄信
    user = db.users.find_one({"lineId": fb.get('lineId')}) if fb.get('lineId') else {}
    email = user.get('email') or fb.get('email')
    if email:
        fb_for_email = fb.copy()
        fb_for_email['realName'] = user.get('realName', '信徒')
        send_email(email, "【承天中承府】您的回饋已核准刊登", generate_feedback_email_html(fb_for_email, 'approved'), is_html=True)
    return jsonify({"success": True})

@app.route('/api/feedback/<fid>/ship', methods=['PUT'])
@login_required
def ship_feedback(fid):
    oid = get_object_id(fid)
    if not oid: return jsonify({"error": "無效的 ID 格式"}), 400
    data = request.get_json()
    tracking = data.get('trackingNumber', '')
    fb = db.feedback.find_one({'_id': oid})
    
    db.feedback.update_one({'_id': oid}, {'$set': {'status': 'sent', 'trackingNumber': tracking, 'sentAt': datetime.utcnow()}})
    
    user = db.users.find_one({"lineId": fb.get('lineId')}) if fb.get('lineId') else {}
    email = user.get('email') or fb.get('email')
    if email:
        fb_for_email = fb.copy()
        fb_for_email['realName'] = user.get('realName', '信徒')
        send_email(email, "【承天中承府】結緣品寄出通知", generate_feedback_email_html(fb_for_email, 'sent', tracking), is_html=True)
    return jsonify({"success": True})

@app.route('/api/feedback/<fid>', methods=['DELETE'])
@login_required
def delete_feedback(fid):
    oid = get_object_id(fid)
    if not oid: return jsonify({"error": "無效的 ID 格式"}), 400
    fb = db.feedback.find_one({'_id': oid})
    
    user = db.users.find_one({"lineId": fb.get('lineId')}) if fb and fb.get('lineId') else {}
    email = user.get('email') or (fb.get('email') if fb else None)
    if email:
        fb_for_email = fb.copy()
        fb_for_email['realName'] = user.get('realName', '信徒')
        send_email(email, "【承天中承府】感謝您的投稿與分享", generate_feedback_email_html(fb_for_email, 'rejected'), is_html=True)
        
    db.feedback.delete_one({'_id': oid})
    return jsonify({"success": True})

@app.route('/api/feedback/<fid>', methods=['PUT'])
@login_required
def update_feedback(fid):
    oid = get_object_id(fid)
    if not oid: return jsonify({"error": "無效的 ID 格式"}), 400
    data = request.get_json()
    db.feedback.update_one({'_id': oid}, {'$set': {'nickname': data.get('nickname'), 'category': data.get('category'), 'content': data.get('content')}})
    return jsonify({"success": True})

@app.route('/api/feedback/export-sent-txt', methods=['POST'])
@login_required
def export_sent_feedback_txt():
    cursor = db.feedback.find({"status": "sent"}).sort("sentAt", -1)
    enriched = enrich_feedback_for_admin(cursor)
    if not enriched: return jsonify({"error": "無已寄送資料"}), 404
    
    si = io.StringIO()
    si.write(f"已寄送名單匯出\n匯出時間: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
    si.write("=" * 50 + "\n")
    for doc in enriched:
        si.write(f"{doc['realName']}\t{doc['phone']}\t{doc['address']}\n")
    return Response(si.getvalue(), mimetype='text/plain', headers={"Content-Disposition": "attachment;filename=sent_feedback_list.txt"})

@app.route('/api/feedback/export-txt', methods=['POST'])
@login_required
def export_feedback_txt():
    cursor = db.feedback.find({"status": "approved"}).sort("approvedAt", 1)
    enriched = enrich_feedback_for_admin(cursor)
    if not enriched: return jsonify({"error": "無資料"}), 404
    
    si = io.StringIO()
    si.write(f"匯出時間: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n")
    for doc in enriched:
        si.write(f"【編號】{doc.get('feedbackId', '無')}\n")
        si.write(f"姓名：{doc['realName']}\n")
        si.write(f"電話：{doc['phone']}\n")
        si.write(f"地址：{doc['address']}\n")
        si.write("-" * 30 + "\n")
    return Response(si.getvalue(), mimetype='text/plain', headers={"Content-Disposition": "attachment;filename=feedback_list.txt"})

@app.route('/api/settings/bank', methods=['GET', 'POST'])
@login_required
def handle_bank_settings():
    if request.method == 'GET':
        # 一次回傳兩組設定
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
        # 接收並儲存兩組設定
        data = request.get_json()
        
        # 儲存建廟基金 (Fund) - 維持原本的 key
        if 'fund' in data:
            db.settings.update_one(
                {"type": "bank_info"},
                {"$set": data['fund']},
                upsert=True
            )
            
        # 儲存一般/捐香 (Shop) - 使用新的 key
        if 'shop' in data:
            db.settings.update_one(
                {"type": "bank_info_shop"},
                {"$set": data['shop']},
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
    
    # 1. 取得前端傳來的 type 參數
    # 如果前端沒傳 (像 donation.html)，就預設用 'donation'
    target_type = request.args.get('type', 'donation')
    
    # 2. 建立查詢條件 (只抓已付款)
    query = {"status": "paid"}
    
    # 判斷要抓哪種類型
    if target_type == 'all':
        query["orderType"] = {"$in": ["donation", "fund"]}
    else:
        query["orderType"] = target_type
        
    # 3. 執行查詢 (依更新時間排序，取前 30 筆)
    cursor = db.orders.find(query).sort("updatedAt", -1).limit(30)
    
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
    type_filter = request.args.get('type') # 'donation' 或 'fund'
    status_filter = request.args.get('status') # 'paid', 'pending'
    report_filter = request.args.get('reported') # '0' (未稟告), '1' (已稟告)
    
    query = {}
    if type_filter: query['orderType'] = type_filter
    else: query['orderType'] = {"$in": ["donation", "fund"]} # 預設抓這兩種
    
    if status_filter: query['status'] = status_filter
    
    # 稟告篩選 (只針對捐香有效)
    if type_filter == 'donation' and report_filter is not None:
        query['is_reported'] = (report_filter == '1')

    # 日期篩選 (選填)
    start_str = request.args.get('start')
    end_str = request.args.get('end')
    if start_str and end_str:
        try:
            start_date = datetime.strptime(start_str, '%Y-%m-%d')
            end_date = datetime.strptime(end_str, '%Y-%m-%d') + timedelta(days=1)
            query["createdAt"] = {"$gte": start_date, "$lt": end_date}
        except: pass

    cursor = db.orders.find(query).sort([("is_reported", 1), ("createdAt", -1)])
    results = []
    for doc in cursor:
        doc['_id'] = str(doc['_id'])
        doc['createdAt'] = (doc['createdAt'] + timedelta(hours=8)).strftime('%Y-%m-%d %H:%M')
        # 顯示稟告時間
        if doc.get('reportedAt'):
            doc['reportedAt'] = (doc['reportedAt'] + timedelta(hours=8)).strftime('%Y-%m-%d')
        results.append(doc)
    return jsonify(results)

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
    line_id = session.get('user_line_id')
    if not line_id: return jsonify({"error": "請先使用 LINE 登入"}), 401
    
    order_type = data.get('orderType', 'shop')
    
    prefix = "ORD"
    if order_type == 'donation': prefix = "DON"
    elif order_type == 'fund': prefix = "FND"
    
    order_id = f"{prefix}{datetime.now().strftime('%Y%m%d%H%M%S')}{random.randint(10,99)}"
    
    # 接收新欄位
    customer_info = {
        "name": data.get('name'), 
        "phone": data.get('phone'), 
        "email": data.get('email', ''),
        "address": data.get('address'), 
        "last5": data.get('last5'),
        "lunarBirthday": data.get('lunarBirthday', ''),
        # 新增配送資訊
        "shippingMethod": data.get('shippingMethod', 'home'), # home 或 711
        "storeInfo": data.get('storeInfo', ''),               # 7-11 門市資訊
        "shippingFee": data.get('shippingFee', 120)           # 記錄當時的運費
    }
    
    now = datetime.utcnow()
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
    if order_type == 'donation': subject = f"【承天中承府】捐香登記確認 ({order_id})"
    elif order_type == 'fund': subject = f"【承天中承府】建廟護持確認 ({order_id})"
    
    if order_type in ['donation', 'fund']:
        html = generate_donation_created_email(order)
    else:
        html = generate_shop_email_html(order, 'created')
        
    send_email(customer_info['email'], subject, html, is_html=True)
    return jsonify({"success": True, "orderId": order_id})
# === 3. 新增 API: 批次標記捐香為「已稟告」 ===
@app.route('/api/donations/mark-reported', methods=['POST'])
@login_required
def mark_donations_reported():
    data = request.get_json()
    ids = data.get('ids', [])
    if not ids: return jsonify({"success": False, "message": "無選取訂單"})
    
    # 轉換 ID 並更新
    object_ids = [get_object_id(i) for i in ids if get_object_id(i)]
    if object_ids:
        db.orders.update_many(
            {"_id": {"$in": object_ids}},
            {"$set": {"is_reported": True, "reportedAt": datetime.utcnow()}}
        )
    return jsonify({"success": True})
@app.route('/api/user/orders', methods=['GET'])
def get_user_orders():
    """給信徒「個人專區」看的商城訂單紀錄"""
    line_id = session.get('user_line_id')
    if not line_id or db is None:
        return jsonify([])
        
    # 只抓取商品訂單，不含建廟捐款
    cursor = db.orders.find({"lineId": line_id, "orderType": "shop"}).sort("createdAt", -1)
    results = []
    for doc in cursor:
        # 轉換為台灣時間字串
        tw_created = doc['createdAt'] + timedelta(hours=8)
        # 若是舊訂單沒有 paymentDeadline，相容處理為創建時間+2小時
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
            "deadline_iso": tw_deadline.isoformat() # 用於前端 JS 比較是否過期
        })
    return jsonify(results)
@app.route('/api/user/donations', methods=['GET'])
def get_user_donations():
    line_id = session.get('user_line_id')
    if not line_id or db is None:
        return jsonify([])
        
    cursor = db.orders.find({"lineId": line_id, "orderType": {"$in": ["donation", "fund"]}}).sort("createdAt", -1)
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
    """一般訂單 API (只抓取 shop)"""
    # 關鍵：明確指定只抓取一般商品訂單 (shop)
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
    cutoff = datetime.utcnow() - timedelta(days=14)
    result = db.orders.delete_many({"status": "shipped", "shippedAt": {"$lt": cutoff}})
    return jsonify({"success": True, "count": result.deleted_count})

@app.route('/api/orders/<oid>/confirm', methods=['PUT'])
@login_required
def confirm_order_payment(oid):
    # [資安修正] 使用 get_object_id 檢查格式
    oid_obj = get_object_id(oid)
    if not oid_obj: return jsonify({"error": "無效的 ID 格式"}), 400

    order = db.orders.find_one({'_id': oid_obj})
    if not order: return jsonify({"error": "No order"}), 404
    now = datetime.utcnow()
    db.orders.update_one({'_id': oid_obj}, {'$set': {'status': 'paid', 'updatedAt': now, 'paidAt': now}})
    cust = order['customer']
    if order.get('orderType') in ['donation', 'fund']:
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
    # [資安修正] 使用 get_object_id 檢查格式
    oid_obj = get_object_id(oid)
    if not oid_obj: return jsonify({"error": "無效的 ID 格式"}), 400

    data = request.get_json()
    new_email = data.get('email')
    order = db.orders.find_one({'_id': oid_obj})
    if not order: return jsonify({"error": "No order"}), 404
    cust = order['customer']
    target_email = cust.get('email')
    if new_email and new_email != target_email:
        db.orders.update_one({'_id': oid_obj}, {'$set': {'customer.email': new_email}})
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
    oid_obj = get_object_id(oid)
    if not oid_obj: return jsonify({"error": "無效的 ID 格式"}), 400

    order = db.orders.find_one({'_id': oid_obj})
    if order and order.get('customer', {}).get('email'):
        subject = f"【承天中承府】訂單/登記已取消 ({order['orderId']})"
        body = f"親愛的 {order['customer']['name']} 您好：\n您的訂單/登記 ({order['orderId']}) 已被取消。如為誤操作或有任何疑問，請聯繫官方 LINE。"
        send_email(order['customer']['email'], subject, body)
    db.orders.delete_one({'_id': oid_obj})
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
        "name": data.get('name'), "category": data.get('category', '其他'),
        "series": data.get('series', ''),"seriesSort": int(data.get('seriesSort', 0)),"price": int(data.get('price', 0)),"description": data.get('description', ''), "image": data.get('image', ''), "isActive": data.get('isActive', True),
        "isDonation": data.get('isDonation', False), "variants": data.get('variants', []), "createdAt": datetime.utcnow()
    }
    db.products.insert_one(new_product)
    return jsonify({"success": True})

@app.route('/api/products/<pid>', methods=['PUT'])
@login_required
def update_product(pid):
    oid = get_object_id(pid)
    if not oid: return jsonify({"error": "無效的 ID 格式"}), 400

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
    if not oid: return jsonify({"error": "無效的 ID 格式"}), 400

    db.products.delete_one({'_id': oid})
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
    oid = get_object_id(aid)
    if not oid: return jsonify({"error": "無效的 ID 格式"}), 400

    data = request.get_json()
    db.announcements.update_one({'_id': oid}, {'$set': {
        "date": datetime.strptime(data['date'], '%Y/%m/%d'), "title": data['title'],
        "content": data['content'], "isPinned": data.get('isPinned', False)
    }})
    return jsonify({"success": True})

@app.route('/api/announcements/<aid>', methods=['DELETE'])
@login_required
def delete_announcement(aid):
    oid = get_object_id(aid)
    if not oid: return jsonify({"error": "無效的 ID 格式"}), 400

    db.announcements.delete_one({'_id': oid})
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
    oid = get_object_id(fid)
    if not oid: return jsonify({"error": "無效的 ID 格式"}), 400

    data = request.get_json()
    db.faq.update_one({'_id': oid}, {'$set': {
        "question": data['question'], "answer": data['answer'], "category": data['category'], "isPinned": data.get('isPinned', False)
    }})
    return jsonify({"success": True})

@app.route('/api/faq/<fid>', methods=['DELETE'])
@login_required
def delete_faq(fid):
    oid = get_object_id(fid)
    if not oid: return jsonify({"error": "無效的 ID 格式"}), 400

    db.faq.delete_one({'_id': oid})
    return jsonify({"success": True})

# === 1. 修改 get_fund_settings (只計算 fund 類別) ===
@app.route('/api/fund-settings', methods=['GET'])
def get_fund_settings():
    settings = db.temple_fund.find_one({"type": "main_fund"}) or {"goal_amount": 10000000}
    
    # 修改：只加總 orderType 為 'fund' 且已付款的金額
    # (若您已在資料庫手動將舊的建廟訂單改成 fund，這樣寫最乾淨)
    pipeline = [
        {"$match": {"status": "paid", "orderType": "fund"}},
        {"$group": {"_id": None, "total_current": {"$sum": "$total"}}}
    ]
    
    if db is not None:
        result = list(db.orders.aggregate(pipeline))
        calculated_current = result[0]['total_current'] if result else 0
    else:
        calculated_current = 0
        
    settings['current_amount'] = calculated_current
    if '_id' in settings: settings['_id'] = str(settings['_id'])
    return jsonify(settings)

@app.route('/api/fund-settings', methods=['POST'])
@login_required
def update_fund_settings():
    data = request.get_json()
    # 💡 現在只需更新目標金額 (goal_amount)，目前金額已完全自動化不須存進設定檔
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
    if not oid: return jsonify({"error": "無效的 ID 格式"}), 400

    data = request.get_json()
    db.links.update_one({'_id': oid}, {'$set': {'url': data['url']}})
    return jsonify({"success": True})

@app.route('/api/orders/<oid>/ship', methods=['PUT'])
@login_required
def ship_order(oid):
    oid_obj = get_object_id(oid)
    if not oid_obj: return jsonify({"error": "無效的 ID 格式"}), 400

    data = request.get_json() or {}
    tracking_num = data.get('trackingNumber', '').strip()
    order = db.orders.find_one({'_id': oid_obj})
    if not order: return jsonify({"error": "No order"}), 404
    now = datetime.utcnow()
    db.orders.update_one({'_id': oid_obj}, {'$set': {
        'status': 'shipped', 'updatedAt': now, 'shippedAt': now, 'trackingNumber': tracking_num
    }})
    cust = order['customer']
    email_subject = f"【承天中承府】訂單出貨通知 ({order['orderId']})"
    email_html = generate_shop_email_html(order, 'shipped', tracking_num)
    send_email(cust.get('email'), email_subject, email_html, is_html=True)
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