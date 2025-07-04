
document.addEventListener('DOMContentLoaded', function() {
    const newsList = document.getElementById('news-list');
    const modal = document.getElementById('announcementModal');
    const modalDate = modal.querySelector('.modal-date');
    const modalTitle = modal.querySelector('.modal-title');
    const modalBody = modal.querySelector('.modal-body');
    const closeModalBtn = document.getElementById('modalCloseBtn');
    let allNewsData = []; // 用來儲存從 API 獲取的完整資料

    // 從後端 API 獲取最新消息
    fetch('/api/announcements')
    .then(response => response.json())
        .then(data => {
            allNewsData = data; // 儲存資料
            newsList.innerHTML = ''; // 清空現有內容

            // 遍歷資料，生成消息列表
            data.forEach((news, index) => {
                const newsItem = document.createElement('li');
                newsItem.className = 'news-item';
                // 將索引存儲在 data-index 屬性中，方便後續查找
                newsItem.dataset.index = index; 

                newsItem.innerHTML = `
                    <span class="news-date">${news.date}</span>
                    <p class="news-title">${news.title}</p>
                `;

                // 為每個消息項目添加點擊事件監聽器
                newsItem.addEventListener('click', () => {
                    // 從 allNewsData 中找到對應的完整資料
                    const newsData = allNewsData[index];

                    // 更新彈出視窗的內容
                    modalDate.textContent = newsData.date;
                    modalTitle.textContent = newsData.title;
                    // 將內容中的換行符號 \n 轉換為 <br>
                    modalBody.innerHTML = newsData.content.replace(/\n/g, '<br>');

                    // 顯示彈出視窗
                    modal.style.display = 'flex';
                });

                newsList.appendChild(newsItem);
            });
        })
        .catch(error => {
            console.error('Error fetching news:', error);
            newsList.innerHTML = '<li class="news-item"><p class="news-title">消息載入失敗，請稍後再試。</p></li>';
        });

    // 關閉彈出視窗的按鈕事件
    closeModalBtn.addEventListener('click', () => {
        modal.style.display = 'none';
    });

    // 點擊彈出視窗外部區域也可關閉
    modal.addEventListener('click', (event) => {
        if (event.target === modal) {
            modal.style.display = 'none';
        }
    });
});