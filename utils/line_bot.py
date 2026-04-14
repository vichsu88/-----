from linebot import LineBotApi
from linebot.models import TextSendMessage
from linebot.exceptions import LineBotApiError

# 填入你剛剛拿到的 Access Token
LINE_CHANNEL_ACCESS_TOKEN = "DXSy5nvM7UX/MS4JecDnho/4Xr2DoiCiTOBKAg0adCcdEyY1m+V68E/Vz1tmc+rRZKbCyziE26I+UXLmWB2F78suyplqqM95xOpfuXEpkp0DWhlb3JcWec6Pg4D4lZNfdjBsYHvxurc8LVpHpGf0VAdB04t89/1O/w1cDnyilFU="
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)

def send_admin_notification(message_text):
    """
    發送通知給系統管理員 (也就是你)
    """
    # 這裡要填入你自己的 LINE User ID (稍後會教你去哪裡拿)
    admin_user_id = "Ua153013c2048f6bfb12937f93a672709"
    
    try:
        line_bot_api.push_message(
            admin_user_id,
            TextSendMessage(text=message_text)
        )
        print("✅ LINE 推播成功！")
    except LineBotApiError as e:
        print(f"❌ LINE 推播失敗: {e}")