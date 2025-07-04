# --- 1. 引入所有必要的函式庫 ---
from flask import Flask, jsonify, request
from flask_cors import CORS
from pymongo import MongoClient
from bson import json_util, ObjectId
import json
from datetime import datetime
import traceback # 引入追蹤錯誤的強力工具

# --- 2. 建立 Flask 應用程式 ---
app = Flask(__name__)
CORS(app)

# --- 3. 設定資料庫連線 ---
MONGO_URI = "mongodb+srv://yuanshuaiadmin:yuanshuaiadmin260@news.irew4nn.mongodb.net/?retryWrites=true&w=majority&appName=news"

try:
    client = MongoClient(MONGO_URI)
    db = client['ChentienTempleDB'] 
    print("--- MongoDB 連線成功 ---")
except Exception as e:
    print(f"--- MongoDB 連線失敗: {e} ---")
    db = None

# --- 4. 撰寫 API 端點 ---
@app.route('/')
def index():
    return "<h1>承天中承府 後端 API 已啟動</h1>"

# 【功能一】獲取所有公告 (植入偵錯儀的最終版本)
@app.route('/api/announcements', methods=['GET'])
def get_announcements():
    print("\n--- 收到獲取公告請求 ---")
    if db is None:
        print("錯誤：資料庫未連線")
        return jsonify({"error": "資料庫連線失敗"}), 500
        
    try:
        print("步驟1: 準備查詢資料庫...")
        announcements_cursor = db.announcements.find().sort([("isPinned", -1), ("date", -1)])
        print("步驟2: 成功從資料庫查詢到資料，準備遍歷...")
        
        results = []
        for i, doc in enumerate(announcements_cursor):
            print(f"  正在處理第 {i+1} 筆資料, ID: {doc.get('_id')}")
            
            # 將 ObjectId 轉成字串
            doc['_id'] = str(doc['_id'])
            
            # 檢查日期欄位
            if 'date' in doc and isinstance(doc['date'], datetime):
                print(f"    偵測到日期為 datetime 物件，進行格式化...")
                doc['date'] = doc['date'].strftime('%Y/%m/%d')
            else:
                print(f"    日期為文字或不存在，直接使用原值: {doc.get('date')}")

            results.append(doc)
            
        print("步驟3: 所有資料處理完畢，準備回傳。")
        return jsonify(results)

    except Exception as e:
        print(f"\n!!!!!!!! 發生嚴重錯誤 !!!!!!!!")
        print(f"錯誤類型: {type(e).__name__}, 錯誤訊息: {str(e)}")
        # 打印完整的錯誤堆疊，這是最強的除錯線索
        traceback.print_exc()
        return jsonify({"error": f"在處理公告時發生嚴重錯誤: {str(e)}"}), 500

# ... 其他 API 端點維持不變 ...

# --- 5. 啟動伺服器 ---
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)