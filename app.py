import os
from functools import wraps
from flask import Flask, jsonify, render_template, request, session, redirect, url_for, flash
from flask_cors import CORS
from pymongo import MongoClient
from bson import ObjectId
from datetime import datetime
from dotenv import load_dotenv

# --- 應用程式初始化與設定 ---
load_dotenv()
app = Flask(__name__)
CORS(app)

# 從 .env 讀取密鑰與密碼
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY')
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD') # <--- 錯誤發生就是因為缺少了這一行

# --- 資料庫連線 ---
MONGO_URI = os.environ.get('MONGO_URI')
db = None
try:
    if MONGO_URI:
        client = MongoClient(MONGO_URI)
        db = client['ChentienTempleDB']
        print("--- MongoDB 連線成功 ---")
    else:
        print("--- 警告：未找到 MONGO_URI，資料庫無法連線 ---")
except Exception as e:
    print(f"--- MongoDB 連線失敗: {e} ---")


# --- 裝飾器 (Decorator) ---
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
    if db is None:
        return dict(links={}) # 資料庫未連線時回傳空字典
    
    links_from_db = db.links.find({})
    # 將資料轉換成 "名稱: 網址" 的字典格式，方便模板取用
    links_dict = {link['name']: link['url'] for link in links_from_db}
    
    return dict(links=links_dict)


# --- 前台頁面路由 ---
@app.route('/')
def home():
    return render_template('index.html')

@app.route('/gongtan')
def gongtan_page():
    return render_template('gongtan.html')

@app.route('/shoujing')
def shoujing_page():
    return render_template('shoujing.html')

@app.route('/incense')
def incense_page():
    return render_template('incense.html')

@app.route('/feedback')
def feedback_page():
    return render_template('feedback.html')

@app.route('/faq')
def faq_page():
    return render_template('faq.html')


# --- 後台頁面路由 ---
@app.route('/admin')
def admin_page():
    return render_template('admin.html')


# --- 後台與 API 路由 ---
@app.route('/api/session_check', methods=['GET'])
def session_check():
    if 'logged_in' in session:
        return jsonify({"logged_in": True})
    return jsonify({"logged_in": False})

@app.route('/api/login', methods=['POST'])
def api_login():
    password = request.json.get('password')
    if password == ADMIN_PASSWORD:
        session['logged_in'] = True
        return jsonify({"success": True, "message": "登入成功！"})
    return jsonify({"success": False, "message": "密碼錯誤"}), 401

@app.route('/api/logout', methods=['POST'])
def api_logout():
    session.pop('logged_in', None)
    return jsonify({"success": True, "message": "已成功登出"})

@app.route('/api/announcements', methods=['GET'])
def get_announcements():
    if db is None: return jsonify({"error": "資料庫未連線或連線失敗"}), 500
    try:
        announcements_cursor = db.announcements.find().sort([("isPinned", -1), ("date", -1)])
        results = []
        for doc in announcements_cursor:
            doc['_id'] = str(doc['_id'])
            if 'date' in doc and isinstance(doc['date'], datetime):
                doc['date'] = doc['date'].strftime('%Y/%m/%d')
            results.append(doc)
        return jsonify(results)
    except Exception as e:
        return jsonify({"error": f"在處理公告時發生嚴重錯誤: {str(e)}"}), 500

@app.route('/api/links', methods=['GET'])
@login_required
def get_links():
    if db is None: return jsonify({"error": "資料庫未連線"}), 500
    links_cursor = db.links.find({})
    links_list = []
    for link in links_cursor:
        link['_id'] = str(link['_id'])
        links_list.append(link)
    return jsonify(links_list)

@app.route('/api/links/<link_id>', methods=['PUT'])
@login_required
def update_link(link_id):
    if db is None: return jsonify({"error": "資料庫未連線"}), 500
    data = request.get_json()
    if not data or 'url' not in data:
        return jsonify({"error": "缺少 url 欄位"}), 400
    result = db.links.update_one(
        {'_id': ObjectId(link_id)},
        {'$set': {'url': data['url']}}
    )
    if result.matched_count == 0:
        return jsonify({"error": "找不到指定的連結"}), 404
    return jsonify({"success": True}), 200


# --- 啟動伺服器 
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)