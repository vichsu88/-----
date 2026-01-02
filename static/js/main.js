document.addEventListener('DOMContentLoaded', function() {
    /* ==============================
       1. 變數定義與初始化
       ============================== */
    const newsList = document.getElementById('news-list');
    const faqList = document.getElementById('faq-list'); // ★ 新增：FAQ 的容器
    const modal = document.getElementById('announcementModal');
    
    // 使用 ?. 避免報錯
    const modalDate = modal?.querySelector('.modal-date');
    const modalTitle = modal?.querySelector('.modal-title');
    const modalBody = modal?.querySelector('.modal-body');
    const closeModalBtn = document.getElementById('modalCloseBtn');
    
    let allNewsData = []; 

    /* ==============================
       【工具】解析連結函式
       將 "文字($'網址'$)" 轉換為 HTML 連結
       ============================== */
    function parseContentForLinks(text) {
        if (!text) return '';
        // 抓取 文字($'網址'$)
        const regex = /(.+?)\(\$\'(.+?)\'\$\)/g;
        const replacement = '<a href="$2" target="_blank" rel="noopener noreferrer" style="color: #007bff; text-decoration: underline;">$1</a>';
        return text.replace(regex, replacement);
    }

    /* ==============================
       2. FAQ 列表載入與搜尋功能 (★ 全新修正)
       ============================== */
    if (faqList) {
        // 2-1. 從後端抓取 FAQ 資料
        fetch('/api/faq')
            .then(res => res.json())
            .then(faqs => {
                if (faqs.length === 0) {
                    faqList.innerHTML = '<p style="text-align:center;">目前沒有常見問題。</p>';
                    return;
                }

                // 2-2. 渲染 HTML (後端已排好序：置頂 -> 時間)
                faqList.innerHTML = faqs.map(faq => `
                    <div class="faq-item-card">
                        <div class="faq-q">Q：${faq.question}</div>
                        <div class="faq-a">A：${parseContentForLinks(faq.answer).replace(/\n/g, '<br>')}</div>
                    </div>
                `).join('');

                // 2-3. 綁定搜尋功能 (必須等資料長出來後才能綁定)
                setupFaqSearch();
            })
            .catch(err => {
                console.error('FAQ 載入失敗:', err);
                faqList.innerHTML = '<p style="text-align:center;">載入失敗，請稍後再試。</p>';
            });
    }

    // 搜尋功能邏輯封裝
    function setupFaqSearch() {
        const searchInput = document.getElementById('faqSearch');
        const faqCards = document.querySelectorAll('.faq-item-card'); // 抓取剛剛生成的卡片
        const noResultMsg = document.getElementById('no-result-msg');

        if (searchInput && faqCards.length > 0) {
            searchInput.addEventListener('input', function(e) {
                const term = e.target.value.trim().toLowerCase();
                let hasResult = false;

                faqCards.forEach(card => {
                    const qText = card.querySelector('.faq-q')?.textContent || '';
                    const aText = card.querySelector('.faq-a')?.textContent || '';
                    const fullText = (qText + aText).toLowerCase();
                    const isMatch = fullText.includes(term);
                    
                    card.style.display = isMatch ? '' : 'none';
                    if (isMatch) hasResult = true;
                });

                if (noResultMsg) {
                    noResultMsg.style.display = hasResult ? 'none' : 'block';
                }
            });
        }
    }

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
                    
                    newsItem.addEventListener('click', () => {
                        if (modal && modalDate && modalTitle && modalBody) {
                            const newsData = allNewsData[index];
                            modalDate.textContent = newsData.date;
                            modalTitle.textContent = newsData.title;
                            
                            // ★ 這裡也使用連結轉換
                            const contentWithLinks = parseContentForLinks(newsData.content);
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
        closeModalBtn.addEventListener('click', () => modal.style.display = 'none');
        modal.addEventListener('click', (e) => {
            if (e.target === modal) modal.style.display = 'none';
        });
    }

    /* ==============================
       5. 手機版 Overlay 選單互動
       ============================== */
    const navToggleBtn = document.querySelector('.nav-toggle');
    const mobileNavOverlay = document.getElementById('mobile-nav-overlay');
    const closeOverlayBtn = document.getElementById('overlay-close-btn');
    const overlayLinks = document.querySelectorAll('.overlay-nav-links a');

    if (navToggleBtn && mobileNavOverlay) {
        navToggleBtn.addEventListener('click', () => mobileNavOverlay.classList.add('is-visible'));
        if(closeOverlayBtn) closeOverlayBtn.addEventListener('click', () => mobileNavOverlay.classList.remove('is-visible'));
        overlayLinks.forEach(link => {
            link.addEventListener('click', () => mobileNavOverlay.classList.remove('is-visible'));
        });
    }
});