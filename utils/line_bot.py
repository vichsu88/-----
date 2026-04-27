import os
import logging
from linebot import LineBotApi
from linebot.models import TextSendMessage
from linebot.exceptions import LineBotApiError

# 從環境變數讀取 Access Token
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
logger = logging.getLogger(__name__)


def _get_line_bot_api():
    """延遲建立 LineBotApi；若未設定 token 則回傳 None，避免 import 階段整個 app 崩潰。"""
    if not LINE_CHANNEL_ACCESS_TOKEN:
        return None
    return LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)


def send_admin_notification(message_text):
    """
    發送通知給系統管理員
    """
    admin_user_id = "Ua153013c2048f6bfb12937f93a672709"

    api = _get_line_bot_api()
    if api is None:
        logger.warning("LINE token is not configured; skip push", extra={"event": "line_push_missing_token"})
        return

    try:
        api.push_message(
            admin_user_id,
            TextSendMessage(text=message_text)
        )
        logger.info("LINE push sent", extra={"event": "line_push_sent"})
    except LineBotApiError:
        logger.exception("LINE push failed", extra={"event": "line_push_failed"})
