from repositories.history_repository import get_paginated_history
from utils.security import safe_regex_contains
from utils.timezone import taipei_date_range_query, format_taipei

_TYPE_LABELS = {
    'shop': '🛍️ 結緣品',
    'donation': '🕯️ 捐香',
    'fund': '🏗️ 建廟基金',
    'committee': '🏛️ 委員會',
    'feedback': '💬 回饋'
}

def fetch_history_data(order_type, order_id, name, status, start, end, page, per_page):
    skip = (page - 1) * per_page
    
    # --- 1. 組裝 Orders 查詢條件 ---
    orders_match = {}
    if order_type and order_type != 'feedback':
        orders_match['orderType'] = order_type
    elif order_type == 'feedback':
        # 巧妙設計：如果前端只想查 feedback，我們讓 orders 條件絕對不成立，節省效能
        orders_match['_id'] = "never_match" 

    if order_id:
        orders_match['orderId'] = {"$regex": safe_regex_contains(order_id), "$options": "i"}
    if name:
        orders_match['customer.name'] = {"$regex": safe_regex_contains(name)}
    if status:
        orders_match['status'] = status
    
    date_range = None
    if start and end:
        try:
            date_range = taipei_date_range_query(start, end)
            orders_match['createdAt'] = date_range
        except ValueError:
            pass

    # --- 2. 組裝 Feedback 查詢條件 ---
    feedback_match = {}
    if order_type and order_type != 'feedback':
        feedback_match['_id'] = "never_match"
        
    if order_id:
        feedback_match['feedbackId'] = {"$regex": safe_regex_contains(order_id), "$options": "i"}
    if name:
        name_regex = {"$regex": safe_regex_contains(name), "$options": "i"}
        feedback_match['$or'] = [
            {'nickname': name_regex},
            {'realName': name_regex}
        ]
    if status:
        feedback_match['status'] = status
    if date_range:
        feedback_match['createdAt'] = date_range

    # --- 3. 呼叫 Repository 取出資料 ---
    raw_data, total = get_paginated_history(orders_match, feedback_match, skip, per_page)

    # --- 4. 格式化回傳結果 (整理日期與標籤) ---
    results = []
    for doc in raw_data:
        doc['_id'] = str(doc['_id'])
        doc['createdAt'] = format_taipei(doc.get('createdAt'))
        
        if doc['_docType'] == 'order':
            if doc.get('updatedAt'): doc['updatedAt'] = format_taipei(doc['updatedAt'])
            if doc.get('paymentDeadline'): doc['paymentDeadline'] = format_taipei(doc['paymentDeadline'])
            doc['source_label'] = _TYPE_LABELS.get(doc.get('orderType', ''), '未知')
            if doc.get('paidAt'): doc['paidAt'] = format_taipei(doc['paidAt'])
            if doc.get('shippedAt'): doc['shippedAt'] = format_taipei(doc['shippedAt'])
            if doc.get('reportedAt'): doc['reportedAt'] = format_taipei(doc['reportedAt'])
        else:
            doc['source_label'] = '💬 回饋'
            if doc.get('approvedAt'): doc['approvedAt'] = format_taipei(doc['approvedAt'])
            if doc.get('sentAt'): doc['sentAt'] = format_taipei(doc['sentAt'])
        
        # 移除內部使用的標記
        doc.pop('_docType', None)
        results.append(doc)
        
    return results, total
