# --- app.py (最終安全版) ---
import os
from functools import wraps
from flask import Flask, jsonify, render_template, request, session, redirect, url_for, Response
from flask_cors import CORS
from flask_wtf.csrf import CSRFProtect # 只需要導入 CSRFProtect
from pymongo import MongoClient
from bson import ObjectId
from datetime import datetime, timedelta
from dotenv import load_dotenv
from werkzeug.security import check_password_hash
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address


# --- 應用程式初始化與設定 ---
load_dotenv()
app = Flask(__name__)
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["2000 per day", "500 per hour"], # 全站預設限制
    storage_uri="memory://" 
)
csrf = CSRFProtect(app) 
# 1. 設定 SECRET_KEY，若 .env 未提供，則使用隨機值確保不報錯
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', os.urandom(24))
is_production = os.environ.get('RENDER') is not None

app.config['SESSION_COOKIE_SECURE'] = is_production  # True: 僅限 HTTPS, False: 允許 HTTP
app.config['SESSION_COOKIE_HTTPONLY'] = True         # 禁止 JS 讀取 Cookie (防 XSS)
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'        # 防範 CSRF 的另一道防線
# 3. 設定 Session 有效期為 8 小時
app.permanent_session_lifetime = timedelta(hours=8)

# 4. 限制 CORS，未來部署後應限制 origins
# 部署後請將 "origins": "*" 改為 "origins": "https://您的網域名稱"
CORS(app, resources={r"/api/*": {"origins": "*"}}, supports_credentials=True)

# 5. 從 .env 讀取加密後的密碼
ADMIN_PASSWORD_HASH = os.environ.get('ADMIN_PASSWORD_HASH')


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
        return dict(links={})
    links_from_db = db.links.find({})
    links_dict = {link['name']: link['url'] for link in links_from_db}
    return dict(links=links_dict)


# --- 前台頁面路由 (維持不變) ---
@app.route('/')
def home(): return render_template('index.html')
@app.route('/gongtan')
def gongtan_page(): return render_template('gongtan.html')
@app.route('/shoujing')
def shoujing_page(): return render_template('shoujing.html')
@app.route('/incense')
def incense_page(): return render_template('incense.html')
@app.route('/feedback')
def feedback_page(): return render_template('feedback.html')
@app.route('/faq')
def faq_page(): return render_template('faq.html')


# --- 後台頁面路由 (維持不變) ---
@app.route('/admin')
def admin_page(): return render_template('admin.html')


# --- 後台與 API 路由 ---
@app.route('/api/session_check', methods=['GET'])
def session_check():
    if 'logged_in' in session:
        return jsonify({"logged_in": True})
    return jsonify({"logged_in": False})

# 【關鍵修改】豁免 /api/login 的 CSRF 檢查，因為使用者此時還沒有 token
@csrf.exempt
@app.route('/api/login', methods=['POST'])
@limiter.limit("5 per minute")
def api_login():
    password = request.json.get('password')
    if ADMIN_PASSWORD_HASH and check_password_hash(ADMIN_PASSWORD_HASH, password):
        session['logged_in'] = True
        session.permanent = True
        return jsonify({"success": True, "message": "登入成功！"})
    return jsonify({"success": False, "message": "密碼錯誤"}), 401

@app.route('/api/logout', methods=['POST'])
def api_logout():
    session.pop('logged_in', None)
    return jsonify({"success": True, "message": "已成功登出"})
# API: 接收前端新的回饋
@app.route('/api/feedback', methods=['POST'])
# --- app.py (找到 add_feedback 函式進行修改) ---

@app.route('/api/feedback', methods=['POST'])
def add_feedback():
    if db is None: return jsonify({"error": "資料庫未連線"}), 500
    
    data = request.get_json()
    
    # 移除 'agreed' 的必填檢查，因為現在是在第二階段才勾選，前端會負責擋
    required_fields = ['realName', 'nickname', 'category', 'content']
    if not all(field in data and data[field] for field in required_fields):
        return jsonify({"error": "必填欄位不完整"}), 400
    
    # 雖然前端有檢查，後端還是保險起見檢查一下 agree
    if not data.get('agreed'):
        return jsonify({"error": "必須勾選同意條款"}), 400

    # 處理時辰預設值 (Fix 3)
    birth_time = data.get('birthTime')
    if not birth_time:
        birth_time = '吉時 (不知道)'

    new_feedback = {
        "realName": data.get('realName'),
        "nickname": data.get('nickname'),
        "category": data.get('category', []),
        "content": data.get('content'),
        "lunarBirthday": data.get('lunarBirthday', ''), 
        "birthTime": birth_time, # 使用處理過的變數
        "address": data.get('address', ''),
        "phone": data.get('phone', ''),
        "agreed": True,
        "createdAt": datetime.utcnow(),
        "status": "pending",
        "isMarked": False
    }
    
    db.feedback.insert_one(new_feedback)
    return jsonify({"success": True, "message": "您的回饋已成功送出，待管理者審核後將會刊登。"})
# API: 獲取所有待審核的回饋
@app.route('/api/feedback/pending', methods=['GET'])
@login_required
def get_pending_feedback():
    if db is None: return jsonify({"error": "資料庫未連線"}), 500
    
    try:
        # 查詢 status 為 'pending' 的所有文件，並依照建立時間倒序排列 (新的在最上面)
        pending_list_cursor = db.feedback.find({"status": "pending"}).sort("createdAt", 1)
        
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
# --- app.py 新增功能 ---

# --- 請將此區段插入 app.py (放在 approve_feedback 函式附近) ---

# API: 更新回饋內容 (編輯功能)
@app.route('/api/feedback/<feedback_id>', methods=['PUT'])
@login_required
def update_feedback(feedback_id):
    if db is None: return jsonify({"error": "資料庫未連線"}), 500
    
    data = request.get_json()
    try:
        # 準備更新的欄位
        update_fields = {
            "realName": data.get('realName'),
            "nickname": data.get('nickname'),
            "category": data.get('category'), 
            "content": data.get('content'),
            "lunarBirthday": data.get('lunarBirthday'),
            "birthTime": data.get('birthTime'),
            "address": data.get('address'),
            "phone": data.get('phone')
        }
        
        result = db.feedback.update_one(
            {'_id': ObjectId(feedback_id)},
            {'$set': update_fields}
        )
        
        if result.matched_count == 0:
            return jsonify({"error": "找不到指定的回饋"}), 404
            
        return jsonify({"success": True, "message": "資料更新成功"})
    except Exception as e:
        return jsonify({"error": f"更新失敗: {str(e)}"}), 500
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
@app.route('/api/feedback/download-unmarked', methods=['POST'])
@login_required
def download_unmarked_feedback():
    if db is None: return jsonify({"error": "資料庫未連線"}), 500
    try:
        # 1. 找出所有 Status='approved' 且 isMarked=False 的文件
        cursor = db.feedback.find(
            {"status": "approved", "isMarked": False}
        ).sort("address", 1)
        
        feedback_list = list(cursor)
        
        if not feedback_list:
            return jsonify({"error": "目前沒有新的未寄送資料"}), 404

        # 2. 組合匯出內容 (純文字檔)
        export_text = f"匯出時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        export_text += f"總筆數: {len(feedback_list)}\n"
        export_text += "="*30 + "\n\n"

        ids_to_update = []
        count = 1
        
        for doc in feedback_list:
            ids_to_update.append(doc['_id'])
            
            export_text += f"【第 {count} 筆】\n"
            export_text += f"姓名: {doc.get('realName')}\n"
            export_text += f"電話: {doc.get('phone')}\n"
            export_text += f"地址: {doc.get('address')}\n"
            # 這裡將生日與時辰加入匯出檔案
            export_text += f"農曆生日: {doc.get('lunarBirthday', '無')}\n"
            export_text += f"時辰: {doc.get('birthTime', '無')}\n"
            export_text += f"內容摘要: {doc.get('content')[:30]}...\n"
            export_text += "-"*20 + "\n\n"
            count += 1

        # 3. 自動將這些資料標記為已讀 (isMarked = True)
        db.feedback.update_many(
            {'_id': {'$in': ids_to_update}},
            {'$set': {'isMarked': True}}
        )

        # 4. 回傳檔案供瀏覽器下載
        return Response(
            export_text,
            mimetype='text/plain',
            headers={
                "Content-Disposition": f"attachment;filename=shipping_list_{datetime.now().strftime('%Y%m%d')}.txt"
            }
        )

    except Exception as e:
        return jsonify({"error": f"匯出失敗: {str(e)}"}), 500
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
# --- 請複製這段程式碼，完整替換 app.py 中的 get_announcements 函式 ---
# --- 請用這段完整替換 app.py 中的 get_announcements 函式 ---
@app.route('/api/announcements', methods=['GET'])
def get_announcements():
    if db is None: return jsonify({"error": "資料庫未連線或連線失敗"}), 500
    try:
        # 修改重點：
        # 1. ("isPinned", -1) -> 置頂的排最上面
        # 2. ("_id", -1)      -> 這代表「依照建立時間由新到舊」，保證最新發布的在上面
        announcements_cursor = db.announcements.find().sort([
            ("isPinned", -1), 
            ("_id", -1)
        ])
        
        results = []
        for doc in announcements_cursor:
            doc['_id'] = str(doc['_id'])
            # 如果有 date 欄位且是 datetime 物件，轉成字串
            if 'date' in doc and isinstance(doc['date'], datetime):
                doc['date'] = doc['date'].strftime('%Y/%m/%d')
            results.append(doc)
            
        return jsonify(results)
    except Exception as e:
        print(f"Error fetching announcements: {e}") # 在後台印出錯誤以便除錯
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
@app.route('/api/faq', methods=['POST'])
@login_required
def add_faq():
    if db is None:
        return jsonify({"error": "資料庫未連線"}), 500

    data = request.get_json()
    # 檢查必填欄位
    required_fields = ['question', 'answer', 'category']
    if not all(field in data and data[field].strip() for field in required_fields):
        return jsonify({"error": "請填寫完整資訊"}), 400

    # 只能有中文字（正則表達式，前端也要做）
    import re
    if not re.match(r'^[\u4e00-\u9fff]+$', data['category']):
        return jsonify({"error": "分類只能是中文"}), 400

    new_faq = {
        "question": data['question'].strip(),
        "answer": data['answer'].strip(),
        "category": data['category'].strip(),
        "isPinned": bool(data.get('isPinned', False)),
        "createdAt": datetime.utcnow(),
    }
    db.faq.insert_one(new_faq)
    return jsonify({"success": True})
@app.route('/api/faq', methods=['GET'])
def get_faqs():
    if db is None:
        return jsonify({"error": "資料庫未連線"}), 500
    # 可選參數：分類過濾
    category = request.args.get('category')
    query = {}
    if category:
        query['category'] = category

    # 先依 isPinned 降冪，再依建立時間降冪
    faqs = db.faq.find(query).sort([('isPinned', -1), ('createdAt', -1)])
    result = []
    for faq in faqs:
        faq['_id'] = str(faq['_id'])
        faq['createdAt'] = faq['createdAt'].strftime('%Y-%m-%d %H:%M:%S')
        result.append(faq)
    return jsonify(result)
@app.route('/api/faq/categories', methods=['GET'])
def get_faq_categories():
    if db is None:
        return jsonify({"error": "資料庫未連線"}), 500
    categories = db.faq.distinct('category')
    return jsonify(categories)
@app.route('/api/faq/<faq_id>', methods=['DELETE'])
@login_required
def delete_faq(faq_id):
    if db is None:
        return jsonify({"error": "資料庫未連線"}), 500
    result = db.faq.delete_one({'_id': ObjectId(faq_id)})
    if result.deleted_count == 0:
        return jsonify({"error": "找不到此問答"}), 404
    return jsonify({"success": True})

# --- 公告管理 API (Admin) ---

@app.route('/api/announcements', methods=['POST'])
@login_required
def add_announcement():
    if db is None: return jsonify({"error": "資料庫未連線"}), 500
    data = request.get_json()
    
    # 欄位驗證
    if not all(k in data for k in ['date', 'title', 'content']):
        return jsonify({"error": "缺少必要欄位"}), 400
    
    try:
        # 將前端傳來的 YYYY/MM/DD 字串轉換為 datetime 物件
        date_obj = datetime.strptime(data['date'], '%Y/%m/%d')
    except ValueError:
        return jsonify({"error": "日期格式錯誤，應為 YYYY/MM/DD"}), 400

    new_announcement = {
        "date": date_obj,
        "title": data['title'],
        "content": data['content'],
        "isPinned": data.get('isPinned', False),
        "createdAt": datetime.utcnow()
    }
    db.announcements.insert_one(new_announcement)
    return jsonify({"success": True, "message": "公告新增成功"}), 201

@app.route('/api/announcements/<announcement_id>', methods=['DELETE'])
@login_required
def delete_announcement(announcement_id):
    if db is None: return jsonify({"error": "資料庫未連線"}), 500
    
    result = db.announcements.delete_one({'_id': ObjectId(announcement_id)})
    
    if result.deleted_count == 0:
        return jsonify({"error": "找不到指定公告或已被刪除"}), 404
        
    return jsonify({"success": True, "message": "公告刪除成功"})
# --- (請將這段程式碼貼在 app.py 的最下方，if __name__ == '__main__': 之前) ---

# --- 商品管理 API ---
@app.route('/api/products', methods=['GET'])
@login_required
def get_products():
    if db is None: return jsonify({"error": "資料庫未連線"}), 500
    try:
        # 依類別排序，再依建立時間由新到舊排序
        products = list(db.products.find().sort([("category", 1), ("createdAt", -1)]))
        for p in products:
            p['_id'] = str(p['_id'])
        return jsonify(products)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/products', methods=['POST'])
@login_required
def add_product():
    if db is None: return jsonify({"error": "資料庫未連線"}), 500
    data = request.get_json()
    try:
        # 驗證必填欄位
        if not data.get('name') or not data.get('price'):
            return jsonify({"error": "商品名稱與價格為必填"}), 400

        new_product = {
            "name": data.get('name'),
            "category": data.get('category', '其他'), # 分類：手工香, 建廟基金, 保養品...
            "price": int(data.get('price', 0)),
            "description": data.get('description', ''),
            "image": data.get('image', ''),  # ★ 新增這一行：儲存圖片 Base64
            "isActive": data.get('isActive', True), # 預設上架
            "createdAt": datetime.utcnow()
        }
        db.products.insert_one(new_product)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/products/<product_id>', methods=['PUT'])
@login_required
def update_product(product_id):
    if db is None: return jsonify({"error": "資料庫未連線"}), 500
    data = request.get_json()
    try:
        update_fields = {
            "name": data.get('name'),
            "category": data.get('category'),
            "price": int(data.get('price', 0)),
            "description": data.get('description', ''),
            "image": data.get('image'), # ★ 新增這一行：更新圖片
            "isActive": data.get('isActive', True)
        }
        db.products.update_one({'_id': ObjectId(product_id)}, {'$set': update_fields})
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/products/<product_id>', methods=['DELETE'])
@login_required
def delete_product(product_id):
    if db is None: return jsonify({"error": "資料庫未連線"}), 500
    try:
        db.products.delete_one({'_id': ObjectId(product_id)})
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# --- 建廟基金設定 API ---
@app.route('/api/fund-settings', methods=['GET'])
def get_fund_settings():
    if db is None: return jsonify({"error": "資料庫未連線"}), 500
    try:
        # 查詢是否有設定檔，沒有則回傳預設值
        settings = db.temple_fund.find_one({"type": "main_fund"})
        if not settings:
            return jsonify({"goal_amount": 10000000, "current_amount": 0})
        
        settings['_id'] = str(settings['_id'])
        return jsonify(settings)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/fund-settings', methods=['POST'])
@login_required
def update_fund_settings():
    if db is None: return jsonify({"error": "資料庫未連線"}), 500
    data = request.get_json()
    try:
        # 使用 upsert 功能：如果有就更新，沒有就新增
        db.temple_fund.update_one(
            {"type": "main_fund"},
            {"$set": {
                "goal_amount": int(data.get('goal_amount', 0)),
                "current_amount": int(data.get('current_amount', 0)),
                "updatedAt": datetime.utcnow()
            }},
            upsert=True
        )
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# --- 啟動伺服器 
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)