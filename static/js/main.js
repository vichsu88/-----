
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
/* === 手機版 Overlay 選單互動 (升級版) === */
document.addEventListener('DOMContentLoaded', function() {
    // 抓取需要的 HTML 元素
    const navToggleBtn = document.querySelector('.nav-toggle');
    const mobileNavOverlay = document.getElementById('mobile-nav-overlay');
    const closeOverlayBtn = document.getElementById('overlay-close-btn');
    // 【新增】抓取選單中的所有連結
    const overlayLinks = document.querySelectorAll('.overlay-nav-links a');

    // 只有當這些元素都存在時，才綁定事件
    if (navToggleBtn && mobileNavOverlay && closeOverlayBtn) {

        // 點擊漢堡按鈕時，顯示 Overlay 選單
        navToggleBtn.addEventListener('click', function() {
            mobileNavOverlay.classList.add('is-visible');
        });

        // 點擊關閉按鈕時，隱藏 Overlay 選單
        closeOverlayBtn.addEventListener('click', function() {
            mobileNavOverlay.classList.remove('is-visible');
        });

        // 【新增】為每一個選單連結加上點擊事件
        overlayLinks.forEach(function(link) {
            link.addEventListener('click', function() {
                // 點擊任何一個連結後，都隱藏 Overlay 選單
                mobileNavOverlay.classList.remove('is-visible');
            });
        });
    }
});