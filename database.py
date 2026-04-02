from pymongo import MongoClient

db = None
_client = None


def init_db(mongo_uri):
    global db, _client
    if mongo_uri:
        try:
            _client = MongoClient(mongo_uri)
            db = _client['ChentienTempleDB']
            print("--- MongoDB 連線成功 ---")
        except Exception as e:
            print(f"--- MongoDB 連線失敗: {e} ---")
    else:
        print("--- 警告：未找到 MONGO_URI ---")
    return db
