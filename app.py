# app.py (天地人三界通用 - 最終版)

import os
from flask import Flask, jsonify, render_template
from flask_cors import CORS
from pymongo import MongoClient
from bson import json_util, ObjectId
import json
from datetime import datetime
import traceback
from dotenv import load_dotenv # <--- 引入 dotenv 工具

load_dotenv() # <--- 在程式最上方執行，它會自動讀取 .env 檔案

app = Flask(__name__)
CORS(app)

# 這行程式碼現在會：
# 1. 在本地電腦上，因為 load_dotenv()，成功讀到 .env 裡的 MONGO_URI
# 2. 在 Render 上，因為 Render 系統的環境變數，也成功讀到 MONGO_URI
MONGO_URI = os.environ.get('MONGO_URI')

db = None # 先宣告 db
try:
    if MONGO_URI:
        client = MongoClient(MONGO_URI)
        db = client['ChentienTempleDB'] 
        print("--- MongoDB 連線成功 ---")
    else:
        print("--- 警告：未找到 MONGO_URI，資料庫無法連線 ---")
except Exception as e:
    print(f"--- MongoDB 連線失敗: {e} ---")

# ... (所有 @app.route 的內容維持不變) ...

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/api/announcements', methods=['GET'])
def get_announcements():
    if db is None:
        return jsonify({"error": "資料庫未連線或連線失敗"}), 500
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

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)