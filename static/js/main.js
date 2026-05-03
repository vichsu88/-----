document.addEventListener('DOMContentLoaded', function() {
    /* ==============================
       1. 變數定義與初始化
       ============================== */
    const newsList = document.getElementById('news-list');
    const faqList = document.getElementById('faq-list');
    const modal = document.getElementById('announcementModal');
    
    // [修正] 移除 ?. 語法以相容舊手機，改用傳統判斷
    let modalDate = null;
    let modalTitle = null;
    let modalBody = null;
    
    if (modal) {
        modalDate = modal.querySelector('.modal-date');
        modalTitle = modal.querySelector('.modal-title');
        modalBody = modal.querySelector('.modal-body');
    }

    const closeModalBtn = document.getElementById('modalCloseBtn');
    let allNewsData = []; 

    function showAnnouncementModal() {
        if (!modal) return;
        modal.style.removeProperty('display');
        modal.classList.add('show');
    }

    function hideAnnouncementModal() {
        if (!modal) return;
        modal.classList.remove('show');
        modal.style.removeProperty('display');
    }

    /* ==============================
       【工具】解析連結函式
       將 "文字($'網址'$)" 轉換為 HTML 連結
       ============================== */
    function isSafeLinkUrl(url) {
        try {
            const parsed = new URL(url, window.location.origin);
            return parsed.protocol === 'http:' || parsed.protocol === 'https:';
        } catch (e) {
            return false;
        }
    }

    function appendTextWithBreaks(target, text) {
        const parts = String(text || '').split(/\r?\n/);
        parts.forEach((part, index) => {
            if (index > 0) target.appendChild(document.createElement('br'));
            if (part) target.appendChild(document.createTextNode(part));
        });
    }

    function appendTextWithLinksAndBreaks(target, text) {
        const regex = /(.+?)\(\$\'(.+?)\'\$\)/g;
        const source = String(text || '');
        let lastIndex = 0;
        let match;

        while ((match = regex.exec(source)) !== null) {
            appendTextWithBreaks(target, source.slice(lastIndex, match.index));

            const label = match[1];
            const href = match[2];
            if (isSafeLinkUrl(href)) {
                const link = document.createElement('a');
                link.href = href;
                link.target = '_blank';
                link.rel = 'noopener noreferrer';
                link.style.color = '#007bff';
                link.style.textDecoration = 'underline';
                link.textContent = label;
                target.appendChild(link);
            } else {
                appendTextWithBreaks(target, match[0]);
            }

            lastIndex = regex.lastIndex;
        }

        appendTextWithBreaks(target, source.slice(lastIndex));
    }

    /* ==============================
       2. FAQ 列表載入與搜尋功能
       ============================== */
    if (faqList) {
        // 2-1. 從後端抓取 FAQ 資料
        fetch('/api/faq')
            .then(res => {
                if (!res.ok) throw new Error('Network response was not ok');
                return res.json();
            })
            .then(faqs => {
                if (faqs.length === 0) {
                    faqList.innerHTML = '<p style="text-align:center;">目前沒有常見問題。</p>';
                    return;
                }

                // 2-2. 渲染內容
                faqList.innerHTML = '';
                faqs.forEach(faq => {
                    const card = document.createElement('div');
                    card.className = 'faq-item-card';

                    const question = document.createElement('div');
                    question.className = 'faq-q';
                    question.textContent = `Q：${faq.question || ''}`;

                    const answer = document.createElement('div');
                    answer.className = 'faq-a';
                    answer.appendChild(document.createTextNode('A：'));
                    appendTextWithLinksAndBreaks(answer, faq.answer || '');

                    card.appendChild(question);
                    card.appendChild(answer);
                    faqList.appendChild(card);
                });

                // 2-3. 綁定搜尋功能
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
        const faqCards = document.querySelectorAll('.faq-item-card');
        const noResultMsg = document.getElementById('no-result-msg');

        if (searchInput && faqCards.length > 0) {
            searchInput.addEventListener('input', function(e) {
                const term = e.target.value.trim().toLowerCase();
                let hasResult = false;

                faqCards.forEach(card => {
                    const qElem = card.querySelector('.faq-q');
                    const aElem = card.querySelector('.faq-a');
                    const qText = qElem ? qElem.textContent : '';
                    const aText = aElem ? aElem.textContent : '';
                    
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
    // 使用 try-catch 包裹 localStorage/sessionStorage 避免隱私模式報錯
    try {
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
    } catch (e) {
        console.warn('Storage access failed (likely private mode):', e);
        if (introOverlay) {
             // 如果 storage 失敗，至少確保動畫會跑完並消失，不擋住畫面
             setTimeout(() => {
                introOverlay.classList.add('fade-out');
            }, 1000);
        }
    }

    /* ==============================
       4. 最新消息 (Fetch API)
       ============================== */
    if (newsList && !newsList.querySelector('[data-news]')) {
        fetch('/api/announcements')
            .then(res => {
                if (!res.ok) throw new Error('Network response was not ok');
                return res.json();
            })
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

                    const date = document.createElement('span');
                    date.className = 'news-date';
                    date.textContent = news.date || '';

                    const title = document.createElement('p');
                    title.className = 'news-title';
                    title.textContent = news.title || '';

                    newsItem.appendChild(date);
                    newsItem.appendChild(title);
                    
                    newsItem.addEventListener('click', () => {
                        if (modal && modalDate && modalTitle && modalBody) {
                            const newsData = allNewsData[index];
                            modalDate.textContent = newsData.date;
                            modalTitle.textContent = newsData.title;
                            
                            modalBody.innerHTML = '';
                            appendTextWithLinksAndBreaks(modalBody, newsData.content || '');
                            
                            showAnnouncementModal();
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
        closeModalBtn.addEventListener('click', hideAnnouncementModal);
        modal.addEventListener('click', (e) => {
            if (e.target === modal) hideAnnouncementModal();
        });
    }

    /* ==============================
       5. 手機版 Overlay 選單互動 (合併邏輯)
       ============================== */
    const menuBtn = document.querySelector('.nav-toggle'); // 漢堡按鈕
    const closeBtn = document.getElementById('overlay-close-btn') || document.querySelector('.overlay-close-btn');
    const overlay = document.getElementById('mobile-nav-overlay') || document.querySelector('.mobile-nav-overlay');
    const body = document.body;
    const navLinks = document.querySelectorAll('.overlay-nav-links a');

    function toggleMenu(show) {
        if (!overlay) return;
        
        if (show) {
            overlay.classList.add('is-visible');
            body.classList.add('menu-open'); // 鎖定背景滾動
        } else {
            overlay.classList.remove('is-visible');
            body.classList.remove('menu-open'); // 解除鎖定
        }
    }

    // 點擊漢堡按鈕
    if (menuBtn) {
        menuBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            toggleMenu(true);
        });
    }

    // 點擊關閉按鈕
    if (closeBtn) {
        closeBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            toggleMenu(false);
        });
    }

    // 點擊選單連結後自動關閉
    if (navLinks.length > 0) {
        navLinks.forEach(link => {
            link.addEventListener('click', () => {
                toggleMenu(false);
            });
        });
    }
});
