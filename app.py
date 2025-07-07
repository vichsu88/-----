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
# app.py (在 "後台與 API 路由" 區塊新增)

# API: 接收前端新的回饋
@app.route('/api/feedback', methods=['POST'])
def add_feedback():
    if db is None: return jsonify({"error": "資料庫未連線"}), 500
    
    data = request.get_json()
    
    # 後端的基本驗證，確保必填欄位存在且同意條款
    required_fields = ['realName', 'nickname', 'category', 'content', 'agreed']
    if not all(field in data and data[field] for field in required_fields):
        return jsonify({"error": "必填欄位不完整或未勾選同意"}), 400
    
    if not data['agreed']:
        return jsonify({"error": "必須勾選同意條款"}), 400

    # 準備要存入資料庫的完整資料
    new_feedback = {
        "realName": data.get('realName'),
        "nickname": data.get('nickname'),
        "category": data.get('category', []),
        "content": data.get('content'),
        "address": data.get('address', ''), # 非必填欄位，如果沒有就存空字串
        "phone": data.get('phone', ''),   # 非必填欄位，如果沒有就存空字串
        "agreed": True,
        "createdAt": datetime.utcnow(), # 使用世界標準時間，避免時區問題
        "status": "pending", # 新留言預設都是「待審核」
        "isMarked": False    # 新留言預設都是「未標記」
    }
    
    # 將資料插入 feedback 集合
    db.feedback.insert_one(new_feedback)
    
    # 回傳成功訊息給前端
    return jsonify({"success": True, "message": "您的回饋已成功送出，待管理者審核後將會刊登。"})
# app.py (在 add_feedback 函式下方新增)

# API: 獲取所有待審核的回饋
@app.route('/api/feedback/pending', methods=['GET'])
@login_required
def get_pending_feedback():
    if db is None: return jsonify({"error": "資料庫未連線"}), 500
    
    try:
        # 查詢 status 為 'pending' 的所有文件，並依照建立時間倒序排列 (新的在最上面)
        pending_list_cursor = db.feedback.find({"status": "pending"}).sort("createdAt", -1)
        
        results = []
        for doc in pending_list_cursor:
            # 將 ObjectId 和 datetime 物件轉換為字串，才能序列化成 JSON
            doc['_id'] = str(doc['_id'])
            doc['createdAt'] = doc['createdAt'].strftime('%Y-%m-%d %H:%M:%S')
            results.append(doc)
            
        return jsonify(results)
    except Exception as e:
        return jsonify({"error": f"讀取待審核資料時發生錯誤: {str(e)}"}), 500

# app.py (在 get_pending_feedback 函式下方新增)

# API: 同意刊登 (將 status 改為 'approved')
@app.route('/api/feedback/<feedback_id>/approve', methods=['PUT'])
@login_required
def approve_feedback(feedback_id):
    if db is None: return jsonify({"error": "資料庫未連線"}), 500
    try:
        # 根據 ID 找到文件，並只更新 status 欄位
        result = db.feedback.update_one(
            {'_id': ObjectId(feedback_id)},
            {'$set': {'status': 'approved'}}
        )
        if result.matched_count == 0:
            return jsonify({"error": "找不到指定的回饋"}), 404
            
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": f"審核時發生錯誤: {str(e)}"}), 500

# API: 不同意刪除 (從資料庫中刪除)
@app.route('/api/feedback/<feedback_id>', methods=['DELETE'])
@login_required
def delete_feedback(feedback_id):
    if db is None: return jsonify({"error": "資料庫未連線"}), 500
    try:
        # 根據 ID 直接從資料庫中刪除該文件
        result = db.feedback.delete_one({'_id': ObjectId(feedback_id)})
        
        if result.deleted_count == 0:
            return jsonify({"error": "找不到指定的回饋或已被刪除"}), 404
            
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": f"刪除時發生錯誤: {str(e)}"}), 500
# app.py (在 delete_feedback 函式下方新增)

# API: 獲取所有已審核的回饋
@app.route('/api/feedback/approved', methods=['GET'])
@login_required
def get_approved_feedback():
    if db is None: return jsonify({"error": "資料庫未連線"}), 500
    try:
        approved_list_cursor = db.feedback.find({"status": "approved"}).sort("createdAt", -1)
        results = []
        for doc in approved_list_cursor:
            doc['_id'] = str(doc['_id'])
            doc['createdAt'] = doc['createdAt'].strftime('%Y-%m-%d %H:%M:%S')
            results.append(doc)
        return jsonify(results)
    except Exception as e:
        return jsonify({"error": f"讀取已審核資料時發生錯誤: {str(e)}"}), 500

# API: 標記/取消標記單筆回饋
@app.route('/api/feedback/<feedback_id>/mark', methods=['PUT'])
@login_required
def mark_feedback(feedback_id):
    if db is None: return jsonify({"error": "資料庫未連線"}), 500
    try:
        data = request.get_json()
        is_marked = data.get('isMarked', False) # 從前端獲取要設定的狀態
        result = db.feedback.update_one(
            {'_id': ObjectId(feedback_id)},
            {'$set': {'isMarked': is_marked}}
        )
        if result.matched_count == 0:
            return jsonify({"error": "找不到指定的回饋"}), 404
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": f"標記時發生錯誤: {str(e)}"}), 500

# API: 將所有已審核的回饋標記為true
@app.route('/api/feedback/mark-all-approved', methods=['PUT'])
@login_required
def mark_all_approved_feedback():
    if db is None: return jsonify({"error": "資料庫未連線"}), 500
    try:
        # 使用 update_many 將所有 status 為 approved 的文件的 isMarked 設為 true
        result = db.feedback.update_many(
            {'status': 'approved'},
            {'$set': {'isMarked': True}}
        )
        return jsonify({"success": True, "modified_count": result.modified_count})
    except Exception as e:
        return jsonify({"error": f"全部標記時發生錯誤: {str(e)}"}), 500

# API: 輸出未標記的寄件資訊
@app.route('/api/feedback/export-unmarked', methods=['GET'])
@login_required
def export_unmarked_feedback():
    if db is None: return "資料庫未連線", 500
    try:
        # 找出所有已審核，但尚未標記的文件，並依地址排序
        unmarked_list_cursor = db.feedback.find(
            {"status": "approved", "isMarked": False}
        ).sort("address", 1)
        
        export_text = ""
        count = 1
        for doc in unmarked_list_cursor:
            # 根據您要的格式，組合成純文字
            export_text += f"{count}. {doc.get('realName')}\n"
            export_text += f"   {doc.get('phone')}\n"
            export_text += f"   {doc.get('address')}\n\n"
            count += 1
            
        if not export_text:
            export_text = "目前沒有未標記的寄件資訊。"

        # 直接回傳純文字內容
        return Response(export_text, mimetype='text/plain')
    except Exception as e:
        return f"導出時發生錯誤: {str(e)}", 500
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