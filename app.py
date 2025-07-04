# app.py (整合前端的最終版本)

from flask import Flask, jsonify, render_template # <--- 引入 render_template
from flask_cors import CORS
from pymongo import MongoClient
from bson import json_util, ObjectId
import json
from datetime import datetime
import traceback
import os

app = Flask(__name__)
CORS(app)

MONGO_URI = os.environ.get('MONGO_URI')

try:
    client = MongoClient(MONGO_URI)
    db = client['ChentienTempleDB'] 
    print("--- MongoDB 連線成功 ---")
except Exception as e:
    print(f"--- MongoDB 連線失敗: {e} ---")
    db = None

# 【修改這裡】讓根目錄 '/' 回傳 index.html
@app.route('/')
def home():
    # 這會去 templates 資料夾裡尋找並回傳 index.html
    return render_template('index.html')

# ... (其他的 API 路由，例如 /api/announcements 維持不變) ...

# 【功能一】獲取所有公告 (維持不變)
@app.route('/api/announcements', methods=['GET'])
def get_announcements():
    # ... (此處程式碼不變)
    if db is None:
        return jsonify({"error": "資料庫連線失敗"}), 500
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

# ... (其他 API 路由也維持不變)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)