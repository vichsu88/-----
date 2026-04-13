import json
import smtplib
import threading
import urllib.request
import urllib.error
from datetime import datetime, timedelta

from utils.helpers import get_tw_now


# =========================================
# 寄信核心功能 (SendGrid API)
# =========================================

def send_email_task(to_email, subject, body, is_html, **kwargs):
    # 從環境變數讀取 Namecheap SMTP 設定
    mail_server = os.environ.get('MAIL_SERVER', 'mail.privateemail.com')
    mail_port = int(os.environ.get('MAIL_PORT', 465))
    mail_sender = os.environ.get('MAIL_USERNAME')
    mail_password = os.environ.get('MAIL_PASSWORD')

    if not mail_sender or not mail_password:
        print("❌ 錯誤: SMTP 帳號或密碼未設定")
        return

    msg = MIMEMultipart()
    msg['From'] = mail_sender
    msg['To'] = to_email
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'html' if is_html else 'plain', 'utf-8'))

    try:
        if mail_port == 465:
            server = smtplib.SMTP_SSL(mail_server, mail_port)
        else:
            server = smtplib.SMTP(mail_server, mail_port)
            server.starttls()
            
        server.login(mail_sender, mail_password)
        server.send_message(msg)
        server.quit()
        print(f"✅ Namecheap SMTP 寄信成功!")
    except Exception as e:
        print(f"❌ SMTP 寄信出錯: {str(e)}")
        
def send_email(to_email, subject, body, sendgrid_api_key=None, mail_sender=None, is_html=False):
    if not to_email:
        return
    # 這裡保留舊的參數名稱是為了不改動其他呼叫此函數的地方
    thread = threading.Thread(
        target=send_email_task,
        args=(to_email, subject, body, is_html)
    )
    thread.start()
# =========================================
# 銀行資訊（從 DB 讀取）
# =========================================

def get_bank_info(db, usage='shop'):
    if db is None:
        return "請聯繫廟方確認匯款資訊"

    setting_key = "bank_info" if usage == 'fund' else "bank_info_shop"
    defaults = {
        'fund': {'code': '103', 'name': '新光銀行', 'account': '0666-50-971133-3'},
        'shop': {'code': '808', 'name': '玉山銀行', 'account': '尚未設定'}
    }
    settings = db.settings.find_one({"type": setting_key}) or {}
    code = settings.get('bankCode', defaults[usage]['code'])
    name = settings.get('bankName', defaults[usage]['name'])
    account = settings.get('account', defaults[usage]['account'])

    return f"""
    銀行代碼：<strong>{code} ({name})</strong><br>
    銀行帳號：<strong>{account}</strong>
    """


# =========================================
# Email HTML 模板產生器
# =========================================

def generate_feedback_email_html(feedback, status_type, tracking_num=None):
    name = feedback.get('realName', '信徒')

    if status_type == 'rejected':
        title = "感謝您的投稿與分享"
        content_body = """
        非常感謝您撥冗寫下與元帥的故事，我們已經收到您的投稿。<br><br>
        每一份分享都是對帥府最珍貴的支持。經內部審閱與討論後，由於目前的版面規劃與內容篩選考量，很遺憾此次<strong>暫時無法將您的文章刊登於官網</strong>，還請您見諒。<br><br>
        雖然文字未能在網上呈現，但您對元帥的這份心意，帥府上下都已深深感受到。歡迎您持續關注我們，也期待未來還有機會聽到您的分享。<br><br>
        闔家平安，萬事如意
        """
    elif status_type == 'approved':
        title = "您的回饋已核准刊登"
        content_body = """
        感謝分享您與元帥的故事！您的文章已審核通過，並正式<strong>刊登於承天中承府官方網站</strong>。這份法布施將讓更多有緣人感受到元帥的威靈與慈悲。<br><br>
        為了感謝您的發心，元帥娘特別準備了一份「小神衣」要與您結緣。<br><br>
        <div style="background:#fffcf5; padding:15px; border-left:4px solid #C48945; margin:15px 0; color:#555;">
            <strong>⚡ 元帥娘開符加持中</strong><br>
            目前元帥娘正在親自為小神衣進行「開符」與加持儀式，以確保將滿滿的祝福送到您手中。待儀式圓滿並寄出後，系統會再發送一封信件通知您，這段時間請您留意 Email 信箱。
        </div>
        <br>
        再次感謝您的分享！
        """
    elif status_type == 'sent':
        title = "小神衣寄出通知"
        content_body = f"""
        讓您久等了！<br>
        經過元帥娘開符加持的「小神衣」已於今日為您寄出。這份結緣品承載著帥府的祝福，希望能常伴您左右，護佑平安。<br><br>
        <div style="background:#f0ebe5; padding:15px; border:1px solid #C48945; border-radius:8px;">
            <strong>📦 物流單號：{tracking_num}</strong><br>
            <span style="font-size:13px; color:#666;">您可以透過此單號查詢配送進度。</span>
        </div><br>
        收到後若有任何問題，歡迎隨時透過官方 LINE 與我們聯繫。<br><br>
        願 煙島中壇元帥 庇佑您<br>
        身體健康，順心如意
        """
    else:
        title = "承天中承府通知"
        content_body = ""

    return f"""
    <div style="font-family: 'Microsoft JhengHei', sans-serif; max-width: 600px; margin: 0 auto; border: 1px solid #ddd; border-radius: 8px; overflow: hidden; background-color:#fff;">
        <div style="background: #C48945; padding: 20px; text-align: center;">
            <h2 style="color: #fff; margin: 0; letter-spacing: 1px;">{title}</h2>
        </div>
        <div style="padding: 30px;">
            <p style="font-size: 16px; color: #333; margin-bottom: 20px;">親愛的 <strong>{name}</strong> 您好：</p>
            <div style="font-size: 15px; color: #555; line-height: 1.6;">
                {content_body}
            </div>
            <div style="text-align: center; margin-top: 40px;">
                <a href="https://line.me/R/ti/p/@566dcres" target="_blank" style="background: #00B900; color: #fff; text-decoration: none; padding: 12px 35px; border-radius: 50px; font-weight: bold; display: inline-block; box-shadow: 0 4px 10px rgba(0,185,0,0.3); letter-spacing: 1px;">加入官方 LINE 客服</a>
            </div>
        </div>
        <div style="background: #eee; padding: 15px; text-align: center; font-size: 12px; color: #999;">承天中承府 ‧ 嘉義市新生路337號<br><span style="font-size:11px;">(此為系統自動發送信件，請勿直接回覆)</span></div>
    </div>
    """


def generate_shop_email_html(order, status_type, tracking_num=None, db=None):
    cust = order['customer']
    items = order['items']
    date_str = get_tw_now().strftime('%Y/%m/%d %H:%M')

    created_at_dt = order.get('createdAt')
    if created_at_dt and isinstance(created_at_dt, datetime):
        created_at_str = (created_at_dt + timedelta(hours=8)).strftime('%Y/%m/%d %H:%M')
    else:
        created_at_str = date_str

    bank_html = get_bank_info(db, 'shop')

    shipping_method = cust.get('shippingMethod', 'home')
    if shipping_method == '711':
        delivery_info_html = f"<strong>7-11 取貨門市：</strong>{cust.get('storeInfo', '未提供')}"
        shipping_label = "運費 (7-11 店到店)"
        shipping_fee_display = "60"
    else:
        delivery_info_html = f"<strong>收件地址：</strong>{cust.get('address', '未提供')}"
        shipping_label = "運費 (宅配)"
        shipping_fee_display = "120"

    if 'shippingFee' in cust:
        shipping_fee_display = str(cust['shippingFee'])

    if status_type == 'created':
        title = "訂單確認通知"
        color = "#C48945"
        status_text = f"""
        謝謝您的下單！我們已收到您的訂單。<br>
        訂單成立時間：{created_at_str}<br><br>
        <strong>【付款資訊】</strong><br>
        請於 <strong>2 小時內</strong> 完成匯款，以保留您的訂單資格。<br>
        <span style="color:#C48945; font-size:18px; font-weight:bold;">訂單總金額：NT$ {order['total']}</span><br>
        您的匯款後五碼：<strong>{cust.get('last5', '尚未提供')}</strong><br><br>
        <div style="background:#fffcf5; padding:15px; border-left:4px solid #C48945; margin:15px 0; color:#555;">
            {bank_html}
            <div style="margin-top:8px; font-size:13px; color:#d9534f;">※ 若未於 2 小時內付款，系統將取消此筆訂單。</div>
        </div><br>
        <strong>【配送資訊】</strong><br>
        {delivery_info_html}<br>
        聯絡電話：{cust.get('phone')}<br><br>
        <strong>【防詐騙提醒】</strong><br>
        <span style="color:#666; font-size:14px;">所有匯款請依照官方網頁公告之匯款帳號，若有疑慮請向官方 LINE 查證。</span>
        """
        show_price = True
    elif status_type == 'paid':
        title = "收款確認通知"
        color = "#28a745"
        status_text = f"""
        您的款項已確認！<br>
        帥府將盡速為您安排出貨，請您耐心等候。<br><br>
        <strong>確認時間：{date_str}</strong>
        """
        show_price = True
    else:
        title = "帥府出貨通知"
        color = "#C48945"
        status_text = f"""
        您的訂單已於今日出貨！<br><br>
        <div style="background:#f0ebe5; padding:15px; border:1px solid #C48945; border-radius:8px;">
            <strong>📦 物流單號：{tracking_num}</strong><br>
            <span style="font-size:13px; color:#666;">請依照上方單號，自行至物流網站查詢配送進度。</span>
        </div><br>
        <strong>出貨日期：{date_str}</strong><br>
        {delivery_info_html}<br><br>
        <span style="color:#666;">商品收到若有問題，請點擊下方按鈕詢問官方 LINE。</span>
        """
        show_price = False

    items_rows = ""
    for item in items:
        variant_str = f" ({item['variant']})" if "variant" in item and item["variant"] != "標準" else ""
        price_td = f'<td style="padding:10px; text-align:right;">${item["price"] * item["qty"]}</td>' if show_price else ""
        items_rows += f'<tr style="border-bottom: 1px solid #eee;"><td style="padding: 10px; color:#333;">{item["name"]}{variant_str}</td><td style="padding: 10px; text-align: center; color:#333;">x{item["qty"]}</td>{price_td}</tr>'

    price_th = '<th style="padding:10px; text-align:right;">金額</th>' if show_price else ''
    total_row = f'''
    <tfoot>
        <tr>
            <td colspan="2" style="padding:10px 10px; text-align:right; color:#666;">{shipping_label}</td>
            <td style="padding:10px 10px; text-align:right; color:#666;">+ {shipping_fee_display}</td>
        </tr>
        <tr>
            <td colspan="2" style="padding:15px 10px; text-align:right; font-weight:bold; color:#333;">總計</td>
            <td style="padding:15px 10px; text-align:right; font-weight:bold; color:#C48945; font-size:18px;">NT$ {order["total"]}</td>
        </tr>
    </tfoot>''' if show_price else ''

    return f"""
    <div style="font-family: 'Microsoft JhengHei', sans-serif; max-width: 600px; margin: 0 auto; border: 1px solid #ddd; border-radius: 8px; overflow: hidden; background-color:#fff;">
        <div style="background: {color}; padding: 20px; text-align: center;">
            <h2 style="color: #fff; margin: 0; letter-spacing: 1px;">{title}</h2>
            <p style="color: #fff; opacity: 0.9; margin: 5px 0 0 0; font-size: 14px;">訂單編號：{order['orderId']}</p>
        </div>
        <div style="padding: 30px;">
            <p style="font-size: 16px; color: #333; margin-bottom: 20px;">親愛的 <strong>{cust['name']}</strong> 您好：</p>
            <div style="font-size: 15px; color: #555; line-height: 1.6;">{status_text}</div>
            <div style="margin-top: 30px;">
                <h3 style="font-size:16px; color:#8B4513; border-bottom:2px solid #eee; padding-bottom:10px; margin-bottom:0;">訂單明細</h3>
                <table style="width: 100%; border-collapse: collapse; font-size: 14px;">
                    <thead><tr style="background: #f9f9f9; color:#666;"><th style="padding: 10px; text-align: left;">商品</th><th style="padding: 10px; text-align: center;">數量</th>{price_th}</tr></thead>
                    <tbody>{items_rows}</tbody>{total_row}
                </table>
            </div>
            <div style="text-align: center; margin-top: 40px;">
                <a href="https://line.me/R/ti/p/@566dcres" target="_blank" style="background: #00B900; color: #fff; text-decoration: none; padding: 12px 35px; border-radius: 50px; font-weight: bold; display: inline-block; box-shadow: 0 4px 10px rgba(0,185,0,0.3); letter-spacing: 1px;">加入官方 LINE 客服</a>
            </div>
        </div>
        <div style="background: #eee; padding: 15px; text-align: center; font-size: 12px; color: #999;">承天中承府 ‧ 嘉義市新生路337號<br><span style="font-size:11px;">(此為系統自動發送信件，請勿直接回覆)</span></div>
    </div>
    """


def generate_donation_created_email(order, db=None):
    cust = order['customer']
    items = order['items']
    order_type = order.get('orderType', 'donation')

    if order_type == 'committee':
        bank_html = """
        銀行代碼：<strong>103 (臺灣新光銀行 北嘉義分行)</strong><br>
        銀行帳號：<strong>0666-10-948888-9</strong><br>
        戶名：<strong>芭芭菸酒水專賣店</strong>
        """
    else:
        bank_type = 'fund' if order_type == 'fund' else 'shop'
        bank_html = get_bank_info(db, bank_type)

    items_rows = "".join([
        f'<tr style="border-bottom: 1px solid #eee;"><td style="padding: 10px; color:#333;">{item["name"]}</td>'
        f'<td style="padding: 10px; text-align: center; color:#333;">x{item["qty"]}</td>'
        f'<td style="padding: 10px; text-align: right;">${item["price"] * item["qty"]}</td></tr>'
        for item in items
    ])

    return f"""
    <div style="font-family: 'Microsoft JhengHei', sans-serif; max-width: 600px; margin: 0 auto; border: 1px solid #ddd; border-radius: 8px; overflow: hidden; background-color:#fff;">
        <div style="background: #C48945; padding: 20px; text-align: center;">
            <h2 style="color: #fff; margin: 0; letter-spacing: 1px;">護持登記確認</h2>
            <p style="color: #fff; opacity: 0.9; margin: 5px 0 0 0; font-size: 14px;">單號：{order['orderId']}</p>
        </div>
        <div style="padding: 30px;">
            <p style="font-size: 16px; color: #333; margin-bottom: 20px;">親愛的 <strong>{cust['name']}</strong> 您好：</p>
            <div style="font-size: 15px; color: #555; line-height: 1.6;">
                感恩您的發心！我們已收到您護持公壇的意願登記。<br>這是一份來自善念的承諾，為了讓這份心意能順利化作助人的力量，請您於 <strong>2 小時內</strong> 完成匯款，以圓滿此次護持。<br><br><strong>【您的護持項目】</strong>
            </div>
            <div style="margin-top: 15px;">
                <table style="width: 100%; border-collapse: collapse; font-size: 14px;">
                    <thead><tr style="background: #f9f9f9; color:#666;"><th style="padding: 10px; text-align: left;">項目</th><th style="padding: 10px; text-align: center;">數量</th><th style="padding: 10px; text-align: right;">金額</th></tr></thead>
                    <tbody>{items_rows}</tbody>
                    <tfoot><tr><td colspan="2" style="padding:15px 10px; text-align:right; font-weight:bold; color:#333;">護持總金額</td><td style="padding:15px 10px; text-align:right; font-weight:bold; color:#C48945; font-size:18px;">NT$ {order['total']}</td></tr></tfoot>
                </table>
            </div>
            <div style="background:#fffcf5; padding:15px; border-left:4px solid #C48945; margin:20px 0; color:#555;">
                <strong>【匯款資訊】</strong><br>{bank_html}
                <div style="margin-top:8px;">您的匯款後五碼：<strong>{cust.get('last5', '尚未提供')}</strong></div>
            </div>
            <div style="font-size: 14px; color: #666; margin-top: 20px; border-top: 1px dashed #ddd; padding-top: 15px;">
                <strong>【重要提醒】</strong><ol style="margin-left: -20px; margin-top: 5px;"><li>確認善款入帳後，我們將寄發「電子感謝狀」給您。</li><li><strong>防詐騙提醒</strong>：帥府人員不會致電要求您操作 ATM 或變更轉帳設定。若有疑慮，請務必點擊下方按鈕向官方 LINE 查證。</li></ol>
            </div>
            <div style="text-align: center; margin-top: 30px;">
                <a href="https://line.me/R/ti/p/@566dcres" target="_blank" style="background: #00B900; color: #fff; text-decoration: none; padding: 12px 35px; border-radius: 50px; font-weight: bold; display: inline-block; box-shadow: 0 4px 10px rgba(0,185,0,0.3); letter-spacing: 1px;">加入官方 LINE 客服</a>
            </div>
        </div>
        <div style="background: #eee; padding: 15px; text-align: center; font-size: 12px; color: #999;">承天中承府 ‧ 嘉義市新生路337號</div>
    </div>
    """


def generate_donation_paid_email(cust, order_id, items, total):
    items_str = "、".join([f"{i['name']} x {i['qty']}" for i in items])
    now = get_tw_now()
    roc_year = now.year - 1911
    date_str = f"中華民國 {roc_year} 年 {now.month} 月 {now.day} 日"

    return f"""
    <div style="font-family: 'KaiTi', 'BiauKai', 'DFKai-SB', serif; max-width: 650px; margin: 0 auto; border: 8px double #C48945; padding: 40px 30px; background-color: #fdf8e4; color: #333; line-height: 1.8; box-sizing: border-box;">

        <div style="text-align: center; margin-bottom: 20px;">
            <p style="font-size: 20px; margin: 0; font-weight: bold; color: #8B4513;">奉<br>煙島中壇元帥 聖示</p>
        </div>

        <div style="text-align: center; margin-bottom: 30px;">
            <h2 style="font-size: 22px; color: #555; margin: 0;">桃城 承天 中承府</h2>
            <h1 style="font-size: 34px; color: #C48945; margin: 5px 0 0 0; letter-spacing: 2px;">【功德感謝狀】</h1>
        </div>

        <div style="font-size: 18px; margin-bottom: 35px; padding: 0 10px;">
            <p style="margin: 0 0 10px 0; font-weight: bold;">茲感謝</p>
            <table style="width: 100%; border-collapse: collapse; font-size: 18px;">
                <tr>
                    <td style="width: 100px; padding: 6px 0; color: #555;">姓　　名：</td>
                    <td style="border-bottom: 1px solid #aaa; font-weight: bold;">{cust.get('name', '')}</td>
                </tr>
                <tr>
                    <td style="padding: 6px 0; color: #555;">地　　址：</td>
                    <td style="border-bottom: 1px solid #aaa;">{cust.get('address', '未提供')}</td>
                </tr>
                <tr>
                    <td style="padding: 6px 0; color: #555;">電　　話：</td>
                    <td style="border-bottom: 1px solid #aaa;">{cust.get('phone', '未提供')}</td>
                </tr>
                <tr>
                    <td style="padding: 6px 0; color: #555;">功德項目：</td>
                    <td style="border-bottom: 1px solid #aaa;">{items_str}</td>
                </tr>
                <tr>
                    <td style="padding: 6px 0; color: #555;">功 德 金：</td>
                    <td style="border-bottom: 1px solid #aaa; font-weight: bold; color: #C48945;">新臺幣 {total} 元整</td>
                </tr>
                <tr>
                    <td style="padding: 6px 0; color: #555;">備　　註：</td>
                    <td style="border-bottom: 1px solid #aaa; font-family: monospace; font-size: 16px;">{order_id}</td>
                </tr>
            </table>
        </div>

        <div style="text-align: center; font-size: 20px; color: #8B4513; margin-bottom: 35px; font-weight: bold;">
            <p style="margin: 8px 0;">發心隨喜，護持聖務；<br>誠意昭然，德澤有憑。</p>
            <p style="margin: 8px 0;">善念一動，功名入籍；<br>赤誠既至，福祿臨門。</p>
        </div>

        <div style="text-align: center; font-size: 18px; margin-bottom: 45px;">
            <p style="margin: 0 0 15px 0;">特此敬謝，並祈</p>
            <div style="display: inline-block; text-align: left; font-weight: bold; color: #C48945; font-size: 20px; border: 2px solid #E6BA67; padding: 15px 25px; border-radius: 8px; background: #fffcf5;">
                <p style="margin: 5px 0;">天赦開恩　運勢轉昌</p>
                <p style="margin: 5px 0;">財庫廣納　家道隆盛</p>
                <p style="margin: 5px 0;">光明長照　福壽綿延</p>
            </div>
        </div>

        <div style="text-align: right; font-size: 20px; margin-bottom: 30px; font-weight: bold; color: #333;">
            <p style="margin: 5px 0;">桃城 承天 中承府</p>
            <p style="margin: 5px 0;">煙島中壇元帥 鑑證</p>
        </div>

        <div style="text-align: right; font-size: 18px; margin-bottom: 40px; font-weight: bold; color: #555;">
            <p style="margin: 0;">{date_str}</p>
        </div>

        <div style="border-top: 1px dashed #C48945; padding-top: 20px; text-align: center; font-size: 15px; color: #666;">
            <p style="margin: 0; font-weight: bold; color: #8B4513;">附註：隨喜布施‧功德自記；福報隨行‧善緣自成。</p>
            <div style="margin-top: 25px;">
                <a href="https://line.me/R/ti/p/@566dcres" target="_blank" style="background: #00B900; color: #fff; text-decoration: none; padding: 10px 25px; border-radius: 50px; font-size: 14px; display: inline-block; font-family: 'Microsoft JhengHei', 'Noto Sans TC', sans-serif;">加入官方 LINE 客服</a>
                <div style="margin-top: 10px; font-size: 12px; color: #999; font-family: 'Microsoft JhengHei', 'Noto Sans TC', sans-serif;">(此為系統自動發送之電子感謝狀，請妥善保存)</div>
            </div>
        </div>
    </div>
    """
