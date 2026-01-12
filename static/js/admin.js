document.addEventListener('DOMContentLoaded', () => {

    /* =========================================
       1. 工具函式
       ========================================= */
    const getCsrfToken = () => {
        const meta = document.querySelector('meta[name="csrf-token"]');
        return meta ? meta.getAttribute('content') : '';
    };

    async function apiFetch(url, options = {}) {
        const hasBody = !!options.body;
        const headers = {
            ...(hasBody && { 'Content-Type': 'application/json' }),
            'X-CSRFToken': getCsrfToken(),
            ...(options.headers || {})
        };
        try {
            const response = await fetch(url, { ...options, credentials: 'include', headers });
            if (!response.ok) {
                const errorText = await response.text();
                let errorMessage = errorText;
                try {
                    const errorJson = JSON.parse(errorText);
                    errorMessage = errorJson.error || errorJson.message || errorText;
                } catch (e) {}
                throw new Error(errorMessage || `請求失敗: ${response.status}`);
            }
            const contentType = response.headers.get('Content-Type') || '';
            if (contentType.includes('application/json')) return response.json();
            return response.text();
        } catch (error) {
            console.error(`API Error (${url}):`, error);
            throw error;
        }
    }

    /* =========================================
       2. 初始化與登入
       ========================================= */
    const loginWrapper = document.getElementById('login-wrapper');
    const adminContent = document.getElementById('admin-content');
    const loginForm = document.getElementById('login-form');
    const logoutBtn = document.getElementById('logout-btn');
    const pageTitleDisplay = document.getElementById('page-title-display');
    const sidebar = document.getElementById('admin-sidebar');
    const sidebarToggle = document.getElementById('sidebar-toggle');
    const closeSidebarBtn = document.getElementById('close-sidebar');
    const sidebarOverlay = document.getElementById('sidebar-overlay');

    async function checkSession() {
        try {
            const data = await fetch('/api/session_check').then(res => res.json());
            if (data.logged_in) showAdminContent();
            else showLogin();
        } catch(e) { showLogin(); }
    }
    function showLogin() { loginWrapper.style.display = 'flex'; adminContent.style.display = 'none'; }
    function showAdminContent() {
        loginWrapper.style.display = 'none';
        adminContent.style.display = 'block';
        if (!adminContent.dataset.initialized) {
            setupNavigation();
            const firstNav = document.querySelector('.nav-item[data-tab="tab-feedback"]');
            if(firstNav) firstNav.click();
            adminContent.dataset.initialized = 'true';
        }
    }

    /* =========================================
       3. 側邊選單導覽 (垂直版優化)
       ========================================= */
    function setupNavigation() {
        const navItems = document.querySelectorAll('.nav-item');
        const tabContents = document.querySelectorAll('.tab-content');

        navItems.forEach(item => {
            item.addEventListener('click', () => {
                navItems.forEach(n => n.classList.remove('active'));
                item.classList.add('active');
                const targetId = item.dataset.tab;
                tabContents.forEach(c => c.classList.remove('active'));
                document.getElementById(targetId).classList.add('active');
                if(pageTitleDisplay) pageTitleDisplay.textContent = item.dataset.title;
                
                if (window.innerWidth <= 768) closeSidebar();

                switch (targetId) {
                    case 'tab-feedback':
                        fetchPendingFeedback();
                        fetchApprovedFeedback();
                        break;
                    case 'tab-products': fetchAndRenderProducts(); break;
                    case 'tab-fund': fetchFundSettings(); break;
                    case 'tab-announcements': fetchAndRenderAnnouncements(); break;
                    case 'tab-qa': fetchFaqCategories().then(renderFaqCategoryBtns).then(fetchAndRenderFaqs); break;
                    case 'tab-links': fetchLinks(); break;
                }
            });
        });
    }

    // 側邊欄控制
    if(sidebarToggle) sidebarToggle.onclick = () => { sidebar.classList.add('open'); sidebarOverlay.classList.add('active'); };
    if(closeSidebarBtn) closeSidebarBtn.onclick = closeSidebar;
    if(sidebarOverlay) sidebarOverlay.onclick = closeSidebar;
    function closeSidebar() { sidebar.classList.remove('open'); sidebarOverlay.classList.remove('active'); }

    loginForm.onsubmit = async (e) => {
        e.preventDefault();
        try {
            const res = await fetch('/api/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ password: document.getElementById('admin-password').value })
            });
            const data = await res.json();
            if (data.success) window.location.reload();
            else document.getElementById('login-error').textContent = data.message;
        } catch (err) { alert('登入出錯'); }
    };
    logoutBtn.onclick = async () => { await apiFetch('/api/logout', { method: 'POST' }); showLogin(); };

    /* =========================================
       7. 信徒回饋管理 (垂直版：待審核在上，已刊登在下)
       ========================================= */
    const pendingListContainer = document.getElementById('pending-feedback-list');
    const approvedListContainer = document.getElementById('approved-feedback-list');
    const feedbackEditModal = document.getElementById('feedback-edit-modal');
    const feedbackEditForm = document.getElementById('feedback-edit-form');

    // 匯出按鈕監聽
    document.getElementById('export-btn').addEventListener('click', async () => {
        if(!confirm('確定匯出未寄送清單？匯出後將自動標記為「已寄出」。')) return;
        try {
            const response = await fetch('/api/feedback/download-unmarked', {
                method: 'POST',
                headers: { 'X-CSRFToken': getCsrfToken() }
            });
            if (response.status === 404) { alert('目前沒有新的待寄送資料'); return; }
            if (!response.ok) throw new Error('匯出失敗');
            const blob = await response.blob();
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `寄件清單_${new Date().toISOString().slice(0,10)}.txt`;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            fetchApprovedFeedback();
        } catch(e) { alert(e.message); }
    });

    // 全部標記按鈕監聽
    document.getElementById('mark-all-btn').addEventListener('click', async () => {
        if(!confirm('確定全部標記為已讀？')) return;
        try {
            await apiFetch('/api/feedback/mark-all-approved', { method:'PUT' });
            fetchApprovedFeedback();
        } catch(e) { alert('操作失敗'); }
    });

    async function fetchPendingFeedback() {
        const data = await apiFetch('/api/feedback/pending');
        pendingListContainer.innerHTML = data.length ? data.map(item => renderFeedbackCard(item, 'pending')).join('') : '<p style="text-align:center; color:#999; padding:20px;">目前無待審核資料</p>';
        bindFeedbackButtons(pendingListContainer);
    }
    async function fetchApprovedFeedback() {
        const data = await apiFetch('/api/feedback/approved');
        approvedListContainer.innerHTML = data.length ? data.map(item => renderFeedbackCard(item, 'approved')).join('') : '<p style="text-align:center; color:#999; padding:20px;">目前無已刊登資料</p>';
        bindFeedbackButtons(approvedListContainer);
    }

    function renderFeedbackCard(item, type) {
        const isMarked = item.isMarked ? 'checked' : '';
        const markHtml = (type === 'approved') ? `<label style="cursor:pointer; font-size:14px;"><input type="checkbox" class="mark-checkbox" data-id="${item._id}" ${isMarked}> 已寄出</label>` : '';
        const buttonsHtml = (type === 'pending') 
            ? `<button class="btn btn--grey edit-feedback-btn" data-data='${JSON.stringify(item).replace(/'/g, "&apos;")}'>編輯</button>
               <button class="btn btn--red action-btn" data-action="delete" data-id="${item._id}">刪除</button>
               <button class="btn btn--brown action-btn" data-action="approve" data-id="${item._id}">同意刊登</button>`
            : `<button class="btn btn--brown view-btn" data-data='${JSON.stringify(item).replace(/'/g, "&apos;")}'>查看詳細</button>`;

        return `
            <div class="feedback-card" style="${item.isMarked ? 'background-color:#f0f9eb;' : ''}">
                <div class="feedback-card__header"><span>${item.nickname} / ${item.category}</span><span>${item.createdAt}</span></div>
                <div class="feedback-card__content" style="white-space:pre-wrap; word-break:break-all;">${item.content}</div>
                <div class="feedback-card__actions">${markHtml}${buttonsHtml}</div>
            </div>`;
    }

    function bindFeedbackButtons(container) {
        container.querySelectorAll('.edit-feedback-btn').forEach(btn => {
            btn.onclick = () => showFeedbackEditModal(JSON.parse(btn.dataset.data));
        });
        container.querySelectorAll('.action-btn').forEach(btn => {
            btn.onclick = async () => {
                const action = btn.dataset.action;
                if(!confirm(`確定執行此動作？`)) return;
                const url = action === 'approve' ? `/api/feedback/${btn.dataset.id}/approve` : `/api/feedback/${btn.dataset.id}`;
                await apiFetch(url, { method: action === 'approve' ? 'PUT' : 'DELETE' });
                fetchPendingFeedback(); fetchApprovedFeedback();
            };
        });
        container.querySelectorAll('.mark-checkbox').forEach(chk => {
            chk.onchange = async () => {
                await apiFetch(`/api/feedback/${chk.dataset.id}/mark`, { method:'PUT', body:JSON.stringify({isMarked:chk.checked}) });
                chk.closest('.feedback-card').style.backgroundColor = chk.checked ? '#f0f9eb' : '#fff';
            };
        });
        container.querySelectorAll('.view-btn').forEach(btn => {
            btn.onclick = () => {
                const item = JSON.parse(btn.dataset.data);
                document.getElementById('view-modal-body').innerHTML = `
                    <p><b>姓名:</b> ${item.realName}</p><p><b>電話:</b> ${item.phone}</p><p><b>地址:</b> ${item.address}</p>
                    <p><b>生日:</b> ${item.lunarBirthday || ''} (${item.birthTime || ''})</p><hr><p style="white-space:pre-wrap;">${item.content}</p>`;
                document.getElementById('view-modal').classList.add('is-visible');
            };
        });
    }

    function showFeedbackEditModal(item) {
        feedbackEditForm.reset();
        feedbackEditForm.feedbackId.value = item._id;
        feedbackEditForm.realName.value = item.realName || '';
        feedbackEditForm.nickname.value = item.nickname || '';
        feedbackEditForm.content.value = item.content || '';
        feedbackEditForm.lunarBirthday.value = item.lunarBirthday || '';
        feedbackEditForm.phone.value = item.phone || '';
        feedbackEditForm.address.value = item.address || '';
        feedbackEditForm.category.value = Array.isArray(item.category) ? item.category[0] : item.category;
        feedbackEditForm.birthTime.value = item.birthTime || '吉時 (不知道)';
        feedbackEditModal.classList.add('is-visible');
    }

    feedbackEditForm.onsubmit = async (e) => {
        e.preventDefault();
        const formData = {
            realName: feedbackEditForm.realName.value, nickname: feedbackEditForm.nickname.value,
            category: [feedbackEditForm.category.value], content: feedbackEditForm.content.value,
            lunarBirthday: feedbackEditForm.lunarBirthday.value, birthTime: feedbackEditForm.birthTime.value,
            phone: feedbackEditForm.phone.value, address: feedbackEditForm.address.value
        };
        await apiFetch(`/api/feedback/${feedbackEditForm.feedbackId.value}`, { method:'PUT', body:JSON.stringify(formData) });
        feedbackEditModal.classList.remove('is-visible');
        fetchPendingFeedback();
    };

    /* =========================================
       其他功能 (簡化載入)
       ========================================= */
    const productForm = document.getElementById('product-form');
    async function fetchAndRenderProducts() {
        const products = await apiFetch('/api/products');
        document.getElementById('products-list').innerHTML = products.map(p => `
            <div class="feedback-card" style="padding:0; overflow:hidden;">
                <img src="${p.image || ''}" style="width:100%; height:150px; object-fit:cover; background:#eee;">
                <div style="padding:10px;">
                    <h4>${p.name}</h4><p>NT$ ${p.price}</p>
                    <button class="btn btn--brown edit-p-btn" data-data='${JSON.stringify(p).replace(/'/g, "&apos;")}'>編輯</button>
                </div>
            </div>`).join('');
    }

    async function fetchFundSettings() {
        const data = await apiFetch('/api/fund-settings');
        document.getElementById('fund-goal').value = data.goal_amount;
        document.getElementById('fund-current').value = data.current_amount;
    }

    async function fetchAndRenderAnnouncements() {
        const data = await apiFetch('/api/announcements');
        document.getElementById('announcements-list').innerHTML = data.map(a => `
            <div class="feedback-card">
                <h4>${a.title}</h4><p style="white-space:pre-wrap;">${a.content}</p>
                <button class="btn btn--red" onclick="deleteAnn('${a._id}')">刪除</button>
            </div>`).join('');
    }

    // Modal 通用關閉
    document.querySelectorAll('.admin-modal-overlay').forEach(modal => {
        modal.onclick = (e) => { if (e.target.classList.contains('modal-close-btn') || e.target === modal) modal.classList.remove('is-visible'); };
    });

    checkSession();
});