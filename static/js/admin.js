document.addEventListener('DOMContentLoaded', () => {

    /* =========================================
       1. 核心工具函式 (API Fetcher)
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
       2. 初始化與登入系統
       ========================================= */
    const loginWrapper = document.getElementById('login-wrapper');
    const adminContent = document.getElementById('admin-content');
    const loginForm = document.getElementById('login-form');
    const logoutBtn = document.getElementById('logout-btn');
    const pageTitleDisplay = document.getElementById('page-title-display');
    
    // 側邊選單 DOM
    const sidebar = document.getElementById('admin-sidebar');
    const sidebarToggle = document.getElementById('sidebar-toggle');
    const closeSidebarBtn = document.getElementById('close-sidebar');
    const sidebarOverlay = document.getElementById('sidebar-overlay');

    // 檢查登入狀態
    async function checkSession() {
        try {
            const data = await fetch('/api/session_check').then(res => res.json());
            if (data.logged_in) showAdminContent();
            else showLogin();
        } catch(e) { showLogin(); }
    }

    function showLogin() {
        loginWrapper.style.display = 'flex';
        adminContent.style.display = 'none';
        if(loginForm) loginForm.reset();
    }

    function showAdminContent() {
        loginWrapper.style.display = 'none';
        adminContent.style.display = 'block';
        if (!adminContent.dataset.initialized) {
            setupNavigation();
            // 預設載入第一個分頁
            const firstNav = document.querySelector('.nav-item[data-tab="tab-feedback"]');
            if(firstNav) firstNav.click();
            adminContent.dataset.initialized = 'true';
        }
    }

    // 登入表單提交
    if(loginForm) {
        loginForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const pwdInput = document.getElementById('admin-password');
            const errDisplay = document.getElementById('login-error');
            errDisplay.textContent = '';
            
            try {
                const res = await fetch('/api/login', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ password: pwdInput.value })
                });
                const data = await res.json();
                if (data.success) window.location.reload();
                else errDisplay.textContent = data.message || '登入失敗';
            } catch (err) { errDisplay.textContent = '連線錯誤'; }
        });
    }

    // 登出
    if(logoutBtn) {
        logoutBtn.addEventListener('click', async () => {
            await apiFetch('/api/logout', { method: 'POST' });
            showLogin();
        });
    }

    /* =========================================
       3. 側邊選單導覽邏輯
       ========================================= */
    function setupNavigation() {
        const navItems = document.querySelectorAll('.nav-item');
        const tabContents = document.querySelectorAll('.tab-content');

        navItems.forEach(item => {
            item.addEventListener('click', () => {
                // UI 切換
                navItems.forEach(n => n.classList.remove('active'));
                item.classList.add('active');
                
                const targetId = item.dataset.tab;
                tabContents.forEach(c => c.classList.remove('active'));
                const targetContent = document.getElementById(targetId);
                if(targetContent) targetContent.classList.add('active');

                // 更新標題
                if(pageTitleDisplay) pageTitleDisplay.textContent = item.dataset.title || item.textContent;
                
                // 手機版自動收合
                if (window.innerWidth <= 768) closeSidebar();

                // 根據分頁載入資料
                switch (targetId) {
                    case 'tab-feedback':
                        fetchPendingFeedback();
                        fetchApprovedFeedback();
                        break;
                    case 'tab-products': 
                        fetchAndRenderProducts(); 
                        break;
                    case 'tab-fund': 
                        fetchFundSettings(); 
                        break;
                    case 'tab-announcements': 
                        fetchAndRenderAnnouncements(); 
                        break;
                    case 'tab-qa': 
                        fetchFaqCategories().then(renderFaqCategoryBtns).then(fetchAndRenderFaqs); 
                        break;
                    case 'tab-links': 
                        fetchLinks(); 
                        break;
                }
            });
        });
    }

    // 側邊欄開關控制
    function openSidebar() { sidebar.classList.add('open'); sidebarOverlay.classList.add('active'); }
    function closeSidebar() { sidebar.classList.remove('open'); sidebarOverlay.classList.remove('active'); }
    
    if(sidebarToggle) sidebarToggle.addEventListener('click', openSidebar);
    if(closeSidebarBtn) closeSidebarBtn.addEventListener('click', closeSidebar);
    if(sidebarOverlay) sidebarOverlay.addEventListener('click', closeSidebar);

    /* =========================================
       4. 信徒回饋管理 (核心功能：垂直佈局)
       ========================================= */
    const pendingListContainer = document.getElementById('pending-feedback-list');
    const approvedListContainer = document.getElementById('approved-feedback-list');
    const feedbackEditModal = document.getElementById('feedback-edit-modal');
    const feedbackEditForm = document.getElementById('feedback-edit-form');

    // 匯出按鈕
    const exportBtn = document.getElementById('export-btn');
    if(exportBtn) {
        exportBtn.addEventListener('click', async () => {
            if(!confirm('確定匯出未寄送清單？\n\n系統將下載檔案並自動將這些資料標記為「已寄出」。')) return;
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
                
                alert('匯出成功！');
                fetchApprovedFeedback();
            } catch(e) { alert(e.message); }
        });
    }

    // 全部標記已讀按鈕
    const markAllBtn = document.getElementById('mark-all-btn');
    if(markAllBtn) {
        markAllBtn.addEventListener('click', async () => {
            if(!confirm('確定將所有已刊登回饋標記為已讀？')) return;
            try {
                await apiFetch('/api/feedback/mark-all-approved', { method:'PUT' });
                fetchApprovedFeedback();
            } catch(e) { alert('操作失敗'); }
        });
    }

    // 載入待審核列表
    async function fetchPendingFeedback() {
        if(!pendingListContainer) return;
        try {
            const data = await apiFetch('/api/feedback/pending');
            if (data.length === 0) {
                pendingListContainer.innerHTML = '<p style="text-align:center; color:#999; padding:20px;">🎉 目前沒有待審核資料</p>';
                return;
            }
            pendingListContainer.innerHTML = data.map(item => renderFeedbackCard(item, 'pending')).join('');
            bindFeedbackButtons(pendingListContainer);
        } catch(e) { console.error(e); }
    }

    // 載入已刊登列表
    async function fetchApprovedFeedback() {
        if(!approvedListContainer) return;
        try {
            const data = await apiFetch('/api/feedback/approved');
            if (data.length === 0) {
                approvedListContainer.innerHTML = '<p style="text-align:center; color:#999; padding:20px;">尚未有已刊登資料</p>';
                return;
            }
            approvedListContainer.innerHTML = data.map(item => renderFeedbackCard(item, 'approved')).join('');
            bindFeedbackButtons(approvedListContainer);
        } catch(e) { console.error(e); }
    }

    // 渲染回饋卡片 HTML
    function renderFeedbackCard(item, type) {
        const isMarked = item.isMarked ? 'checked' : '';
        // 已刊登區顯示標記勾選框
        const markHtml = (type === 'approved') 
            ? `<label style="cursor:pointer; font-size:14px; display:flex; align-items:center; margin-right:10px;">
                 <input type="checkbox" class="mark-checkbox" data-id="${item._id}" ${isMarked} style="width:16px; height:16px; margin-right:5px;"> 已寄出
               </label>` 
            : '';
        
        let buttonsHtml = '';
        if (type === 'pending') {
            // 待審核區按鈕：編輯、刪除、同意
            buttonsHtml = `
                <button class="btn btn--grey edit-feedback-btn" data-data='${JSON.stringify(item).replace(/'/g, "&apos;")}' style="margin-right:5px;">編輯</button>
                <button class="btn btn--red action-btn" data-action="delete" data-id="${item._id}" style="margin-right:5px;">刪除</button>
                <button class="btn btn--brown action-btn" data-action="approve" data-id="${item._id}">同意刊登</button>
            `;
        } else {
            // 已刊登區按鈕：查看詳細
            buttonsHtml = `<button class="btn btn--brown view-btn" data-data='${JSON.stringify(item).replace(/'/g, "&apos;")}' style="padding:4px 10px; font-size:13px;">查看詳細</button>`;
        }

        return `
            <div class="feedback-card" style="${item.isMarked ? 'background-color:#f0f9eb;' : ''}">
                <div class="feedback-card__header">
                   <span>${item.nickname} / ${Array.isArray(item.category) ? item.category.join(' ') : item.category}</span>
                   <span>${item.createdAt}</span>
                </div>
                <div class="feedback-card__content" style="white-space:pre-wrap; word-break:break-all;">${item.content}</div>
                <div class="feedback-card__actions" style="display:flex; justify-content:flex-end; align-items:center;">
                    ${markHtml}
                    ${buttonsHtml}
                </div>
            </div>`;
    }

    // 綁定回饋卡片按鈕事件
    function bindFeedbackButtons(container) {
        // 編輯
        container.querySelectorAll('.edit-feedback-btn').forEach(btn => {
            btn.onclick = () => showFeedbackEditModal(JSON.parse(btn.dataset.data));
        });
        // 刪除與同意
        container.querySelectorAll('.action-btn').forEach(btn => {
            btn.onclick = async () => {
                const action = btn.dataset.action;
                if(!confirm(`確定要${action === 'approve' ? '同意刊登' : '刪除'}這則回饋嗎？`)) return;
                const url = action === 'approve' ? `/api/feedback/${btn.dataset.id}/approve` : `/api/feedback/${btn.dataset.id}`;
                try {
                    await apiFetch(url, { method: action === 'approve' ? 'PUT' : 'DELETE' });
                    fetchPendingFeedback();
                    fetchApprovedFeedback();
                } catch(e) { alert(e.message); }
            };
        });
        // 標記已讀
        container.querySelectorAll('.mark-checkbox').forEach(chk => {
            chk.onchange = async () => {
                try {
                    await apiFetch(`/api/feedback/${chk.dataset.id}/mark`, { method:'PUT', body:JSON.stringify({isMarked:chk.checked}) });
                    chk.closest('.feedback-card').style.backgroundColor = chk.checked ? '#f0f9eb' : '#fff';
                } catch(e) { 
                    chk.checked = !chk.checked; 
                    alert('標記失敗'); 
                }
            };
        });
        // 查看詳細
        container.querySelectorAll('.view-btn').forEach(btn => {
            btn.onclick = () => {
                const item = JSON.parse(btn.dataset.data);
                const viewModal = document.getElementById('view-modal');
                const viewBody = document.getElementById('view-modal-body');
                
                viewBody.innerHTML = `
                    <p><b>姓名:</b> ${item.realName || ''}</p>
                    <p><b>電話:</b> ${item.phone || ''}</p>
                    <p><b>地址:</b> ${item.address || ''}</p>
                    <p><b>生日:</b> ${item.lunarBirthday || ''} (${item.birthTime || ''})</p>
                    <hr style="margin:10px 0; border:0; border-top:1px solid #ddd;">
                    <p style="white-space:pre-wrap;">${item.content}</p>
                `;
                
                // 綁定詳細頁中的刪除按鈕
                const delBtn = document.getElementById('delete-feedback-btn');
                // 移除舊事件監聽器 (Clone node hack)
                const newDelBtn = delBtn.cloneNode(true);
                delBtn.parentNode.replaceChild(newDelBtn, delBtn);
                
                newDelBtn.onclick = async () => {
                    if(confirm('確定要永久刪除此回饋？')) {
                        await apiFetch(`/api/feedback/${item._id}`, { method:'DELETE' });
                        viewModal.classList.remove('is-visible');
                        fetchApprovedFeedback();
                    }
                };
                viewModal.classList.add('is-visible');
            };
        });
    }

    // 顯示編輯 Modal
    function showFeedbackEditModal(item) {
        if(!feedbackEditForm) return;
        feedbackEditForm.reset();
        feedbackEditForm.feedbackId.value = item._id;
        feedbackEditForm.realName.value = item.realName || '';
        feedbackEditForm.nickname.value = item.nickname || '';
        feedbackEditForm.content.value = item.content || '';
        feedbackEditForm.lunarBirthday.value = item.lunarBirthday || '';
        feedbackEditForm.phone.value = item.phone || '';
        feedbackEditForm.address.value = item.address || '';
        
        // 處理分類與時辰
        let catVal = Array.isArray(item.category) ? item.category[0] : item.category;
        feedbackEditForm.category.value = catVal || '其他';
        feedbackEditForm.birthTime.value = item.birthTime || '吉時 (不知道)';
        
        feedbackEditModal.classList.add('is-visible');
    }

    // 提交編輯
    if(feedbackEditForm) {
        feedbackEditForm.onsubmit = async (e) => {
            e.preventDefault();
            const formData = {
                realName: feedbackEditForm.realName.value,
                nickname: feedbackEditForm.nickname.value,
                category: [feedbackEditForm.category.value],
                content: feedbackEditForm.content.value,
                lunarBirthday: feedbackEditForm.lunarBirthday.value,
                birthTime: feedbackEditForm.birthTime.value,
                phone: feedbackEditForm.phone.value,
                address: feedbackEditForm.address.value
            };
            try {
                await apiFetch(`/api/feedback/${feedbackEditForm.feedbackId.value}`, { method:'PUT', body:JSON.stringify(formData) });
                alert('修改成功！');
                feedbackEditModal.classList.remove('is-visible');
                fetchPendingFeedback();
            } catch (error) { alert('儲存失敗：' + error.message); }
        };
    }

    /* =========================================
       5. 商品管理 (Products)
       ========================================= */
    const productsListDiv = document.getElementById('products-list');
    const addProductBtn = document.getElementById('add-product-btn');
    const productModal = document.getElementById('product-modal');
    const productForm = document.getElementById('product-form');
    const productImageInput = document.getElementById('product-image-input');
    const previewImage = document.getElementById('preview-image');
    const removeImageBtn = document.getElementById('remove-image-btn');
    const imageHiddenInput = productForm ? productForm.querySelector('input[name="image"]') : null;

    // 圖片上傳預覽
    if(productImageInput) {
        productImageInput.onchange = function(e) {
            const file = e.target.files[0];
            if (!file) return;
            if (file.size > 2 * 1024 * 1024) { alert('圖片太大，請小於 2MB'); this.value=''; return; }
            const reader = new FileReader();
            reader.onload = (event) => {
                previewImage.src = event.target.result;
                previewImage.style.display = 'block';
                removeImageBtn.style.display = 'inline-block';
                imageHiddenInput.value = event.target.result;
            };
            reader.readAsDataURL(file);
        };
    }
    if(removeImageBtn) {
        removeImageBtn.onclick = () => {
            productImageInput.value = ''; imageHiddenInput.value = ''; previewImage.src = ''; 
            previewImage.style.display = 'none'; removeImageBtn.style.display = 'none';
        };
    }

    async function fetchAndRenderProducts() {
        if(!productsListDiv) return;
        try {
            const products = await apiFetch('/api/products');
            if(products.length === 0) { productsListDiv.innerHTML = '<p>目前無商品</p>'; return; }
            
            productsListDiv.innerHTML = products.map(p => {
                const imgHtml = p.image ? `<img src="${p.image}" style="width:100%; height:150px; object-fit:cover;">` : `<div style="height:150px; background:#eee; display:flex; align-items:center; justify-content:center; color:#999;">無圖片</div>`;
                return `
                <div class="feedback-card" style="padding:0; overflow:hidden;">
                    ${imgHtml}
                    <div style="padding:15px;">
                        <span style="font-size:12px; color:#999; border:1px solid #ddd; padding:2px 5px; border-radius:4px;">${p.category}</span>
                        <h4 style="margin:5px 0;">${p.name}</h4>
                        <div style="color:var(--main-brown); font-weight:bold;">NT$ ${p.price}</div>
                        <div style="margin-top:10px; display:flex; gap:5px;">
                            <button class="btn btn--brown edit-prod-btn" style="flex:1;" data-data='${JSON.stringify(p).replace(/'/g, "&apos;")}'>編輯</button>
                            <button class="btn btn--red del-prod-btn" style="flex:1;" data-id="${p._id}">刪除</button>
                        </div>
                    </div>
                </div>`;
            }).join('');

            // 綁定商品按鈕
            productsListDiv.querySelectorAll('.del-prod-btn').forEach(b => b.onclick = async () => {
                if(confirm('確定刪除？')) { await apiFetch(`/api/products/${b.dataset.id}`, {method:'DELETE'}); fetchAndRenderProducts(); }
            });
            productsListDiv.querySelectorAll('.edit-prod-btn').forEach(b => b.onclick = () => showProductModal(JSON.parse(b.dataset.data)));
        } catch(e) { console.error(e); }
    }

    function showProductModal(p = null) {
        productForm.reset();
        previewImage.src = ''; previewImage.style.display = 'none'; removeImageBtn.style.display = 'none'; imageHiddenInput.value = '';
        if(p) {
            document.getElementById('product-modal-title').textContent = '編輯商品';
            productForm.productId.value = p._id; productForm.name.value = p.name; productForm.price.value = p.price;
            productForm.category.value = p.category; productForm.description.value = p.description; productForm.isActive.checked = p.isActive;
            if(p.image) { previewImage.src = p.image; previewImage.style.display = 'block'; removeImageBtn.style.display = 'inline-block'; imageHiddenInput.value = p.image; }
        } else {
            document.getElementById('product-modal-title').textContent = '新增商品';
            productForm.productId.value = ''; productForm.isActive.checked = true;
        }
        productModal.classList.add('is-visible');
    }

    if(addProductBtn) addProductBtn.onclick = () => showProductModal(null);
    if(productForm) {
        productForm.onsubmit = async (e) => {
            e.preventDefault();
            const id = productForm.productId.value;
            const data = {
                category: productForm.category.value, name: productForm.name.value, price: productForm.price.value,
                description: productForm.description.value, isActive: productForm.isActive.checked, image: imageHiddenInput.value
            };
            const method = id ? 'PUT' : 'POST';
            const url = id ? `/api/products/${id}` : '/api/products';
            await apiFetch(url, { method, body: JSON.stringify(data) });
            productModal.classList.remove('is-visible');
            fetchAndRenderProducts();
        };
    }

    /* =========================================
       6. 建廟基金 (Fund)
       ========================================= */
    const fundForm = document.getElementById('fund-form');
    async function fetchFundSettings() {
        const data = await apiFetch('/api/fund-settings');
        if(document.getElementById('fund-goal')) {
            document.getElementById('fund-goal').value = data.goal_amount;
            document.getElementById('fund-current').value = data.current_amount;
        }
    }
    if(fundForm) {
        fundForm.onsubmit = async (e) => {
            e.preventDefault();
            await apiFetch('/api/fund-settings', {
                method:'POST',
                body: JSON.stringify({ 
                    goal_amount: document.getElementById('fund-goal').value,
                    current_amount: document.getElementById('fund-current').value 
                })
            });
            alert('設定已更新');
        };
    }

    /* =========================================
       7. 公告管理 (Announcements)
       ========================================= */
    const announcementsListDiv = document.getElementById('announcements-list');
    const addAnnBtn = document.getElementById('add-announcement-btn');
    const annModal = document.getElementById('announcement-modal');
    const annForm = document.getElementById('announcement-form');

    async function fetchAndRenderAnnouncements() {
        if(!announcementsListDiv) return;
        const data = await apiFetch('/api/announcements');
        announcementsListDiv.innerHTML = data.map(a => `
            <div class="feedback-card">
                <div style="font-size:12px; color:#888;">${a.date} ${a.isPinned ? '<span style="color:red">[置頂]</span>' : ''}</div>
                <h4 style="margin:5px 0;">${a.title}</h4>
                <p style="white-space:pre-wrap; color:#555;">${a.content}</p>
                <div style="text-align:right;"><button class="btn btn--red del-ann-btn" data-id="${a._id}">刪除</button></div>
            </div>`).join('');
        
        announcementsListDiv.querySelectorAll('.del-ann-btn').forEach(b => b.onclick = async () => {
            if(confirm('確定刪除？')) { await apiFetch(`/api/announcements/${b.dataset.id}`, {method:'DELETE'}); fetchAndRenderAnnouncements(); }
        });
    }
    if(addAnnBtn) addAnnBtn.onclick = () => { annForm.reset(); annModal.classList.add('is-visible'); };
    if(annForm) {
        annForm.onsubmit = async (e) => {
            e.preventDefault();
            await apiFetch('/api/announcements', {
                method:'POST',
                body: JSON.stringify({
                    date: annForm.date.value, title: annForm.title.value,
                    content: annForm.content.value, isPinned: annForm.isPinned.checked
                })
            });
            annModal.classList.remove('is-visible');
            fetchAndRenderAnnouncements();
        };
    }

    /* =========================================
       8. FAQ 管理
       ========================================= */
    const faqListDiv = document.getElementById('faq-list');
    const addFaqBtn = document.getElementById('add-faq-btn');
    const faqModal = document.getElementById('faq-modal');
    const faqForm = document.getElementById('faq-form');
    const faqCategoryDiv = document.getElementById('faq-modal-category-btns');

    async function fetchFaqCategories() {
        try { return await apiFetch('/api/faq/categories'); } catch(e) { return []; }
    }
    function renderFaqCategoryBtns(cats) {
        if(faqCategoryDiv) {
            faqCategoryDiv.innerHTML = cats.map(c => 
                `<button type="button" class="btn" style="background:#eee; color:#333; font-size:12px; padding:4px 8px;" onclick="this.form.other_category.value='${c}'">${c}</button>`
            ).join('');
        }
    }
    async function fetchAndRenderFaqs() {
        if(!faqListDiv) return;
        const faqs = await apiFetch('/api/faq');
        faqListDiv.innerHTML = faqs.map(f => `
            <div class="feedback-card" style="position:relative;">
                <div style="margin-bottom:5px;">
                    <span style="background:#C48945; color:#fff; font-size:12px; padding:2px 6px; border-radius:4px;">${f.category}</span>
                    ${f.isPinned ? '<span style="color:red; font-size:12px;">[置頂]</span>' : ''}
                </div>
                <div style="font-weight:bold;">Q: ${f.question}</div>
                <div style="white-space:pre-line; color:#555;">A: ${f.answer}</div>
                <button class="btn btn--red del-faq-btn" data-id="${f._id}" style="position:absolute; top:15px; right:15px; padding:4px 8px; font-size:12px;">刪除</button>
            </div>`).join('');
        
        faqListDiv.querySelectorAll('.del-faq-btn').forEach(b => b.onclick = async () => {
            if(confirm('確定刪除？')) { 
                await apiFetch(`/api/faq/${b.dataset.id}`, {method:'DELETE'}); 
                fetchFaqCategories().then(renderFaqCategoryBtns).then(fetchAndRenderFaqs); 
            }
        });
    }
    if(addFaqBtn) addFaqBtn.onclick = async () => {
        const cats = await fetchFaqCategories();
        renderFaqCategoryBtns(cats);
        faqForm.reset(); faqModal.classList.add('is-visible');
    };
    if(faqForm) {
        faqForm.onsubmit = async (e) => {
            e.preventDefault();
            const cat = faqForm.other_category.value.trim();
            if(!cat) { alert('請輸入分類'); return; }
            await apiFetch('/api/faq', {
                method:'POST',
                body: JSON.stringify({
                    question: faqForm.question.value, answer: faqForm.answer.value,
                    category: cat, isPinned: faqForm.isPinned.checked
                })
            });
            faqModal.classList.remove('is-visible');
            fetchFaqCategories().then(renderFaqCategoryBtns).then(fetchAndRenderFaqs);
        };
    }

    /* =========================================
       9. 連結管理 (Links)
       ========================================= */
    const linksListDiv = document.getElementById('links-list');
    async function fetchLinks() {
        if(!linksListDiv) return;
        const links = await apiFetch('/api/links');
        linksListDiv.innerHTML = links.map(l => `
            <div style="display:flex; gap:10px; margin-bottom:10px; align-items:center;">
                <span style="font-weight:bold; min-width:80px;">${l.name}</span>
                <input type="text" value="${l.url}" readonly style="flex:1; padding:5px; border:1px solid #ddd; background:#eee;">
                <button class="btn btn--brown edit-link-btn" data-id="${l._id}" data-url="${l.url}">修改</button>
            </div>`).join('');
        
        linksListDiv.querySelectorAll('.edit-link-btn').forEach(b => b.onclick = async () => {
            const newUrl = prompt('請輸入新網址', b.dataset.url);
            if(newUrl) {
                await apiFetch(`/api/links/${b.dataset.id}`, { method:'PUT', body:JSON.stringify({url:newUrl}) });
                fetchLinks();
            }
        });
    }

    // Modal 通用關閉事件
    document.querySelectorAll('.admin-modal-overlay').forEach(modal => {
        modal.addEventListener('click', (e) => {
            if (e.target.classList.contains('modal-close-btn') || e.target === modal) {
                modal.classList.remove('is-visible');
            }
        });
    });

    // 啟動檢查
    checkSession();
});