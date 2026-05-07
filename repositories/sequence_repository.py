from pymongo import ReturnDocument

import database
from utils.errors import ServiceUnavailableError
from utils.timezone import utc_now


def _require_db():
    if database.db is None:
        raise ServiceUnavailableError("Database is not available")
    return database.db


def next_counter_value(counter_key, metadata=None):
    """以 MongoDB 單筆文件原子遞增，提供跨程序安全的流水號。"""
    db = _require_db()
    now = utc_now()
    set_on_insert = {
        "createdAt": now,
        **(metadata or {}),
    }
    doc = db.counters.find_one_and_update(
        {"_id": counter_key},
        {
            "$inc": {"seq": 1},
            "$set": {"updatedAt": now},
            "$setOnInsert": set_on_insert,
        },
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    return int(doc.get("seq", 0))
