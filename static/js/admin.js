document.addEventListener('DOMContentLoaded', () => {

    /* =========================================
       1. 核心工具與初始化
       ========================================= */
    const getCsrfToken = () => document.querySelector('meta[name="csrf-token"]').getAttribute('content');

    async function apiFetch(url, options = {}) {
        const headers = { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken(), ...(options.headers || {}) };
        try {
            const response = await fetch(url, { ...options, credentials: 'include', headers });
            if (!response.ok) throw new Error((await response.text()) || `Error: ${response.status}`);
            return response.headers.get('content-type').includes('json') ? response.json() : response.text();
        } catch (error) { console.error(error); throw error; }
    }

    const loginWrapper = document.getElementById('login-wrapper');
    const adminContent = document.getElementById('admin-content');
    const loginForm = document.getElementById('login-form');
    const pageTitleDisplay = document.getElementById('page-title-display');
    
    // 檢查登入
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
            document.querySelector('.nav-item[data-tab="tab-products"]').click(); // 預設首頁
            adminContent.dataset.initialized = 'true';
        }
    }

    // 登入事件
    if(loginForm) loginForm.onsubmit = async (e) => {
        e.preventDefault();
        try {
            const res = await fetch('/api/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ password: document.getElementById('admin-password').value }) });
            if((await res.json()).success) location.reload(); else document.getElementById('login-error').textContent = '密碼錯誤';
        } catch (err) { alert('連線錯誤'); }
    };
    document.getElementById('logout-btn').onclick = async () => { await apiFetch('/api/logout', { method: 'POST' }); location.reload(); };

    /* =========================================
       2. 導覽與側邊欄
       ========================================= */
    function setupNavigation() {
        document.querySelectorAll('.nav-item').forEach(btn => {
            btn.onclick = () => {
                document.querySelectorAll('.nav-item').forEach(b => b.classList.remove('active'));
                document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
                btn.classList.add('active');
                document.getElementById(btn.dataset.tab).classList.add('active');
                pageTitleDisplay.textContent = btn.innerText;
                
                // 手機版自動收合
                if (window.innerWidth <= 768) {
                    document.getElementById('admin-sidebar').classList.remove('open');
                    document.getElementById('sidebar-overlay').style.display = 'none';
                }

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
    
    // 手機版側邊欄開關
    document.getElementById('sidebar-toggle').onclick = () => {
        document.getElementById('admin-sidebar').classList.add('open');
        document.getElementById('sidebar-overlay').style.display = 'block';
    };
    document.getElementById('sidebar-overlay').onclick = () => {
        document.getElementById('admin-sidebar').classList.remove('open');
        document.getElementById('sidebar-overlay').style.display = 'none';
    };

    // 通用 Modal 關閉
    document.querySelectorAll('.admin-modal-overlay').forEach(m => m.onclick = (e) => { 
        if(e.target===m || e.target.classList.contains('modal-close-btn')) m.classList.remove('is-visible'); 
    });

    /* =========================================
       3. 商品管理 (含規格) - 修正按鈕失效問題
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

    // ★ 關鍵修復：動態新增規格欄位函式
    function addVariantRow(name='', price='') {
        if(!variantsContainer) return;
        const div = document.createElement('div');
        div.className = 'variant-row';
        div.innerHTML = `
            <input type="text" placeholder="規格名稱 (如: 尺6)" class="var-name" value="${name}" style="flex:2;">
            <input type="number" placeholder="價格" class="var-price" value="${price}" style="flex:1;">
            <button type="button" class="btn btn--red remove-var-btn" style="padding:8px 12px;">×</button>
        `;
        div.querySelector('.remove-var-btn').onclick = () => div.remove();
        variantsContainer.appendChild(div);
    }
    
    // 綁定按鈕 (確保 ID 存在)
    const addVarBtn = document.getElementById('add-variant-btn');
    if(addVarBtn) addVarBtn.onclick = () => addVariantRow();

    const addProdBtn = document.getElementById('add-product-btn');
    if(addProdBtn) addProdBtn.onclick = () => showProdModal();

    // 顯示商品 Modal
    function showProdModal(p=null) {
        prodForm.reset(); 
        variantsContainer.innerHTML=''; 
        imgPreview.style.display='none'; 
        imgHidden.value='';
        
        if(p) {
            document.getElementById('product-modal-title').textContent = '編輯商品';
            prodForm.productId.value = p._id;
            prodForm.category.value = p.category;
            prodForm.name.value = p.name;
            prodForm.description.value = p.description;
            prodForm.isActive.checked = p.isActive;
            if(p.image) { imgPreview.src = p.image; imgPreview.style.display='block'; imgHidden.value=p.image; }
            
            // 載入規格
            if(p.variants && p.variants.length > 0) p.variants.forEach(v => addVariantRow(v.name, v.price));
            else addVariantRow('標準', p.price); // 相容舊資料
        } else {
            document.getElementById('product-modal-title').textContent = '新增商品';
            prodForm.productId.value = '';
            addVariantRow(); // 預設一列
        }
        prodModal.classList.add('is-visible');
    }

    // 載入商品列表
    async function fetchProducts() {
        if(!productsList) return;
        try {
            const products = await apiFetch('/api/products');
            productsList.innerHTML = products.map(p => {
                let varsHtml = '';
                if(p.variants && p.variants.length > 0) varsHtml = p.variants.map(v => `<small>${v.name}: $${v.price}</small>`).join('<br>');
                else varsHtml = `<small>單價: $${p.price}</small>`;

                return `
                <div class="feedback-card" style="display:flex; gap:15px; align-items:center;">
                    <div style="width:80px; height:80px; background:#eee; flex-shrink:0; border-radius:4px; overflow:hidden;">
                        ${p.image ? `<img src="${p.image}" style="width:100%; height:100%; object-fit:cover;">` : ''}
                    </div>
                    <div style="flex:1;">
                        <span style="border:1px solid #ddd; padding:2px 6px; font-size:12px; border-radius:4px; color:#666;">${p.category}</span>
                        <h4 style="margin:5px 0;">${p.name}</h4>
                        <div style="color:#555;">${varsHtml}</div>
                    </div>
                    <div style="display:flex; gap:5px; flex-direction:column;">
                        <button class="btn btn--brown edit-prod" data-data='${JSON.stringify(p).replace(/'/g, "&apos;")}'>編輯</button>
                        <button class="btn btn--red del-prod" data-id="${p._id}">刪除</button>
                    </div>
                </div>`;
            }).join('');

            productsList.querySelectorAll('.del-prod').forEach(b => b.onclick = async () => { if(confirm('刪除？')) { await apiFetch(`/api/products/${b.dataset.id}`, {method:'DELETE'}); fetchProducts(); } });
            productsList.querySelectorAll('.edit-prod').forEach(b => b.onclick = () => showProdModal(JSON.parse(b.dataset.data)));
        } catch(e) { productsList.innerHTML = '載入失敗'; }
    }

    // 儲存商品
    if(prodForm) prodForm.onsubmit = async (e) => {
        e.preventDefault();
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
            price: variants[0].price // 相容性欄位
        };
        const id = prodForm.productId.value;
        await apiFetch(id ? `/api/products/${id}` : '/api/products', { method: id?'PUT':'POST', body:JSON.stringify(data) });
        prodModal.classList.remove('is-visible');
        fetchProducts();
    };

    /* =========================================
       4. 訂單管理
       ========================================= */
    const ordersList = document.getElementById('orders-list');
    async function fetchOrders() {
        if(!ordersList) return;
        const orders = await apiFetch('/api/orders');
        if(orders.length === 0) { ordersList.innerHTML = '<p>無訂單</p>'; return; }
        
        ordersList.innerHTML = orders.map(o => `
            <div class="feedback-card" style="border-left:5px solid ${o.status==='paid'?'#28a745':(o.status==='shipped'?'blue':'#dc3545')}">
                <div style="display:flex; justify-content:space-between; margin-bottom:10px;">
                    <b>${o.orderId}</b> 
                    <span style="font-weight:bold; color:${o.status==='paid'?'green':'red'}">${o.status==='paid'?'已付款':(o.status==='shipped'?'已出貨':'待核對')}</span>
                </div>
                <div style="line-height:1.6; font-size:14px; color:#555;">
                    <div>金額: <b>$${o.total}</b> (後五碼: <span style="color:#C48945; font-weight:bold;">${o.customer.last5}</span>)</div>
                    <div>姓名: ${o.customer.name} / ${o.customer.phone}</div>
                    <div style="background:#f9f9f9; padding:5px; margin-top:5px; border-radius:4px;">
                        ${o.items.map(i => `${i.name} (${i.variantName}) x${i.qty}`).join('<br>')}
                    </div>
                </div>
                <div style="text-align:right; margin-top:10px;">
                    ${o.status==='pending' ? `<button class="btn btn--green" onclick="confirmOrder('${o._id}')">確認收款</button>` : ''}
                    <button class="btn btn--red" onclick="delOrder('${o._id}')">刪除</button>
                </div>
            </div>`).join('');
    }
    window.confirmOrder = async (id) => { if(confirm('確認已收到款項？')) { await apiFetch(`/api/orders/${id}/confirm`, {method:'PUT'}); fetchOrders(); } };
    window.delOrder = async (id) => { if(confirm('刪除訂單？')) { await apiFetch(`/api/orders/${id}`, {method:'DELETE'}); fetchOrders(); } };

    /* =========================================
       5. 信徒回饋
       ========================================= */
    const pendingList = document.getElementById('pending-feedback-list');
    const approvedList = document.getElementById('approved-feedback-list');
    const fbEditModal = document.getElementById('feedback-edit-modal');
    const fbEditForm = document.getElementById('feedback-edit-form');

    async function fetchPendingFeedback() {
        const data = await apiFetch('/api/feedback/pending');
        pendingList.innerHTML = data.length ? data.map(i => renderFbCard(i, 'pending')).join('') : '<p>無待審核資料</p>';
    }
    async function fetchApprovedFeedback() {
        const data = await apiFetch('/api/feedback/approved');
        approvedList.innerHTML = data.length ? data.map(i => renderFbCard(i, 'approved')).join('') : '<p>無已刊登資料</p>';
    }
    function renderFbCard(item, type) {
        const btns = type === 'pending' 
            ? `<button class="btn btn--grey" onclick='editFb(${JSON.stringify(item).replace(/'/g, "&apos;")})'>編輯</button> 
               <button class="btn btn--brown" onclick="approveFb('${item._id}')">同意</button> 
               <button class="btn btn--red" onclick="delFb('${item._id}')">刪除</button>`
            : `<button class="btn btn--grey" onclick='viewFb(${JSON.stringify(item).replace(/'/g, "&apos;")})'>查看</button>`;
        return `<div class="feedback-card" style="${item.isMarked?'background:#f0f9eb':''}">
            <div style="font-weight:bold; margin-bottom:5px;">${item.nickname} / ${item.category}</div>
            <div style="color:#666; overflow:hidden; white-space:nowrap; text-overflow:ellipsis;">${item.content}</div>
            <div style="text-align:right; margin-top:10px;">${btns}</div>
        </div>`;
    }
    
    window.approveFb = async (id) => { await apiFetch(`/api/feedback/${id}/approve`, {method:'PUT'}); fetchPendingFeedback(); fetchApprovedFeedback(); };
    window.delFb = async (id) => { if(confirm('刪除？')) await apiFetch(`/api/feedback/${id}`, {method:'DELETE'}); fetchPendingFeedback(); fetchApprovedFeedback(); };
    window.editFb = (item) => {
        if(!fbEditForm) return;
        fbEditForm.feedbackId.value = item._id; fbEditForm.realName.value = item.realName;
        fbEditForm.nickname.value = item.nickname; fbEditForm.content.value = item.content;
        fbEditForm.phone.value = item.phone; fbEditForm.address.value = item.address;
        fbEditForm.category.value = item.category;
        fbEditModal.classList.add('is-visible');
    };
    if(fbEditForm) fbEditForm.onsubmit = async (e) => {
        e.preventDefault();
        const data = {
            realName: fbEditForm.realName.value, nickname: fbEditForm.nickname.value, category: [fbEditForm.category.value],
            content: fbEditForm.content.value, phone: fbEditForm.phone.value, address: fbEditForm.address.value
        };
        await apiFetch(`/api/feedback/${fbEditForm.feedbackId.value}`, {method:'PUT', body:JSON.stringify(data)});
        fbEditModal.classList.remove('is-visible'); fetchPendingFeedback();
    };
    window.viewFb = (item) => {
        document.getElementById('view-modal-body').innerHTML = `<p>姓名: ${item.realName}</p><p>電話: ${item.phone}</p><p>地址: ${item.address}</p><hr><p>${item.content}</p>`;
        const delBtn = document.getElementById('delete-feedback-btn');
        delBtn.onclick = async () => { if(confirm('刪除？')) { await apiFetch(`/api/feedback/${item._id}`, {method:'DELETE'}); document.getElementById('view-modal').classList.remove('is-visible'); fetchApprovedFeedback(); }};
        document.getElementById('view-modal').classList.add('is-visible');
    };
    
    // 匯出與標記
    document.getElementById('export-btn').onclick = async () => {
        if(!confirm('匯出並標記已寄送？')) return;
        const res = await fetch('/api/feedback/download-unmarked', {method:'POST', headers:{'X-CSRFToken':getCsrfToken()}});
        if(res.status===404) return alert('無新資料');
        const blob = await res.blob();
        const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download='list.txt'; a.click();
        fetchApprovedFeedback();
    };
    document.getElementById('mark-all-btn').onclick = async () => {
        if(confirm('全部標記已讀？')) { await apiFetch('/api/feedback/mark-all-approved', {method:'PUT'}); fetchApprovedFeedback(); }
    };

    /* =========================================
       6. 基金與公告
       ========================================= */
    const fundForm = document.getElementById('fund-form');
    const annModal = document.getElementById('announcement-modal');
    const annForm = document.getElementById('announcement-form');
    const annList = document.getElementById('announcements-list');

    async function fetchFundSettings() {
        const data = await apiFetch('/api/fund-settings');
        document.getElementById('fund-goal').value = data.goal_amount;
        document.getElementById('fund-current').value = data.current_amount;
    }
    if(fundForm) fundForm.onsubmit = async (e) => {
        e.preventDefault();
        await apiFetch('/api/fund-settings', {method:'POST', body:JSON.stringify({goal_amount:document.getElementById('fund-goal').value, current_amount:document.getElementById('fund-current').value})});
        alert('更新成功');
    };

    async function fetchAndRenderAnnouncements() {
        const data = await apiFetch('/api/announcements');
        annList.innerHTML = data.map(a => `<div class="feedback-card"><div>${a.date} ${a.isPinned?'<span style="color:red">[置頂]</span>':''} ${a.title}</div><button class="btn btn--red" onclick="delAnn('${a._id}')" style="margin-top:5px; padding:4px 8px; font-size:12px;">刪除</button></div>`).join('');
    }
    window.delAnn = async (id) => { if(confirm('刪除？')) { await apiFetch(`/api/announcements/${id}`, {method:'DELETE'}); fetchAndRenderAnnouncements(); } };
    document.getElementById('add-announcement-btn').onclick = () => { annForm.reset(); annModal.classList.add('is-visible'); };
    if(annForm) annForm.onsubmit = async (e) => {
        e.preventDefault();
        await apiFetch('/api/announcements', {method:'POST', body:JSON.stringify({date:annForm.date.value, title:annForm.title.value, content:annForm.content.value, isPinned:annForm.isPinned.checked})});
        annModal.classList.remove('is-visible'); fetchAndRenderAnnouncements();
    };

    /* =========================================
       7. FAQ 與 連結 (補回功能)
       ========================================= */
    // FAQ
    const faqList = document.getElementById('faq-list');
    const faqModal = document.getElementById('faq-modal');
    const faqForm = document.getElementById('faq-form');
    
    async function fetchFaqCategories() { try { return await apiFetch('/api/faq/categories'); } catch(e){return [];} }
    function renderFaqCategoryBtns(cats) { document.getElementById('faq-modal-category-btns').innerHTML = cats.map(c => `<button type="button" class="btn" style="background:#eee;color:#333;margin-right:5px;padding:2px 5px;font-size:12px;" onclick="this.form.other_category.value='${c}'">${c}</button>`).join(''); }
    
    async function fetchAndRenderFaqs() {
        const faqs = await apiFetch('/api/faq');
        faqList.innerHTML = faqs.map(f => `<div class="feedback-card"><b>[${f.category}]</b> ${f.question}<br><small>${f.answer}</small><div style="text-align:right"><button class="btn btn--red" onclick="delFaq('${f._id}')" style="padding:4px 8px;font-size:12px;">刪除</button></div></div>`).join('');
    }
    window.delFaq = async (id) => { if(confirm('刪除？')) { await apiFetch(`/api/faq/${id}`, {method:'DELETE'}); fetchAndRenderFaqs(); } };
    document.getElementById('add-faq-btn').onclick = async () => { const cats = await fetchFaqCategories(); renderFaqCategoryBtns(cats); faqForm.reset(); faqModal.classList.add('is-visible'); };
    if(faqForm) faqForm.onsubmit = async (e) => {
        e.preventDefault();
        if(!faqForm.other_category.value) return alert('分類必填');
        await apiFetch('/api/faq', {method:'POST', body:JSON.stringify({question:faqForm.question.value, answer:faqForm.answer.value, category:faqForm.other_category.value, isPinned:faqForm.isPinned.checked})});
        faqModal.classList.remove('is-visible'); fetchAndRenderFaqs();
    };

    // Links
    const linksList = document.getElementById('links-list');
    async function fetchLinks() {
        const links = await apiFetch('/api/links');
        linksList.innerHTML = links.map(l => `<div style="margin-bottom:10px; display:flex; align-items:center; gap:10px;"><b>${l.name}</b> <input value="${l.url}" readonly style="flex:1;"> <button class="btn btn--brown" onclick="editLink('${l._id}', '${l.url}')">修改</button></div>`).join('');
    }
    window.editLink = async (id, old) => {
        const url = prompt('新網址', old);
        if(url) { await apiFetch(`/api/links/${id}`, {method:'PUT', body:JSON.stringify({url})}); fetchLinks(); }
    };

    checkSession();
});