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
            const firstNav = document.querySelector('.nav-item[data-tab="tab-feedback"]');
            if(firstNav) firstNav.click();
            adminContent.dataset.initialized = 'true';
        }
    }

    if(loginForm) {
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
    }
    if(logoutBtn) {
        logoutBtn.onclick = async () => { await apiFetch('/api/logout', { method: 'POST' }); showLogin(); };
    }

    /* =========================================
       3. 導覽邏輯
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
                const targetContent = document.getElementById(targetId);
                if(targetContent) targetContent.classList.add('active');

                if(pageTitleDisplay) pageTitleDisplay.textContent = item.dataset.title;
                if(window.innerWidth <= 768) closeSidebar();

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

    function closeSidebar() { sidebar.classList.remove('open'); sidebarOverlay.classList.remove('active'); }
    if(sidebarToggle) sidebarToggle.onclick = () => { sidebar.classList.add('open'); sidebarOverlay.classList.add('active'); };
    if(closeSidebarBtn) closeSidebarBtn.onclick = closeSidebar;
    if(sidebarOverlay) sidebarOverlay.onclick = closeSidebar;

    /* =========================================
       4. 信徒回饋管理 (垂直版)
       ========================================= */
    const pendingListContainer = document.getElementById('pending-feedback-list');
    const approvedListContainer = document.getElementById('approved-feedback-list');
    const feedbackEditModal = document.getElementById('feedback-edit-modal');
    const feedbackEditForm = document.getElementById('feedback-edit-form');

    const exportBtn = document.getElementById('export-btn');
    if(exportBtn) {
        exportBtn.onclick = async () => {
            if(!confirm('匯出並自動標記已寄出？')) return;
            try {
                const res = await fetch('/api/feedback/download-unmarked', { method:'POST', headers:{'X-CSRFToken':getCsrfToken()} });
                if(res.status === 404) { alert('無新資料'); return; }
                const blob = await res.blob();
                const a = document.createElement('a'); a.href = URL.createObjectURL(blob);
                a.download = `寄件_${new Date().toISOString().slice(0,10)}.txt`;
                a.click();
                fetchApprovedFeedback();
            } catch(e) { alert(e.message); }
        };
    }

    const markAllBtn = document.getElementById('mark-all-btn');
    if(markAllBtn) {
        markAllBtn.onclick = async () => {
            if(confirm('全部標記已讀？')) {
                await apiFetch('/api/feedback/mark-all-approved', {method:'PUT'});
                fetchApprovedFeedback();
            }
        };
    }

    async function fetchPendingFeedback() {
        if(!pendingListContainer) return;
        const data = await apiFetch('/api/feedback/pending');
        pendingListContainer.innerHTML = data.length ? data.map(i => renderFeedbackCard(i, 'pending')).join('') : '<p style="text-align:center;color:#999;padding:20px;">無待審核資料</p>';
        bindFeedbackButtons(pendingListContainer);
    }
    async function fetchApprovedFeedback() {
        if(!approvedListContainer) return;
        const data = await apiFetch('/api/feedback/approved');
        approvedListContainer.innerHTML = data.length ? data.map(i => renderFeedbackCard(i, 'approved')).join('') : '<p style="text-align:center;color:#999;padding:20px;">無已刊登資料</p>';
        bindFeedbackButtons(approvedListContainer);
    }

    function renderFeedbackCard(item, type) {
        const isMarked = item.isMarked ? 'checked' : '';
        const markHtml = (type === 'approved') ? `<label style="cursor:pointer;margin-right:10px;"><input type="checkbox" class="mark-checkbox" data-id="${item._id}" ${isMarked}> 已寄出</label>` : '';
        const buttons = (type === 'pending') 
            ? `<button class="btn btn--grey edit-feedback-btn" data-data='${JSON.stringify(item).replace(/'/g, "&apos;")}' style="margin-right:5px;">編輯</button>
               <button class="btn btn--red action-btn" data-action="delete" data-id="${item._id}" style="margin-right:5px;">刪除</button>
               <button class="btn btn--brown action-btn" data-action="approve" data-id="${item._id}">同意</button>`
            : `<button class="btn btn--brown view-btn" data-data='${JSON.stringify(item).replace(/'/g, "&apos;")}' style="font-size:13px;padding:4px 10px;">查看詳細</button>`;

        return `<div class="feedback-card" style="${item.isMarked?'background:#f0f9eb;':''}">
            <div class="feedback-card__header"><span>${item.nickname} / ${item.category}</span><span>${item.createdAt}</span></div>
            <div class="feedback-card__content" style="white-space:pre-wrap;word-break:break-all;">${item.content}</div>
            <div class="feedback-card__actions" style="display:flex;justify-content:flex-end;align-items:center;">${markHtml}${buttons}</div>
        </div>`;
    }

    function bindFeedbackButtons(container) {
        container.querySelectorAll('.edit-feedback-btn').forEach(b => b.onclick = () => showFeedbackEditModal(JSON.parse(b.dataset.data)));
        container.querySelectorAll('.action-btn').forEach(b => b.onclick = async () => {
            if(!confirm('確定執行？')) return;
            const url = b.dataset.action === 'approve' ? `/api/feedback/${b.dataset.id}/approve` : `/api/feedback/${b.dataset.id}`;
            await apiFetch(url, { method: b.dataset.action === 'approve' ? 'PUT' : 'DELETE' });
            fetchPendingFeedback(); fetchApprovedFeedback();
        });
        container.querySelectorAll('.mark-checkbox').forEach(c => c.onchange = async () => {
            await apiFetch(`/api/feedback/${c.dataset.id}/mark`, { method:'PUT', body:JSON.stringify({isMarked:c.checked}) });
            c.closest('.feedback-card').style.background = c.checked ? '#f0f9eb' : '#fff';
        });
        container.querySelectorAll('.view-btn').forEach(b => b.onclick = () => {
            const item = JSON.parse(b.dataset.data);
            document.getElementById('view-modal-body').innerHTML = `
                <p><b>姓名:</b> ${item.realName}</p><p><b>電話:</b> ${item.phone}</p><p><b>地址:</b> ${item.address}</p>
                <p><b>生日:</b> ${item.lunarBirthday} (${item.birthTime})</p><hr><p>${item.content}</p>`;
            
            const delBtn = document.getElementById('delete-feedback-btn');
            const newDelBtn = delBtn.cloneNode(true); // Remove listeners
            delBtn.parentNode.replaceChild(newDelBtn, delBtn);
            newDelBtn.onclick = async () => {
                if(confirm('確定刪除？')) {
                    await apiFetch(`/api/feedback/${item._id}`, {method:'DELETE'});
                    document.getElementById('view-modal').classList.remove('is-visible');
                    fetchApprovedFeedback();
                }
            };
            document.getElementById('view-modal').classList.add('is-visible');
        });
    }

    function showFeedbackEditModal(item) {
        if(!feedbackEditForm) return;
        feedbackEditForm.reset();
        feedbackEditForm.feedbackId.value = item._id;
        feedbackEditForm.realName.value = item.realName; feedbackEditForm.nickname.value = item.nickname;
        feedbackEditForm.content.value = item.content; feedbackEditForm.lunarBirthday.value = item.lunarBirthday;
        feedbackEditForm.phone.value = item.phone; feedbackEditForm.address.value = item.address;
        feedbackEditForm.category.value = Array.isArray(item.category) ? item.category[0] : item.category;
        feedbackEditForm.birthTime.value = item.birthTime || '吉時 (不知道)';
        feedbackEditModal.classList.add('is-visible');
    }

    if(feedbackEditForm) {
        feedbackEditForm.onsubmit = async (e) => {
            e.preventDefault();
            const data = {
                realName: feedbackEditForm.realName.value, nickname: feedbackEditForm.nickname.value,
                category: [feedbackEditForm.category.value], content: feedbackEditForm.content.value,
                lunarBirthday: feedbackEditForm.lunarBirthday.value, birthTime: feedbackEditForm.birthTime.value,
                phone: feedbackEditForm.phone.value, address: feedbackEditForm.address.value
            };
            await apiFetch(`/api/feedback/${feedbackEditForm.feedbackId.value}`, { method:'PUT', body:JSON.stringify(data) });
            feedbackEditModal.classList.remove('is-visible');
            fetchPendingFeedback();
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

    if(productImageInput) {
        productImageInput.onchange = function(e) {
            const file = e.target.files[0];
            if (!file) return;
            if (file.size > 2*1024*1024) { alert('圖片需小於 2MB'); this.value=''; return; }
            const reader = new FileReader();
            reader.onload = (ev) => {
                previewImage.src = ev.target.result;
                previewImage.style.display = 'block';
                removeImageBtn.style.display = 'inline-block';
                imageHiddenInput.value = ev.target.result;
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
        const products = await apiFetch('/api/products');
        if(products.length === 0) { productsListDiv.innerHTML = '<p>無商品</p>'; return; }
        
        productsListDiv.innerHTML = products.map(p => `
            <div class="feedback-card" style="padding:0; overflow:hidden;">
                ${p.image ? `<img src="${p.image}" style="width:100%;height:150px;object-fit:cover;">` : '<div style="height:150px;background:#eee;"></div>'}
                <div style="padding:10px;">
                    <h4>${p.name}</h4><p>NT$ ${p.price}</p>
                    <button class="btn btn--brown edit-prod-btn" data-data='${JSON.stringify(p).replace(/'/g, "&apos;")}' style="width:100%;">編輯</button>
                    <button class="btn btn--red del-prod-btn" data-id="${p._id}" style="width:100%;margin-top:5px;">刪除</button>
                </div>
            </div>`).join('');
        
        productsListDiv.querySelectorAll('.del-prod-btn').forEach(b => b.onclick = async () => {
            if(confirm('刪除？')) { await apiFetch(`/api/products/${b.dataset.id}`, {method:'DELETE'}); fetchAndRenderProducts(); }
        });
        productsListDiv.querySelectorAll('.edit-prod-btn').forEach(b => b.onclick = () => showProductModal(JSON.parse(b.dataset.data)));
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
            await apiFetch(id ? `/api/products/${id}` : '/api/products', { method: id ? 'PUT' : 'POST', body: JSON.stringify(data) });
            productModal.classList.remove('is-visible');
            fetchAndRenderProducts();
        };
    }

    /* =========================================
       6. 其他功能 (公告, FAQ, 連結, 基金)
       ========================================= */
    // 公告
    const announcementsListDiv = document.getElementById('announcements-list');
    const annModal = document.getElementById('announcement-modal');
    const annForm = document.getElementById('announcement-form');
    async function fetchAndRenderAnnouncements() {
        if(!announcementsListDiv) return;
        const data = await apiFetch('/api/announcements');
        announcementsListDiv.innerHTML = data.map(a => `
            <div class="feedback-card">
                <div>${a.date} ${a.isPinned ? '<span style="color:red">[置頂]</span>' : ''}</div>
                <h4>${a.title}</h4><p style="white-space:pre-wrap;">${a.content}</p>
                <button class="btn btn--red" onclick="deleteAnn('${a._id}')">刪除</button>
            </div>`).join('');
    }
    // 為了讓 inline onclick 運作
    window.deleteAnn = async (id) => {
        if(confirm('刪除公告？')) { await apiFetch(`/api/announcements/${id}`, {method:'DELETE'}); fetchAndRenderAnnouncements(); }
    };
    if(document.getElementById('add-announcement-btn')) document.getElementById('add-announcement-btn').onclick = () => { annForm.reset(); annModal.classList.add('is-visible'); };
    if(annForm) annForm.onsubmit = async (e) => {
        e.preventDefault();
        await apiFetch('/api/announcements', { method:'POST', body: JSON.stringify({
            date: annForm.date.value, title: annForm.title.value, content: annForm.content.value, isPinned: annForm.isPinned.checked
        })});
        annModal.classList.remove('is-visible'); fetchAndRenderAnnouncements();
    };

    // FAQ
    const faqListDiv = document.getElementById('faq-list');
    const faqModal = document.getElementById('faq-modal');
    const faqForm = document.getElementById('faq-form');
    async function fetchFaqCategories() { try { return await apiFetch('/api/faq/categories'); } catch(e){return [];} }
    function renderFaqCategoryBtns(cats) {
        const div = document.getElementById('faq-modal-category-btns');
        if(div) div.innerHTML = cats.map(c => `<button type="button" class="btn" style="background:#eee;color:#333;font-size:12px;padding:4px;" onclick="this.form.other_category.value='${c}'">${c}</button>`).join('');
    }
    async function fetchAndRenderFaqs() {
        if(!faqListDiv) return;
        const faqs = await apiFetch('/api/faq');
        faqListDiv.innerHTML = faqs.map(f => `
            <div class="feedback-card">
                <div>${f.category} ${f.isPinned?'[置頂]':''}</div>
                <b>Q: ${f.question}</b><br>A: ${f.answer}
                <button class="btn btn--red" style="float:right;" onclick="deleteFaq('${f._id}')">刪除</button>
            </div>`).join('');
    }
    window.deleteFaq = async (id) => { if(confirm('刪除？')) { await apiFetch(`/api/faq/${id}`, {method:'DELETE'}); fetchFaqCategories().then(renderFaqCategoryBtns).then(fetchAndRenderFaqs); }};
    if(document.getElementById('add-faq-btn')) document.getElementById('add-faq-btn').onclick = async () => {
        const cats = await fetchFaqCategories(); renderFaqCategoryBtns(cats);
        faqForm.reset(); faqModal.classList.add('is-visible');
    };
    if(faqForm) faqForm.onsubmit = async (e) => {
        e.preventDefault();
        if(!faqForm.other_category.value) { alert('請輸入分類'); return; }
        await apiFetch('/api/faq', { method:'POST', body: JSON.stringify({
            question: faqForm.question.value, answer: faqForm.answer.value, category: faqForm.other_category.value, isPinned: faqForm.isPinned.checked
        })});
        faqModal.classList.remove('is-visible'); fetchFaqCategories().then(renderFaqCategoryBtns).then(fetchAndRenderFaqs);
    };

    // 連結與基金
    async function fetchLinks() {
        const div = document.getElementById('links-list');
        if(!div) return;
        const links = await apiFetch('/api/links');
        div.innerHTML = links.map(l => `
            <div style="margin-bottom:10px;">
                <b>${l.name}</b> <input value="${l.url}" readonly style="padding:5px;">
                <button class="btn btn--brown" onclick="editLink('${l._id}','${l.url}')">修改</button>
            </div>`).join('');
    }
    window.editLink = async (id, old) => {
        const url = prompt('新網址', old);
        if(url) { await apiFetch(`/api/links/${id}`, {method:'PUT', body:JSON.stringify({url})}); fetchLinks(); }
    };
    async function fetchFundSettings() {
        const data = await apiFetch('/api/fund-settings');
        if(document.getElementById('fund-goal')) {
            document.getElementById('fund-goal').value = data.goal_amount;
            document.getElementById('fund-current').value = data.current_amount;
        }
    }
    if(document.getElementById('fund-form')) document.getElementById('fund-form').onsubmit = async (e) => {
        e.preventDefault();
        await apiFetch('/api/fund-settings', { method:'POST', body: JSON.stringify({
            goal_amount: document.getElementById('fund-goal').value, current_amount: document.getElementById('fund-current').value
        })});
        alert('已更新');
    };

    // Modal 關閉
    document.querySelectorAll('.admin-modal-overlay').forEach(m => {
        m.onclick = (e) => { if(e.target.classList.contains('modal-close-btn') || e.target === m) m.classList.remove('is-visible'); };
    });

    checkSession();
});
/* === 10. 訂單管理 (Orders) === */
const ordersListDiv = document.getElementById('orders-list');

async function fetchOrders() {
    if(!ordersListDiv) return;
    try {
        const orders = await apiFetch('/api/orders');
        if(orders.length === 0) { ordersListDiv.innerHTML = '<p>無訂單</p>'; return; }
        
        ordersListDiv.innerHTML = orders.map(o => {
            const statusColor = o.status === 'paid' ? 'green' : (o.status === 'shipped' ? 'blue' : 'red');
            const statusText = o.status === 'paid' ? '已付款/待出貨' : (o.status === 'shipped' ? '已出貨' : '未付款/待核對');
            
            // 商品清單字串
            const itemsStr = o.items.map(i => `${i.name} x${i.qty}`).join(', ');
            
            return `
            <div class="feedback-card" style="border-left: 5px solid ${statusColor};">
                <div style="display:flex; justify-content:space-between; margin-bottom:10px;">
                    <span><b>${o.orderId}</b> (${o.customer.name})</span>
                    <span style="color:${statusColor}; font-weight:bold;">${statusText}</span>
                </div>
                <div style="font-size:14px; color:#555; line-height:1.6;">
                    金額：$${o.total} <br>
                    匯款後五碼：<b style="color:#C48945;">${o.customer.last5}</b> <br>
                    電話：${o.customer.phone} <br>
                    地址：${o.customer.address} <br>
                    商品：${itemsStr} <br>
                    時間：${o.createdAt}
                </div>
                <div style="text-align:right; margin-top:10px;">
                    ${o.status === 'pending' ? `<button class="btn btn--green" onclick="confirmOrder('${o._id}')">確認收款</button>` : ''}
                    <button class="btn btn--red" onclick="deleteOrder('${o._id}')">刪除</button>
                </div>
            </div>`;
        }).join('');
    } catch(e){ console.error(e); }
}

window.confirmOrder = async (id) => {
    if(confirm('確認已收到款項？系統將標記為已付款並寄信通知客人。')) {
        await apiFetch(`/api/orders/${id}/confirm`, {method:'PUT'});
        fetchOrders();
    }
};

window.deleteOrder = async (id) => {
    if(confirm('確定刪除此訂單？')) {
        await apiFetch(`/api/orders/${id}`, {method:'DELETE'});
        fetchOrders();
    }
};

// 記得在 switch case 裡加入 'tab-orders': fetchOrders(); break;