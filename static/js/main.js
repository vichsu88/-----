document.addEventListener('DOMContentLoaded', function() {
    /* ==============================
       1. 變數定義與初始化
       ============================== */
    const newsList = document.getElementById('news-list');
    const modal = document.getElementById('announcementModal');
    // 使用 Optional Chaining (?.) 避免找不到元素時報錯
    const modalDate = modal?.querySelector('.modal-date');
    const modalTitle = modal?.querySelector('.modal-title');
    const modalBody = modal?.querySelector('.modal-body');
    const closeModalBtn = document.getElementById('modalCloseBtn');
    let allNewsData = []; 

    /* ==============================
       【關鍵工具】解析連結函式
       將 "文字($'網址'$)" 轉換為可點擊的 HTML 連結
       ============================== */
    function parseContentForLinks(text) {
        if (!text) return '';
        // 抓取 文字($'網址'$) 的正規表示式
        const regex = /(.+?)\(\$\'(.+?)\'\$\)/g;
        const replacement = '<a href="$2" target="_blank" rel="noopener noreferrer" style="color: #007bff; text-decoration: underline;">$1</a>';
        return text.replace(regex, replacement);
    }

    /* ==============================
       2. FAQ 搜尋功能 (若頁面有此功能才執行)
       ============================== */
    const searchInput = document.getElementById('faqSearch');
    const faqCards = document.querySelectorAll('.faq-item-card');
    const noResultMsg = document.getElementById('no-result-msg');
    
    if (searchInput && faqCards.length > 0) {
        searchInput.addEventListener('input', function(e) {
            const searchTerm = e.target.value.trim().toLowerCase();
            let hasResult = false;
            faqCards.forEach(card => {
                const questionText = card.querySelector('.faq-q')?.textContent || '';
                const answerText = card.querySelector('.faq-a')?.textContent || '';
                const fullText = (questionText + answerText).toLowerCase();
                const isMatch = fullText.includes(searchTerm);
                card.style.display = isMatch ? '' : 'none';
                if (isMatch) hasResult = true;
            });
            if (noResultMsg) {
                noResultMsg.style.display = hasResult ? 'none' : 'block';
            }
        });
    }

    /* ==============================
       3. 進場動畫 (Intro Overlay)
       ============================== */
    const introOverlay = document.getElementById('intro-overlay');
    if (introOverlay) {
        if (sessionStorage.getItem('hasSeenIntro')) {
            introOverlay.style.display = 'none';
        } else {
            // 延遲 1 秒後開始淡出
            setTimeout(() => {
                introOverlay.classList.add('fade-out');
                sessionStorage.setItem('hasSeenIntro', 'true');
            }, 1000);
        }
    }

    /* ==============================
       4. 最新消息 (Fetch API) & 連結轉換
       ============================== */
    if (newsList) {
        fetch('/api/announcements')
            .then(response => response.json())
            .then(data => {
                allNewsData = data;
                newsList.innerHTML = '';
                
                if (data.length === 0) {
                    newsList.innerHTML = '<li class="news-item"><p class="news-title">目前沒有最新消息。</p></li>';
                    return;
                }

                data.forEach((news, index) => {
                    const newsItem = document.createElement('li');
                    newsItem.className = 'news-item';
                    newsItem.dataset.index = index;
                    newsItem.innerHTML = `
                        <span class="news-date">${news.date}</span>
                        <p class="news-title">${news.title}</p>
                    `;
                    
                    // 點擊公告時觸發
                    newsItem.addEventListener('click', () => {
                        if (modal && modalDate && modalTitle && modalBody) {
                            const newsData = allNewsData[index];
                            modalDate.textContent = newsData.date;
                            modalTitle.textContent = newsData.title;
                            
                            // 【關鍵步驟】1. 先轉換連結
                            const contentWithLinks = parseContentForLinks(newsData.content);
                            // 【關鍵步驟】2. 再處理換行符號
                            modalBody.innerHTML = contentWithLinks.replace(/\n/g, '<br>');
                            
                            modal.style.display = 'flex';
                        }
                    });
                    newsList.appendChild(newsItem);
                });
            })
            .catch(error => {
                console.error('Error fetching news:', error);
                newsList.innerHTML = '<li class="news-item"><p class="news-title">消息載入失敗，請稍後再試。</p></li>';
            });
    }

    // Modal 關閉邏輯
    if (closeModalBtn && modal) {
        closeModalBtn.addEventListener('click', () => {
            modal.style.display = 'none';
        });
        modal.addEventListener('click', (event) => {
            if (event.target === modal) {
                modal.style.display = 'none';
            }
        });
    }

    /* ==============================
       5. 手機版 Overlay 選單互動
       ============================== */
    const navToggleBtn = document.querySelector('.nav-toggle');
    const mobileNavOverlay = document.getElementById('mobile-nav-overlay');
    const closeOverlayBtn = document.getElementById('overlay-close-btn');
    const overlayLinks = document.querySelectorAll('.overlay-nav-links a');

    if (navToggleBtn && mobileNavOverlay && closeOverlayBtn) {
        navToggleBtn.addEventListener('click', function() {
            mobileNavOverlay.classList.add('is-visible');
        });
        closeOverlayBtn.addEventListener('click', function() {
            mobileNavOverlay.classList.remove('is-visible');
        });
        overlayLinks.forEach(function(link) {
            link.addEventListener('click', function() {
                mobileNavOverlay.classList.remove('is-visible');
            });
        });
    }
});