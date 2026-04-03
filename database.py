from datetime import datetime, timezone

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


def write_audit_log(admin_username, action, target='', details=''):
    """寫入操作日誌至 audit_log collection"""
    if db is None:
        return
    try:
        db.audit_log.insert_one({
            "timestamp": datetime.now(timezone.utc).replace(tzinfo=None),
            "admin": admin_username or 'system',
            "action": action,
            "target": target,
            "details": details
        })
    except Exception as e:
        print(f"[AuditLog Error] {e}")
