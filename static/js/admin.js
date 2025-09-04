// --- static/js/admin.js (最終安全版，整合專家建議) ---
document.addEventListener('DOMContentLoaded', () => {
    /**
     * 這是一個小工具，可以把 "文字($'網址'$)" 變成真正的連結
     */
    function parseContentForLinks(text) {
        if (!text) {
            return '';
        }
        const regex = /(.+?)\(\$\'(.+?)\'\$\)/g;
        const replacement = '<a href="$2" target="_blank" rel="noopener noreferrer" style="color: #007bff; text-decoration: underline;">$1</a>';
        return text.replace(regex, replacement);
    }
    // --- 1. 共用工具函式 ---
    /**
     * 從 <meta> 標籤獲取 CSRF Token
     * @returns {string} CSRF Token
     */
    const getCsrfToken = () => document.querySelector('meta[name="csrf-token"]').getAttribute('content');
    /**
     * 封裝全局 fetch 請求，自動處理 CSRF token, headers, credentials 和錯誤
     * @param {string} url - API 的 URL
     * @param {object} options - fetch 的設定選項 (method, body, etc.)
     * @returns {Promise<any>} - 解析後的 JSON 物件或純文字
     */
    async function apiFetch(url, options = {}) {
        const hasBody = !!options.body;
        const headers = {
            // 使用標準的展開運算子 (...)，並確保 options.headers 存在
            ...(hasBody && { 'Content-Type': 'application/json' }),
            'X-CSRFToken': getCsrfToken(),
            ...(options.headers || {}) // 加上 || {} 避免 options.headers 未定義時出錯
        };
        try {
            const response = await fetch(url, {
                // 將 options 物件展開，並確保我們的設定（credentials, headers）會覆蓋傳入的同名屬性
                ...options,
                credentials: 'include',
                headers
            });
            if (!response.ok) {
                const errorText = await response.text();
                let errorMessage = errorText;
                try {
                    const errorJson = JSON.parse(errorText);
                    errorMessage = errorJson.error || errorJson.message || errorText;
                } catch (e) {
                    // 解析 JSON 失敗，直接使用純文字錯誤
                }
                throw new Error(errorMessage || `請求失敗，狀態碼: ${response.status}`);
            }
            const contentType = response.headers.get('Content-Type') || '';
            // 如果後端明確回傳 text/plain，就當作純文字處理
            if (contentType.includes('application/json')) {
                return response.json();
            }
            return response.text();
        } catch (error) {
            console.error(`API Fetch Error (${url}):`, error);
            // 將錯誤再次拋出，讓呼叫的地方可以捕捉到並顯示給使用者
            throw error;
        }
    }
    // --- 2. DOM 元素宣告 ---
    const loginContainer = document.getElementById('login-container');
    const adminContent = document.getElementById('admin-content');
    const loginForm = document.getElementById('login-form');
    const passwordInput = document.getElementById('admin-password');
    const loginError = document.getElementById('login-error');
    const logoutBtn = document.getElementById('logout-btn');
    const linksListDiv = document.getElementById('links-list');
    const pendingListContainer = document.getElementById('pending-feedback-list');
    const approvedListContainer = document.getElementById('approved-feedback-list');
    const markAllBtn = document.getElementById('mark-all-btn');
    const exportBtn = document.getElementById('export-btn');
    const exportModal = document.getElementById('export-modal');
    const exportTextareaInModal = document.getElementById('export-output-textarea');
    const viewModal = document.getElementById('view-modal');
    const faqListDiv = document.getElementById('faq-list');
    const faqCategoryBtnsDiv = document.getElementById('faq-category-btns');
    const addFaqBtn = document.getElementById('add-faq-btn');
    const faqModal = document.getElementById('faq-modal');
    const faqForm = document.getElementById('faq-form');
    const faqModalCategoryBtns = document.getElementById('faq-modal-category-btns');
    const announcementsListDiv = document.getElementById('announcements-list');
    const addAnnouncementBtn = document.getElementById('add-announcement-btn');
    const announcementFormModal = document.getElementById('announcement-modal');
    const announcementForm = document.getElementById('announcement-form');
    const announcementFormTitle = document.getElementById('announcement-modal-title');
    const announcementViewModal = document.getElementById('announcement-view-modal');
    const announcementViewModalBody = document.getElementById('announcement-view-modal-body');
    const deleteAnnouncementFromModalBtn = document.getElementById('delete-announcement-from-modal-btn');
    // --- 3. 核心函式與事件綁定 ---
    async function checkSession() {
        const data = await fetch('/api/session_check').then(res => res.json());
        if (data.logged_in) {
            showAdminContent();
        } else {
            showLogin();
        }
    }
    loginForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        loginError.textContent = '';
        try {
            // 注意：登入 API 是豁免 CSRF 的，所以可以直接呼叫
            const response = await fetch('/api/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ password: passwordInput.value })
            });
            const data = await response.json();
            if (data.success) {
                // ★ 關鍵修正：登入成功後必須刷新頁面，以獲取與新 session 綁定的 CSRF token
                window.location.reload();
            } else {
                loginError.textContent = data.message || '登入失敗';
            }
        } catch (err) {
            loginError.textContent = '請求失敗，請檢查網路或伺服器狀態。';
        }
    });
    logoutBtn.addEventListener('click', async () => {
        await apiFetch('/api/logout', { method: 'POST' });
        showLogin();
    });
    function showLogin() {
        loginContainer.style.display = 'block';
        adminContent.style.display = 'none';
        passwordInput.value = '';
    }
    function showAdminContent() {
        loginContainer.style.display = 'none';
        adminContent.style.display = 'block';
        if (!adminContent.dataset.initialized) {
            setupTabs();
            // 預設觸發第一個頁籤的點擊事件來載入內容
            document.querySelector('.tab-btn').click();
            adminContent.dataset.initialized = 'true';
        }
    }
    async function fetchLinks() {
        try {
            const links = await apiFetch('/api/links');
            linksListDiv.innerHTML = '';
            links.forEach(link => {
                const item = document.createElement('div');
                item.className = 'link-item';
                // 修正打字錯誤
                item.innerHTML = `
                    <span class="link-name-display">${link.name}</span>
                    <input class="link-url-display" type="text" value="${link.url}" readonly>
                    <button class="edit-btn btn" data-id="${link._id}">修改</button>
                `;
                linksListDiv.appendChild(item);
            });
        } catch (error) { console.error('抓取連結列表失敗:', error); }
    }
    linksListDiv.addEventListener('click', async function (event) {
        if (event.target.classList.contains('edit-btn')) {
            const id = event.target.dataset.id;
            const newUrl = prompt('請輸入新的連結網址：', event.target.closest('.link-item').querySelector('input').value);
            if (newUrl !== null && newUrl.trim() !== '') {
                try {
                    await apiFetch(`/api/links/${id}`, {
                        method: 'PUT',
                        body: JSON.stringify({ url: newUrl })
                    });
                    fetchLinks();
                } catch (error) { alert(`更新失敗: ${error.message}`); }
            }
        }
    });
    // (以下是您所有的原始函式，現在它們可以安全地運作了)
    async function fetchPendingFeedback() {
        try {
            const data = await apiFetch('/api/feedback/pending');
            pendingListContainer.innerHTML = '';
            if (data.length === 0) {
                pendingListContainer.innerHTML = '<p>目前沒有待審核的回饋。</p>';
                return;
            }
            data.forEach(item => {
                const card = document.createElement('div');
                card.className = 'feedback-card';
                card.innerHTML = `
                    <div class="feedback-card__header">
                        <span class="feedback-card__info"><span class="nickname">${item.nickname}</span> / ${item.category.join(', ')}</span>
                        <span>${item.createdAt}</span>
                    </div>
                    <p class="feedback-card__content">${item.content}</p>
                    <div class="feedback-card__actions">
                        <button class="btn delete-feedback-btn" data-id="${item._id}">不同意刪除</button>
                        <button class="btn btn--brown approve-feedback-btn" data-id="${item._id}">同意刊登</button>
                    </div>
                `;
                pendingListContainer.appendChild(card);
            });
        } catch (error) { console.error('抓取待審核回饋失敗:', error); }
    }
    async function fetchApprovedFeedback() {
        try {
            const data = await apiFetch('/api/feedback/approved');
            approvedListContainer.innerHTML = '';
            if (data.length === 0) {
                approvedListContainer.innerHTML = '<p>目前沒有已審核的回饋。</p>';
                return;
            }
            data.forEach(item => {
                const card = document.createElement('div');
                card.className = 'feedback-card';
                card.innerHTML = `
                    <div class="feedback-card__header">
                        <span class="feedback-card__info"><span class="nickname">${item.nickname}</span> / ${item.category.join(', ')}</span>
                        <span>${item.createdAt}</span>
                    </div>
                    <p class="feedback-card__content">${item.content}</p>
                    <div class="feedback-card__actions">
                        <button class="btn btn--brown view-feedback-btn" data-id="${item._id}">查看</button>
                    </div>
                `;
                card.querySelector('.view-feedback-btn').addEventListener('click', () => {
                    showDetailModal(item);
                });
                approvedListContainer.appendChild(card);
            });
        } catch (error) { console.error('抓取已審核回饋失敗:', error); }
    }
    adminContent.addEventListener('click', async (e) => {
        const target = e.target;
        const id = target.dataset.id;
        try {
            if (target.classList.contains('approve-feedback-btn')) {
                if (!confirm('確定要同意刊登這則回饋嗎？')) return;
                await apiFetch(`/api/feedback/${id}/approve`, { method: 'PUT' });
                fetchPendingFeedback();
                fetchApprovedFeedback();
            } else if (target.classList.contains('delete-feedback-btn')) {
                if (!confirm('確定要永久刪除這則回饋嗎？')) return;
                await apiFetch(`/api/feedback/${id}`, { method: 'DELETE' });
                fetchPendingFeedback();
                fetchApprovedFeedback();
                closeDetailModal();
            } else if (target.classList.contains('mark-feedback-btn')) {
                const isMarked = target.dataset.marked === 'true';
                await apiFetch(`/api/feedback/${id}/mark`, {
                    method: 'PUT',
                    body: JSON.stringify({ isMarked: !isMarked })
                });
                fetchApprovedFeedback();
            }
        } catch (error) {
            alert(`操作失敗: ${error.message}`);
        }
    });
    markAllBtn.addEventListener('click', async () => {
        if (!confirm('確定要將所有已審核的回饋都標記為已處理嗎？')) return;
        try {
            await apiFetch('/api/feedback/mark-all-approved', { method: 'PUT' });
            fetchApprovedFeedback();
        } catch (error) {
            alert(`操作失敗: ${error.message}`);
        }
    });
    exportBtn.addEventListener('click', async () => {
        try {
            const textData = await apiFetch('/api/feedback/export-unmarked');
            exportTextareaInModal.value = textData;
            exportModal.classList.add('is-visible');
        } catch (error) {
            alert(`導出時發生錯誤: ${error.message}`);
        }
    });
    exportModal.addEventListener('click', (e) => {
        if (e.target.classList.contains('modal-close-btn') || e.target.id === 'export-modal') {
            exportModal.classList.remove('is-visible');
        }
    });
    function setupTabs() {
        const mainTabs = document.querySelectorAll('.tab-btn');
        const mainContents = document.querySelectorAll('.tab-content');
        mainTabs.forEach(tab => {
            tab.addEventListener('click', () => {
                mainTabs.forEach(t => t.classList.remove('active'));
                mainContents.forEach(c => c.classList.remove('active'));
                tab.classList.add('active');
                const activeContent = document.getElementById(tab.dataset.tab);
                if (activeContent) activeContent.classList.add('active');
                switch (tab.dataset.tab) {
                    case 'tab-links': fetchLinks(); break;
                    case 'tab-announcements': fetchAndRenderAnnouncements(); break;
                    case 'tab-feedback':
                        document.querySelector('.sub-tab-btn[data-sub-tab="#approved-list-content"]').click();
                        fetchApprovedFeedback();
                        fetchPendingFeedback();
                        break;
                    case 'tab-qa':
                        fetchFaqCategories().then(renderFaqCategoryBtns).then(fetchAndRenderFaqs);
                        break;
                }
            });
        });
        const subTabs = document.querySelectorAll('.sub-tab-btn');
        const subContents = document.querySelectorAll('.sub-tab-content');
        subTabs.forEach(tab => {
            tab.addEventListener('click', () => {
                subTabs.forEach(t => t.classList.remove('active'));
                subContents.forEach(c => c.classList.remove('active'));
                tab.classList.add('active');
                const activeSubContent = document.querySelector(tab.dataset.subTab);
                if (activeSubContent) activeSubContent.classList.add('active');
            });
        });
    }
    function showDetailModal(feedback) {
        const body = document.getElementById('view-modal-body');
        body.textContent = `
    【真實姓名】${feedback.realName || '(未填)'}
    【暱稱】${feedback.nickname}
    【類別】${feedback.category.join(', ')}
    【寄件地址】${feedback.address || '(未填)'}
    【聯絡電話】${feedback.phone || '(未填)'}
    【填寫時間】${feedback.createdAt}
    【回饋內容】
    ${feedback.content}
        `;
        viewModal.classList.add('is-visible');
        const deleteBtn = document.getElementById('delete-feedback-btn');
        deleteBtn.onclick = async () => {
            if (!confirm('確定要刪除這則回饋嗎？此操作無法復原。')) return;
            try {
                await apiFetch(`/api/feedback/${feedback._id}`, { method: 'DELETE' });
                alert('已成功刪除該筆回饋');
                closeDetailModal();
                fetchApprovedFeedback();
            } catch (err) { alert(err.message); }
        };
    }
    function closeDetailModal() {
        viewModal.classList.remove('is-visible');
    }
    viewModal.addEventListener('click', (e) => {
        if (e.target.classList.contains('modal-close-btn') || e.target.id === 'view-modal') {
            closeDetailModal();
        }
    });
    // --- FAQ 管理區 ---
    let faqCategories = [];
    let currentFaqCategory = '';
    async function fetchFaqCategories() {
        faqCategories = await apiFetch('/api/faq/categories');
    }
    function renderFaqCategoryBtns() {
        let html = `<button class="sub-tab-btn faq-category-btn active" data-category="">全部</button>`;
        faqCategories.forEach(cat => {
            html += `<button class="sub-tab-btn faq-category-btn" data-category="${cat}">${cat}</button>`;
        });
        faqCategoryBtnsDiv.innerHTML = html;
        faqCategoryBtnsDiv.querySelectorAll('.faq-category-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                currentFaqCategory = btn.dataset.category;
                faqCategoryBtnsDiv.querySelector('.active').classList.remove('active');
                btn.classList.add('active');
                fetchAndRenderFaqs();
            });
        });
    }
    async function fetchAndRenderFaqs() {
        let url = '/api/faq' + (currentFaqCategory ? `?category=${encodeURIComponent(currentFaqCategory)}` : '');
        try {
            const faqs = await apiFetch(url);
            if (!Array.isArray(faqs) || faqs.length === 0) {
                faqListDiv.innerHTML = `<p>目前沒有問答。</p>`;
                return;
            }
            faqListDiv.innerHTML = faqs.map(faq => `
            <div class="feedback-card" style="border-color:${faq.isPinned ? '#E6BA67' : '#ddd'};">
              <div class="feedback-card__content">
                <b>Q：</b>${faq.question}<br>
                <b>A：</b>${faq.answer}
              </div>
              <div class="feedback-card__actions">
                <button class="btn btn--brown delete-faq-btn" data-id="${faq._id}">刪除</button>
              </div>
            </div>`).join('');
            faqListDiv.querySelectorAll('.delete-faq-btn').forEach(btn => {
                btn.onclick = async () => {
                    if (!confirm('確定要刪除這則問答？')) return;
                    await apiFetch(`/api/faq/${btn.dataset.id}`, { method: 'DELETE' });
                    fetchAndRenderFaqs();
                    fetchFaqCategories().then(renderFaqCategoryBtns);
                };
            });
        } catch (error) { console.error('抓取 FAQ 失敗:', error); }
    }
    addFaqBtn.addEventListener('click', () => {
        faqForm.reset();
        faqModalCategoryBtns.innerHTML = faqCategories.map(cat => `<button type="button" class="btn btn--brown modal-cat-btn" data-cat="${cat}">${cat}</button>`).join('');
        faqModal.classList.add('is-visible');
        faqModalCategoryBtns.querySelectorAll('.modal-cat-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                faqForm.other_category.value = btn.textContent;
                faqModalCategoryBtns.querySelector('.active')?.classList.remove('active');
                btn.classList.add('active');
            });
        });
    });
    faqModal.addEventListener('click', e => {
        if (e.target.classList.contains('modal-close-btn') || e.target.id === 'faq-modal') {
            faqModal.classList.remove('is-visible');
        }
    });
    faqForm.addEventListener('submit', async e => {
        e.preventDefault();
        const formData = {
            question: faqForm.question.value.trim(),
            answer: faqForm.answer.value.trim(),
            category: faqForm.other_category.value.trim(),
            isPinned: faqForm.isPinned.checked
        };
        if (!formData.question || !formData.answer || !formData.category) return alert('請完整填寫');
        if (!/^[\u4e00-\u9fff]+$/.test(formData.category)) return alert('分類只能輸入中文！');
        await apiFetch('/api/faq', {
            method: 'POST',
            body: JSON.stringify(formData)
        });
        faqModal.classList.remove('is-visible');
        fetchAndRenderFaqs();
        fetchFaqCategories().then(renderFaqCategoryBtns);
    });
    // --- 公告管理區 ---
    // --- ↓↓↓ 這是【修正版】的 fetchAndRenderAnnouncements 函式，請複製它 ↓↓↓ ---
    async function fetchAndRenderAnnouncements() {
        try {
            const announcements = await apiFetch('/api/announcements');
            announcementsListDiv.innerHTML = announcements.length === 0 ? '<p>目前沒有任何公告。</p>' :
                announcements.map(item => {
                    // 【關鍵修正】在將資料轉為 JSON 字串後，把所有單引號 ' 替換為安全的 HTML 編碼 &apos;
                    const safeDataString = JSON.stringify(item).replace(/'/g, "&apos;");
                    return `
            <div class="feedback-card" style="border-left: 4px solid ${item.isPinned ? '#C48945' : '#ddd'};">
                <div class="feedback-card__header">
                    <span class="feedback-card__info">${item.date}</span>
                    ${item.isPinned ? '<span style="color: #C48945; font-weight: bold;">置頂</span>' : ''}
                </div>
                <p class="feedback-card__content" style="font-weight: bold; font-size: 1.1em;">${item.title}</p>
                <div class="feedback-card__actions">
                    <button class="btn btn--brown view-announcement-btn" data-id='${safeDataString}'>查看</button>
                </div>
            </div>`;
                }).join('');
            announcementsListDiv.querySelectorAll('.view-announcement-btn').forEach(btn => {
                btn.addEventListener('click', () => showAnnouncementDetailModal(JSON.parse(btn.dataset.id)));
            });
        } catch (error) { console.error('抓取公告失敗:', error); }
    }
    // --- ↑↑↑ 複製到這裡為止 ↑↑↑ ---
    // --- ↓↓↓ 這是【最終優化版】的 showAnnouncementDetailModal 函式，請複製它 ↓↓↓ ---
    function showAnnouncementDetailModal(item) {
        // 採納建議 1：如果標題或內容為空，提供預設文字
        const safeTitle = (item.title || '無標題').replace(/\n/g, '<br>');
        const parsedContent = parseContentForLinks(item.content);
        const safeContent = (parsedContent || '無內容').replace(/\n/g, '<br>');
        const modalHtml = `
        <div style="line-height: 1.8;">
            <p><b>【公告日期】</b> ${item.date || '無'}</p>
            <p><b>【是否置頂】</b> ${item.isPinned ? '是' : '否'}</p>
            <p><b>【標題】</b><br>${safeTitle}</p>
            <hr style="margin: 15px 0;">
            <p><b>【內文】</b></p>
            <div>${safeContent}</div>
        </div>
    `;
        announcementViewModalBody.innerHTML = modalHtml;
        // 採納建議 4：為刪除操作增加 try/catch 和成功/失敗提示
        deleteAnnouncementFromModalBtn.onclick = async () => {
            if (!confirm('確定要永久刪除這則公告嗎？')) return;
            try {
                await apiFetch(`/api/announcements/${item._id}`, { method: 'DELETE' });
                alert('公告已成功刪除！'); // 成功提示
                closeAnnouncementDetailModal();
                fetchAndRenderAnnouncements();
            } catch (error) {
                alert(`刪除失敗：${error.message}`); // 失敗提示
            }
        };
        // --- ↑↑↑ 複製到這裡為止 ↑↑↑ ---
        announcementViewModal.classList.add('is-visible');
    }
    function closeAnnouncementDetailModal() {
        announcementViewModal.classList.remove('is-visible');
    }
    addAnnouncementBtn.addEventListener('click', () => {
        announcementFormTitle.textContent = '新增公告';
        announcementForm.reset();
        announcementFormModal.classList.add('is-visible');
    });
    announcementForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const formData = {
            date: announcementForm.date.value.trim(),
            title: announcementForm.title.value.trim(),
            content: announcementForm.content.value.trim(),
            isPinned: announcementForm.isPinned.checked
        };
        if (!formData.date || !formData.title || !formData.content) return alert('所有欄位皆為必填。');
        await apiFetch('/api/announcements', {
            method: 'POST',
            body: JSON.stringify(formData)
        });
        announcementFormModal.classList.remove('is-visible');
        fetchAndRenderAnnouncements();
    });
    announcementFormModal.addEventListener('click', (e) => {
        if (e.target.classList.contains('modal-close-btn') || e.target.id === 'announcement-modal') {
            announcementFormModal.classList.remove('is-visible');
        }
    });
    announcementViewModal.addEventListener('click', (e) => {
        if (e.target.classList.contains('modal-close-btn') || e.target.id === 'announcement-view-modal') {
            closeAnnouncementDetailModal();
        }
    });
    // --- 啟動！ ---
    checkSession();
});
