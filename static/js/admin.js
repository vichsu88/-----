document.addEventListener('DOMContentLoaded', () => {
    // --- DOM 元素宣告 (新增回饋管理相關元素) ---
    const loginContainer = document.getElementById('login-container');
    const adminContent = document.getElementById('admin-content');
    const loginForm = document.getElementById('login-form');
    const passwordInput = document.getElementById('admin-password');
    const loginError = document.getElementById('login-error');
    const logoutBtn = document.getElementById('logout-btn');
    
    // 連結管理
    const linksListDiv = document.getElementById('links-list');

    // 回饋管理
    const pendingListContainer = document.getElementById('pending-feedback-list');
    const approvedListContainer = document.getElementById('approved-feedback-list');
    const markAllBtn = document.getElementById('mark-all-btn');
    const exportBtn = document.getElementById('export-btn');
    const exportOutputContainer = document.getElementById('export-output-container');
    const exportTextarea = document.getElementById('export-output');


    // --- 函式定義 ---

    // 登入/登出/Session檢查
    async function checkSession() {
        const response = await fetch('/api/session_check');
        const data = await response.json();
        if (data.logged_in) {
            showAdminContent();
        } else {
            showLogin();
        }
    }

    loginForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        loginError.textContent = '';
        const response = await fetch('/api/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ password: passwordInput.value })
        });
        const data = await response.json();
        if (data.success) {
            showAdminContent();
        } else {
            loginError.textContent = data.message || '登入失敗';
        }
    });

    logoutBtn.addEventListener('click', async () => {
        await fetch('/api/logout', { method: 'POST' });
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
        fetchLinks(); 
        // 登入後預設載入回饋列表
        fetchApprovedFeedback();
        fetchPendingFeedback();
    }

    // 連結管理
    async function fetchLinks() {
        try {
            const response = await fetch('/api/links');
            if (!response.ok) throw new Error('獲取連結失敗');
            const links = await response.json();
            linksListDiv.innerHTML = ''; 
            links.forEach(link => {
                const item = document.createElement('div');
                item.className = 'link-item';
                item.innerHTML = `
                    <span class="link-name-display">${link.name}</span>
                    <input class="link-url-display" type="text" value="${link.url}" readonly>
                    <button class="edit-btn btn" data-id="${link._id}">修改</button>
                `;
                linksListDiv.appendChild(item);
            });
        } catch (error) { console.error('Error fetching links:', error); }
    }
    
    linksListDiv.addEventListener('click', async function(event) {
        if (event.target.classList.contains('edit-btn')) {
            const target = event.target;
            const id = target.dataset.id;
            const inputField = target.closest('.link-item').querySelector('input[type="text"]');
            const currentUrl = inputField.value;
            const newUrl = prompt('請輸入新的連結網址：', currentUrl);
            if (newUrl === null || newUrl.trim() === '') return;
            try {
                const response = await fetch(`/api/links/${id}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ url: newUrl })
                });
                if (!response.ok) throw new Error('更新失敗');
                fetchLinks();
            } catch (error) { console.error('Error updating link:', error); }
        }
    });

    // --- ↓↓↓ 全新：回饋管理相關函式 ↓↓↓ ---

    // 獲取並渲染「待審核」列表
    async function fetchPendingFeedback() {
        try {
            const response = await fetch('/api/feedback/pending');
            if (!response.ok) throw new Error('讀取待審核資料失敗');
            const data = await response.json();
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
        } catch (error) { console.error('Error fetching pending feedback:', error); }
    }
    
    // 獲取並渲染「已審核」列表
    async function fetchApprovedFeedback() {
        try {
            const response = await fetch('/api/feedback/approved');
            if (!response.ok) throw new Error('讀取已審核資料失敗');
            const data = await response.json();
            approvedListContainer.innerHTML = '';
             if (data.length === 0) {
                approvedListContainer.innerHTML = '<p>目前沒有已審核的回饋。</p>';
                return;
            }
            data.forEach(item => {
                const card = document.createElement('div');
                card.className = 'feedback-card';
                const isMarked = item.isMarked;
                card.innerHTML = `
                    <div class="feedback-card__header">
                        <span class="feedback-card__info"><span class="nickname">${item.nickname}</span> / ${item.category.join(', ')}</span>
                        <span>${item.createdAt}</span>
                    </div>
                    <p class="feedback-card__content">${item.content}</p>
                    <div class="feedback-card__actions">
                        <button class="btn mark-feedback-btn" data-id="${item._id}" data-marked="${isMarked}" style="background-color: ${isMarked ? '#28a745' : '#6c757d'}">
                            ${isMarked ? '✓ 已標記' : '標記'}
                        </button>
                    </div>
                `;
                approvedListContainer.appendChild(card);
            });
        } catch (error) { console.error('Error fetching approved feedback:', error); }
    }

    // 處理所有回饋相關的按鈕點擊
    adminContent.addEventListener('click', async (e) => {
        const target = e.target;
        const id = target.dataset.id;

        if (target.classList.contains('approve-feedback-btn')) {
            if (!confirm('確定要同意刊登這則回饋嗎？')) return;
            await fetch(`/api/feedback/${id}/approve`, { method: 'PUT' });
            fetchPendingFeedback(); 
            fetchApprovedFeedback();
        }

        if (target.classList.contains('delete-feedback-btn')) {
             if (!confirm('確定要永久刪除這則回饋嗎？')) return;
             await fetch(`/api/feedback/${id}`, { method: 'DELETE' });
             fetchPendingFeedback();
        }

        if (target.classList.contains('mark-feedback-btn')) {
            const isMarked = target.dataset.marked === 'true';
            await fetch(`/api/feedback/${id}/mark`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ isMarked: !isMarked })
            });
            fetchApprovedFeedback();
        }
    });
    
    // 全部標記按鈕
    markAllBtn.addEventListener('click', async () => {
        if (!confirm('確定要將所有已審核的回饋都標記為已處理嗎？')) return;
        await fetch('/api/feedback/mark-all-approved', { method: 'PUT' });
        fetchApprovedFeedback();
    });

    // 輸出寄件資訊按鈕
    exportBtn.addEventListener('click', async () => {
        const response = await fetch('/api/feedback/export-unmarked');
        const textData = await response.text();
        exportOutputContainer.style.display = 'block';
        exportTextarea.value = textData;
    });

    // --- 主頁籤與子頁籤切換邏輯 ---
    function setupTabs() {
        // 主頁籤
        const mainTabs = document.querySelectorAll('.tab-btn');
        const mainContents = document.querySelectorAll('.tab-content');
        mainTabs.forEach(tab => {
            tab.addEventListener('click', () => {
                mainTabs.forEach(t => t.classList.remove('active'));
                mainContents.forEach(c => c.classList.remove('active'));
                tab.classList.add('active');
                const activeContent = document.getElementById(tab.dataset.tab);
                if(activeContent) activeContent.classList.add('active');
                
                if (tab.dataset.tab === 'tab-feedback') {
                    // 確保預設顯示第一個子頁籤
                    document.querySelector('.sub-tab-btn[data-sub-tab="#approved-list-content"]').click();
                    fetchApprovedFeedback();
                    fetchPendingFeedback();
                } else if (tab.dataset.tab === 'tab-links') {
                    fetchLinks();
                }
            });
        });

        // 子頁籤
        const subTabs = document.querySelectorAll('.sub-tab-btn');
        const subContents = document.querySelectorAll('.sub-tab-content');
        subTabs.forEach(tab => {
            tab.addEventListener('click', () => {
                subTabs.forEach(t => t.classList.remove('active'));
                subContents.forEach(c => c.classList.remove('active'));
                tab.classList.add('active');
                const activeSubContent = document.querySelector(tab.dataset.subTab);
                if(activeSubContent) activeSubContent.classList.add('active');
            });
        });
    }

    // --- 啟動！ ---
    checkSession();
    setupTabs();
});