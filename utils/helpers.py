import re
import os
from datetime import datetime, timedelta, timezone
from bson import ObjectId
from bson.errors import InvalidId
from linebot import LineBotApi
from linebot.models import TextSendMessage

# 初始化 LINE Bot API (請確保你的環境變數有設定)
LINE_CHANNEL_ACCESS_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN')
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)

def send_line_notification(to_line_id, message_text):
    """
    發送 LINE 訊息給指定的 user_id
    """
    try:
        line_bot_api.push_message(
            to_line_id,
            TextSendMessage(text=message_text)
        )
        return True
    except Exception as e:
        print(f"LINE 推播失敗: {e}")
        return False

def get_tw_now():
    return datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=8)


def validate_real_name(name):
    if not name:
        return True, ""
    if re.search(r'[、，,。/&＆\s]', name) or re.search(r'(全家|一家|闔家|合家|等人|與|及)', name):
        return False, "姓名僅限填寫「一位」，請勿包含空格、標點符號或群體字眼。"
    return True, ""


def calculate_business_d2(start_date):
    current = start_date
    added_days = 0
    while added_days < 2:
        current += timedelta(days=1)
        if current.weekday() < 5:
            added_days += 1
    return current


def mask_name(real_name):
    if not real_name:
        return ""
    if len(real_name) >= 2:
        return real_name[0] + "O" + real_name[2:]
    return real_name


def get_object_id(fid):
    try:
        return ObjectId(fid)
    except (InvalidId, TypeError):
        return None
