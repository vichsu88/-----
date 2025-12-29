document.addEventListener('DOMContentLoaded', function() {
    /* ==============================
       1. 變數定義與初始化
       ============================== */
    const newsList = document.getElementById('news-list');
    const modal = document.getElementById('announcementModal');
    // 確認 modal 存在才去抓內部的元素，避免報錯
    const modalDate = modal ? modal.querySelector('.modal-date') : null;
    const modalTitle = modal ? modal.querySelector('.modal-title') : null;
    const modalBody = modal ? modal.querySelector('.modal-body') : null;
    const closeModalBtn = document.getElementById('modalCloseBtn');
    
    let allNewsData = []; // 用來儲存從 API 獲取的完整資料

    /* ==============================
       2. FAQ 搜尋功能
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

                if (fullText.includes(searchTerm)) {
                    card.style.display = ''; 
                    hasResult = true;
                } else {
                    card.style.display = 'none'; 
                }
            });

            if (noResultMsg) {
                noResultMsg.style.display = hasResult ? 'none' : 'block';
            }
        });
    } // <--- 【修正點 1】原本這裡少了一個 }，導致後面的程式碼被卡住

    /* ==============================
       3. 進場動畫 (Intro Overlay)
       ============================== */
    const introOverlay = document.getElementById('intro-overlay');
    if (introOverlay) {
        if (sessionStorage.getItem('hasSeenIntro')) {
            introOverlay.style.display = 'none';
        } else {
            setTimeout(() => {
                introOverlay.classList.add('fade-out');
                sessionStorage.setItem('hasSeenIntro', 'true');
            }, 1000);
        }
    }

    /* ==============================
       4. 最新消息 (Fetch API)
       ============================== */
    // 小工具：解析連結
    function parseContentForLinks(text) {
        if (!text) return '';
        const regex = /(.+?)\(\$\'(.+?)\'\$\)/g;
        const replacement = '<a href="$2" target="_blank" rel="noopener noreferrer" style="color: #007bff; text-decoration: underline;">$1</a>';
        return text.replace(regex, replacement);
    }

    // 只有當 newsList 存在時才執行 Fetch，避免在非首頁報錯
    if (newsList) {
        fetch('/api/announcements')
            .then(response => response.json())
            .then(data => {
                allNewsData = data;
                newsList.innerHTML = '';

                data.forEach((news, index) => {
                    const newsItem = document.createElement('li');
                    newsItem.className = 'news-item';
                    newsItem.dataset.index = index;

                    newsItem.innerHTML = `
                        <span class="news-date">${news.date}</span>
                        <p class="news-title">${news.title}</p>
                    `;

                    newsItem.addEventListener('click', () => {
                        // 確保 Modal 相關元素都存在
                        if (modal && modalDate && modalTitle && modalBody) {
                            const newsData = allNewsData[index];
                            modalDate.textContent = newsData.date;
                            modalTitle.textContent = newsData.title;

                            const parsedContent = parseContentForLinks(newsData.content);
                            modalBody.innerHTML = parsedContent.replace(/\n/g, '<br>');

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

    // Modal 關閉邏輯 (需確認按鈕與 Modal 存在)
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
    // 【修正點 2】直接合併在同一個 DOMContentLoaded 裡
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