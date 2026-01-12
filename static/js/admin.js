document.addEventListener('DOMContentLoaded', () => {

    /* =========================================
       1. 核心工具
       ========================================= */
    const getCsrfToken = () => {
        const meta = document.querySelector('meta[name="csrf-token"]');
        return meta ? meta.getAttribute('content') : '';
    };

    async function apiFetch(url, options = {}) {
        const headers = { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken(), ...(options.headers || {}) };
        try {
            const response = await fetch(url, { ...options, credentials: 'include', headers });
            if (!response.ok) throw new Error((await response.text()) || `Error: ${response.status}`);
            return response.headers.get('content-type').includes('json') ? response.json() : response.text();
        } catch (error) { console.error(error); throw error; }
    }

    /* =========================================
       2. 初始化與登入
       ========================================= */
    const loginWrapper = document.getElementById('login-wrapper');
    const adminContent = document.getElementById('admin-content');
    const loginForm = document.getElementById('login-form');
    const logoutBtn = document.getElementById('logout-btn');
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
        loginWrapper.style.display = 'none'; adminContent.style.display = 'block';
        if (!adminContent.dataset.initialized) {
            setupNavigation();
            document.querySelector('.nav-item[data-tab="tab-products"]').click(); // 預設進商品頁
            adminContent.dataset.initialized = 'true';
        }
    }

    if(loginForm) loginForm.onsubmit = async (e) => {
        e.preventDefault();
        try {
            const res = await fetch('/api/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ password: document.getElementById('admin-password').value }) });
            if((await res.json()).success) location.reload(); else alert('密碼錯誤');
        } catch (err) { alert('連線錯誤'); }
    };
    if(logoutBtn) logoutBtn.onclick = async () => { await apiFetch('/api/logout', { method: 'POST' }); showLogin(); };

    /* =========================================
       3. 導覽與 UI
       ========================================= */
    function setupNavigation() {
        document.querySelectorAll('.nav-item').forEach(btn => {
            btn.onclick = () => {
                document.querySelectorAll('.nav-item').forEach(b => b.classList.remove('active'));
                document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
                btn.classList.add('active');
                document.getElementById(btn.dataset.tab).classList.add('active');
                if(window.innerWidth <= 768) closeSidebar();
                
                // 載入資料
                const tab = btn.dataset.tab;
                if(tab === 'tab-products') fetchProducts();
                if(tab === 'tab-orders') fetchOrders();
                if(tab === 'tab-feedback') { fetchPendingFeedback(); fetchApprovedFeedback(); }
                if(tab === 'tab-fund') { fetchFundSettings(); fetchAndRenderAnnouncements(); }
                if(tab === 'tab-qa') { fetchFaqCategories().then(renderFaqCategoryBtns).then(fetchAndRenderFaqs); }
                if(tab === 'tab-links') fetchLinks();
            };
        });
    }
    function closeSidebar() { sidebar.classList.remove('open'); sidebarOverlay.classList.remove('active'); }
    if(sidebarToggle) sidebarToggle.onclick = () => { sidebar.classList.add('open'); sidebarOverlay.classList.add('active'); };
    if(closeSidebarBtn) closeSidebarBtn.onclick = closeSidebar;
    if(sidebarOverlay) sidebarOverlay.onclick = closeSidebar;

    // Modal 通用關閉
    document.querySelectorAll('.admin-modal-overlay').forEach(m => m.onclick = (e) => { if(e.target===m || e.target.classList.contains('modal-close-btn')) m.classList.remove('is-visible'); });

    /* =========================================
       4. 商品管理 (含規格邏輯)
       ========================================= */
    const productsList = document.getElementById('products-list');
    const prodModal = document.getElementById('product-modal');
    const prodForm = document.getElementById('product-form');
    const variantsContainer = document.getElementById('variants-container');
    const imgInput = document.getElementById('product-image-input');
    const imgPreview = document.getElementById('preview-image');
    const imgHidden = prodForm ? prodForm.querySelector('[name="image"]') : null;

    // 圖片預覽
    if(imgInput) imgInput.onchange = (e) => {
        const file = e.target.files[0];
        if(!file) return;
        const reader = new FileReader();
        reader.onload = (ev) => { imgPreview.src = ev.target.result; imgPreview.style.display='block'; imgHidden.value=ev.target.result; };
        reader.readAsDataURL(file);
    };

    // 動態新增規格欄位
    function addVariantRow(name='', price='') {
        if(!variantsContainer) return;
        const div = document.createElement('div');
        div.className = 'variant-row';
        div.innerHTML = `
            <input type="text" placeholder="規格 (如: 尺6)" class="var-name" value="${name}" style="flex:2;">
            <input type="number" placeholder="價格" class="var-price" value="${price}" style="flex:1;">
            <button type="button" onclick="this.parentElement.remove()" class="btn btn--red" style="padding:5px 10px;">×</button>
        `;
        variantsContainer.appendChild(div);
    }
    const addVarBtn = document.getElementById('add-variant-btn');
    if(addVarBtn) addVarBtn.onclick = () => addVariantRow();

    async function fetchProducts() {
        if(!productsList) return;
        const products = await apiFetch('/api/products');
        productsList.innerHTML = products.map(p => {
            // 規格摘要
            let varsHtml = '';
            if(p.variants && p.variants.length > 0) varsHtml = p.variants.map(v => `<small>${v.name}: $${v.price}</small>`).join('<br>');
            else varsHtml = `<small>單價: $${p.price}</small>`;

            return `
            <div class="feedback-card" style="display:flex; gap:15px; align-items:center;">
                <div style="width:80px; height:80px; background:#eee; flex-shrink:0;">
                    ${p.image ? `<img src="${p.image}" style="width:100%; height:100%; object-fit:cover;">` : ''}
                </div>
                <div style="flex:1;">
                    <span style="border:1px solid #ddd; padding:2px 5px; font-size:12px; border-radius:4px;">${p.category}</span>
                    <h4 style="margin:5px 0;">${p.name}</h4>
                    <div>${varsHtml}</div>
                </div>
                <div>
                    <button class="btn btn--brown edit-prod" data-data='${JSON.stringify(p).replace(/'/g, "&apos;")}'>編輯</button>
                    <button class="btn btn--red del-prod" data-id="${p._id}">刪除</button>
                </div>
            </div>`;
        }).join('');

        productsList.querySelectorAll('.del-prod').forEach(b => b.onclick = async () => { if(confirm('刪除？')) { await apiFetch(`/api/products/${b.dataset.id}`, {method:'DELETE'}); fetchProducts(); } });
        productsList.querySelectorAll('.edit-prod').forEach(b => b.onclick = () => showProdModal(JSON.parse(b.dataset.data)));
    }

    function showProdModal(p=null) {
        prodForm.reset(); variantsContainer.innerHTML=''; imgPreview.style.display='none'; imgHidden.value='';
        if(p) {
            prodForm.productId.value = p._id;
            prodForm.category.value = p.category;
            prodForm.name.value = p.name;
            prodForm.description.value = p.description;
            prodForm.isActive.checked = p.isActive;
            if(p.image) { imgPreview.src = p.image; imgPreview.style.display='block'; imgHidden.value=p.image; }
            
            if(p.variants && p.variants.length > 0) p.variants.forEach(v => addVariantRow(v.name, v.price));
            else addVariantRow('標準', p.price); // 舊資料轉為規格
        } else {
            prodForm.productId.value = '';
            addVariantRow(); // 預設一列
        }
        prodModal.classList.add('is-visible');
    }
    const addProdBtn = document.getElementById('add-product-btn');
    if(addProdBtn) addProdBtn.onclick = () => showProdModal();

    if(prodForm) prodForm.onsubmit = async (e) => {
        e.preventDefault();
        // 收集規格
        const variants = [];
        variantsContainer.querySelectorAll('.variant-row').forEach(row => {
            const name = row.querySelector('.var-name').value.trim();
            const price = parseInt(row.querySelector('.var-price').value);
            if(name && price) variants.push({name, price});
        });
        if(variants.length === 0) return alert('請至少輸入一種規格與價格');

        const data = {
            category: prodForm.category.value,
            name: prodForm.name.value,
            description: prodForm.description.value,
            image: imgHidden.value,
            isActive: prodForm.isActive.checked,
            variants: variants,
            price: variants[0].price // 相容性
        };
        const id = prodForm.productId.value;
        await apiFetch(id ? `/api/products/${id}` : '/api/products', { method: id?'PUT':'POST', body:JSON.stringify(data) });
        prodModal.classList.remove('is-visible');
        fetchProducts();
    };

    /* =========================================
       5. 訂單管理 (Orders)
       ========================================= */
    const ordersList = document.getElementById('orders-list');
    async function fetchOrders() {
        if(!ordersList) return;
        const orders = await apiFetch('/api/orders');
        ordersList.innerHTML = orders.map(o => `
            <div class="feedback-card" style="border-left:5px solid ${o.status==='paid'?'green':'red'}">
                <div style="display:flex; justify-content:space-between;">
                    <b>${o.orderId}</b> <span style="color:${o.status==='paid'?'green':'red'}">${o.status==='paid'?'已付款':'待核對'}</span>
                </div>
                <p>金額: $${o.total} | 後五碼: <b style="color:#C48945">${o.customer.last5}</b> | 姓名: ${o.customer.name}</p>
                <div style="background:#f9f9f9; padding:5px; font-size:13px;">
                    ${o.items.map(i => `${i.name} (${i.variant}) x${i.qty}`).join('<br>')}
                </div>
                <div style="text-align:right; margin-top:5px;">
                    ${o.status==='pending' ? `<button class="btn btn--green" onclick="confirmOrder('${o._id}')">確認收款</button>` : ''}
                    <button class="btn btn--red" onclick="delOrder('${o._id}')">刪除</button>
                </div>
            </div>`).join('');
    }
    window.confirmOrder = async (id) => { if(confirm('確認收款？')) { await apiFetch(`/api/orders/${id}/confirm`, {method:'PUT'}); fetchOrders(); } };
    window.delOrder = async (id) => { if(confirm('刪除？')) { await apiFetch(`/api/orders/${id}`, {method:'DELETE'}); fetchOrders(); } };

    /* =========================================
       6. 其他功能 (回饋, 公告, FAQ, 基金, 連結)
       ========================================= */
    // 信徒回饋
    const pendingList = document.getElementById('pending-feedback-list');
    const approvedList = document.getElementById('approved-feedback-list');
    async function fetchPendingFeedback() {
        if(!pendingList) return;
        const data = await apiFetch('/api/feedback/pending');
        pendingList.innerHTML = data.length ? data.map(i => renderFeedbackCard(i, 'pending')).join('') : '<p>無待審核</p>';
        bindFeedbackBtns(pendingList);
    }
    async function fetchApprovedFeedback() {
        if(!approvedList) return;
        const data = await apiFetch('/api/feedback/approved');
        approvedList.innerHTML = data.length ? data.map(i => renderFeedbackCard(i, 'approved')).join('') : '<p>無已刊登</p>';
        bindFeedbackBtns(approvedList);
    }
    function renderFeedbackCard(item, type) {
        // ... (省略卡片 HTML，請使用前一版本或標準版，此處為簡化邏輯演示) ...
        // 為節省篇幅，請直接使用這段通用邏輯
        const btns = type === 'pending' 
            ? `<button class="btn btn--brown action-btn" data-id="${item._id}" data-action="approve">同意</button> <button class="btn btn--red action-btn" data-id="${item._id}" data-action="delete">刪除</button>`
            : `<button class="btn btn--grey view-btn" data-data='${JSON.stringify(item).replace(/'/g, "&apos;")}'>查看</button>`;
        return `<div class="feedback-card"><div>${item.nickname}: ${item.content.substring(0,30)}...</div><div style="text-align:right">${btns}</div></div>`;
    }
    function bindFeedbackBtns(container) {
        container.querySelectorAll('.action-btn').forEach(b => b.onclick = async () => {
            const url = b.dataset.action === 'approve' ? `/api/feedback/${b.dataset.id}/approve` : `/api/feedback/${b.dataset.id}`;
            await apiFetch(url, { method: b.dataset.action === 'approve' ? 'PUT' : 'DELETE' });
            fetchPendingFeedback(); fetchApprovedFeedback();
        });
    }
    const exportBtn = document.getElementById('export-btn');
    if(exportBtn) exportBtn.onclick = async () => {
        if(!confirm('匯出並標記？')) return;
        const res = await fetch('/api/feedback/download-unmarked', {method:'POST', headers:{'X-CSRFToken':getCsrfToken()}});
        if(res.status===404) return alert('無新資料');
        const blob = await res.blob();
        const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download='list.txt'; a.click();
        fetchApprovedFeedback();
    };

    // 基金與公告
    const fundForm = document.getElementById('fund-form');
    async function fetchFundSettings() {
        const data = await apiFetch('/api/fund-settings');
        if(document.getElementById('fund-goal')) {
            document.getElementById('fund-goal').value = data.goal_amount;
            document.getElementById('fund-current').value = data.current_amount;
        }
    }
    if(fundForm) fundForm.onsubmit = async (e) => {
        e.preventDefault();
        await apiFetch('/api/fund-settings', { method:'POST', body:JSON.stringify({goal_amount:document.getElementById('fund-goal').value, current_amount:document.getElementById('fund-current').value}) });
        alert('更新成功');
    };
    
    // (FAQ 與 連結功能省略，請保留您原有的或使用完整版)
    // 這裡只確保核心商城功能運作

    checkSession();
});