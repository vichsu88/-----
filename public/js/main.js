// public/js/main.js

// 等待 HTML 頁面都載入完成後再執行
document.addEventListener('DOMContentLoaded', function() {
    
    // 找到所有可以點擊的消息項目
    const newsItems = document.querySelectorAll('.news-item');
    // 找到彈窗本身
    const modal = document.getElementById('announcementModal');
    // 找到關閉按鈕
    const closeBtn = document.getElementById('modalCloseBtn');

    // 如果頁面上有彈窗，才執行以下程式碼
    if (modal) {
        // 為每一個消息項目加上點擊事件
        newsItems.forEach(item => {
            item.addEventListener('click', function() {
                // 這裡未來會從後端抓取真實資料，現在先用假資料填充
                // document.querySelector('.modal-date').textContent = ...
                // document.querySelector('.modal-title').textContent = ...
                // document.querySelector('.modal-body').innerHTML = ...
                
                // 顯示彈窗
                modal.style.display = 'flex';
            });
        });

        // 為關閉按鈕加上點擊事件
        closeBtn.addEventListener('click', function() {
            modal.style.display = 'none'; // 隱藏彈窗
        });

        // 點擊彈窗的灰色背景區域也可以關閉
        modal.addEventListener('click', function(event) {
            if (event.target === modal) {
                modal.style.display = 'none';
            }
        });
    }
});