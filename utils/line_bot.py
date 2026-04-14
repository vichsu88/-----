import os
from linebot import LineBotApi
from linebot.models import TextSendMessage
from linebot.exceptions import LineBotApiError

# 改用 os.getenv 從環境變數讀取，不再把密碼寫死在這裡！
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)

def send_admin_notification(message_text):
    """
    發送通知給系統管理員 (也就是你)
    """
    # 你的 User ID 可以留在這裡，因為這不算機密，這只是你的「收件地址」
    admin_user_id = "Ua153013c2048f6bfb12937f93a672709"
    
    try:
        line_bot_api.push_message(
            admin_user_id,
            TextSendMessage(text=message_text)
        )
        print("✅ LINE 推播成功！")
    except LineBotApiError as e:
        print(f"❌ LINE 推播失敗: {e}")