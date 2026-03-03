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
            const contentType = response.headers.get('content-type');
            return contentType && contentType.includes('json') ? response.json() : response.text();
        } catch (error) { 
            console.error(error); 
            try {
                const errObj = JSON.parse(error.message);
                alert(errObj.message || '發生錯誤');
            } catch(e) {
                alert('操作失敗，請檢查網路或權限'); 
            }
            throw error; 
        }
    }

    const loginWrapper = document.getElementById('login-wrapper');
    const adminContent = document.getElementById('admin-content');
    const loginForm = document.getElementById('login-form');
    const pageTitleDisplay = document.getElementById('page-title-display');
    
    // 檢查登入狀態
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
            // 預設載入第一個分頁 (商品管理)
            document.querySelector('.nav-item[data-tab="tab-products"]').click();
            adminContent.dataset.initialized = 'true';
        }
    }

    // 登入事件
    if(loginForm) loginForm.onsubmit = async (e) => {
        e.preventDefault();
        try {
            const res = await fetch('/api/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ password: document.getElementById('admin-password').value }) });
            const data = await res.json();
            if(data.success) location.reload(); else document.getElementById('login-error').textContent = '密碼錯誤';
        } catch (err) { alert('連線錯誤'); }
    };
    
    // 登出事件
    document.getElementById('logout-btn').onclick = async () => { await apiFetch('/api/logout', { method: 'POST' }); location.reload(); };

    /* =========================================
       2. 導覽與側邊欄邏輯
       ========================================= */
    function setupNavigation() {
        document.querySelectorAll('.nav-item').forEach(btn => {
            btn.onclick = () => {
                // UI 切換
                document.querySelectorAll('.nav-item').forEach(b => b.classList.remove('active'));
                document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
                btn.classList.add('active');
                document.getElementById(btn.dataset.tab).classList.add('active');
                if(pageTitleDisplay) pageTitleDisplay.textContent = btn.innerText;
                
                // 手機版自動收合
                if (window.innerWidth <= 768) {
                    document.getElementById('admin-sidebar').classList.remove('open');
                    document.getElementById('sidebar-overlay').style.display = 'none';
                }

                // 根據分頁載入資料
                const tab = btn.dataset.tab;
                if(tab === 'tab-products') fetchProducts();
                if(tab === 'tab-donations') fetchDonations('donation'); // 預設載入捐香
                if(tab === 'tab-orders') fetchOrders();
                if(tab === 'tab-feedback') fetchFeedback(); // 統一函式
                if(tab === 'tab-fund') { fetchFundSettings(); fetchAndRenderAnnouncements(); }
                if(tab === 'tab-qa') { fetchFaqCategories().then(renderFaqCategoryBtns).then(fetchAndRenderFaqs); }
                if(tab === 'tab-links') { fetchLinks(); fetchBankInfo(); } // 載入匯款資訊
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

    // 卡片顯示完整的切換按鈕功能
    window.toggleContent = function(id, btn) {
        const box = document.getElementById(`content-${id}`);
        box.classList.toggle('expanded');
        if (box.classList.contains('expanded')) {
            btn.textContent = '收起內容';
        } else {
            btn.textContent = '顯示完整內容';
        }
    };

    /* =========================================
       3. 商品管理 (Cloudinary 上傳)
       ========================================= */
    const productsList = document.getElementById('products-list');
    const prodModal = document.getElementById('product-modal');
    const prodForm = document.getElementById('product-form');
    const variantsContainer = document.getElementById('variants-container');
    const imgInput = document.getElementById('product-image-input');
    const imgPreview = document.getElementById('preview-image');
    const imgHidden = prodForm ? prodForm.querySelector('[name="image"]') : null;

    const CLOUD_NAME = 'dsvj25pma';     
    const UPLOAD_PRESET = 'temple_upload'; 

    if(imgInput) imgInput.onchange = async (e) => {
        const file = e.target.files[0];
        if(!file) return;

        const localReader = new FileReader();
        localReader.onload = (ev) => {
            imgPreview.src = ev.target.result;
            imgPreview.style.display = 'block';
        };
        localReader.readAsDataURL(file);

        const formData = new FormData();
        formData.append('file', file);
        formData.append('upload_preset', UPLOAD_PRESET);

        const submitBtn = document.querySelector('#product-form button[type="submit"]');
        
        try {
            if(submitBtn) { 
                submitBtn.dataset.originalText = submitBtn.textContent;
                submitBtn.textContent = '圖片上傳中...'; 
                submitBtn.disabled = true; 
                submitBtn.style.opacity = '0.7';
            }

            const res = await fetch(`https://api.cloudinary.com/v1_1/${CLOUD_NAME}/image/upload`, {
                method: 'POST',
                body: formData
            });
            const data = await res.json();

            if(data.secure_url) {
                imgHidden.value = data.secure_url; 
                console.log('圖片上傳成功:', data.secure_url);
            } else {
                console.error('Cloudinary Error:', data);
                alert('圖片上傳失敗');
            }
        } catch (err) {
            console.error('Upload Error:', err);
            alert('圖片上傳發生錯誤');
        } finally {
            if(submitBtn) { 
                submitBtn.textContent = submitBtn.dataset.originalText || '儲存商品'; 
                submitBtn.disabled = false; 
                submitBtn.style.opacity = '1';
            }
        }
    };

    function addVariantRow(name='', price='') {
        if(!variantsContainer) return;
        const div = document.createElement('div');
        div.className = 'variant-row';
        div.innerHTML = `
            <input type="text" placeholder="規格名稱" class="var-name" value="${name}" style="flex:2;">
            <input type="number" placeholder="價格" class="var-price" value="${price}" style="flex:1;">
            <button type="button" class="btn btn--red remove-var-btn" style="padding:8px 12px;">×</button>
        `;
        div.querySelector('.remove-var-btn').onclick = () => div.remove();
        variantsContainer.appendChild(div);
    }
    
    const addVarBtn = document.getElementById('add-variant-btn');
    if(addVarBtn) addVarBtn.onclick = () => addVariantRow();

    const addProdBtn = document.getElementById('add-product-btn');
    if(addProdBtn) addProdBtn.onclick = () => showProdModal();

    function showProdModal(p=null) {
        prodForm.reset(); 
        variantsContainer.innerHTML=''; 
        imgPreview.style.display='none'; 
        imgHidden.value='';
        prodForm.seriesSort.value = 10;
        if(p) {
            document.getElementById('product-modal-title').textContent = '編輯商品';
            prodForm.productId.value = p._id;
            prodForm.category.value = p.category;
            prodForm.name.value = p.name;
            prodForm.description.value = p.description;
            prodForm.isActive.checked = p.isActive;
            prodForm.isDonation.checked = p.isDonation || false;
            prodForm.series.value = p.series || '';
            prodForm.seriesSort.value = p.seriesSort || 0;
            if(p.image) { 
                imgPreview.src = p.image; 
                imgPreview.style.display='block'; 
                imgHidden.value = p.image; 
            }
            if(p.variants && p.variants.length > 0) p.variants.forEach(v => addVariantRow(v.name, v.price));
            else addVariantRow('標準', p.price);
        } else {
            document.getElementById('product-modal-title').textContent = '新增商品';
            prodForm.productId.value = '';
            addVariantRow();
        }
        prodModal.classList.add('is-visible');
    }

    async function fetchProducts() {
        if(!productsList) return;
        try {
            const products = await apiFetch('/api/products');
            const groups = {};
            products.forEach(p => {
                if(!groups[p.category]) groups[p.category] = [];
                groups[p.category].push(p);
            });

            let html = '';
            for (const [cat, items] of Object.entries(groups)) {
                html += `<h3 style="background:#eee; padding:10px; border-radius:5px; color:#555;">📂 ${cat}</h3>`;
                html += items.map(p => {
                    let varsHtml = '';
                    if(p.variants && p.variants.length > 0) varsHtml = p.variants.map(v => `<small>${v.name}: $${v.price}</small>`).join(' | ');
                    else varsHtml = `<small>單價: $${p.price}</small>`;

                    return `
                    <div class="feedback-card" style="display:flex; gap:15px; align-items:center;">
                        <div style="width:80px; height:80px; background:#eee; flex-shrink:0; border-radius:4px; overflow:hidden;">
                            ${p.image ? `<img src="${p.image}" style="width:100%; height:100%; object-fit:cover;">` : ''}
                        </div>
                        <div style="flex:1;">
                            ${p.isDonation ? '<span style="background:#C48945; color:#fff; padding:2px 6px; font-size:12px; border-radius:4px;">捐贈項目</span>' : ''}
                            <h4 style="margin:5px 0;">${p.name}</h4>
                            <div style="color:#555;">${varsHtml}</div>
                            <small style="color:${p.isActive?'green':'red'}">${p.isActive?'● 上架中':'● 已下架'}</small>
                        </div>
                        <div style="display:flex; gap:5px; flex-direction:column;">
                            <button class="btn btn--brown edit-prod" data-data='${JSON.stringify(p).replace(/'/g, "&apos;")}'>編輯</button>
                            <button class="btn btn--red del-prod" data-id="${p._id}">刪除</button>
                        </div>
                    </div>`;
                }).join('');
            }
            productsList.innerHTML = html || '<p>目前無商品</p>';

            productsList.querySelectorAll('.del-prod').forEach(b => b.onclick = async () => { if(confirm('刪除？')) { await apiFetch(`/api/products/${b.dataset.id}`, {method:'DELETE'}); fetchProducts(); } });
            productsList.querySelectorAll('.edit-prod').forEach(b => b.onclick = () => showProdModal(JSON.parse(b.dataset.data)));
        } catch(e) { productsList.innerHTML = '載入失敗'; }
    }

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
            series: prodForm.series.value.trim(),
            seriesSort: parseInt(prodForm.seriesSort.value) || 0,
            isActive: prodForm.isActive.checked,
            isDonation: prodForm.isDonation.checked,
            variants: variants,
            price: variants[0].price
        };
        const id = prodForm.productId.value;
        await apiFetch(id ? `/api/products/${id}` : '/api/products', { method: id?'PUT':'POST', body:JSON.stringify(data) });
        prodModal.classList.remove('is-visible');
        fetchProducts();
    };

    /* =========================================
       4. 捐贈管理 (捐香與建廟分流)
       ========================================= */

    // 切換子分頁
    window.switchDonationTab = (type) => {
        document.querySelectorAll('.sub-tab-btn').forEach(b => b.classList.remove('active'));
        if(event) event.target.classList.add('active');
        
        const incenseDiv = document.getElementById('subtab-incense');
        const fundDiv = document.getElementById('subtab-fund');
        
        if(incenseDiv && fundDiv) {
            incenseDiv.style.display = type === 'incense' ? 'block' : 'none';
            fundDiv.style.display = type === 'fund' ? 'block' : 'none';
        }
        
        // 載入對應資料
        if (type === 'incense') fetchDonations('donation');
        else fetchDonations('fund');
    };

    // 載入列表 (共用函式)
    window.fetchDonations = async (type) => {
        // 如果沒有傳入 type，預設判斷目前哪個分頁是開的
        if(!type) {
            const isFundVisible = document.getElementById('subtab-fund').style.display === 'block';
            type = isFundVisible ? 'fund' : 'donation';
        }

        const container = type === 'donation' ? document.getElementById('incense-list') : document.getElementById('fund-list');
        if(!container) return;
        container.innerHTML = '<p>載入中...</p>';
        
        // ★ 修改：移除 status=paid 限制，抓取所有資料
        let url = `/api/donations/admin?type=${type}`;
        
        // 如果是捐香，加上稟告狀態篩選
        if (type === 'donation') {
            const filterEl = document.getElementById('incense-report-filter');
            const reportStatus = filterEl ? filterEl.value : '';
            if (reportStatus !== '') url += `&reported=${reportStatus}`;
        }

        try {
            const orders = await apiFetch(url);
            
            // ★ 修改：自動分流 待審核 與 已付款
            const pendingOrders = orders.filter(o => o.status === 'pending');
            const paidOrders = orders.filter(o => o.status === 'paid');

            if (type === 'donation') {
                renderIncenseList(pendingOrders, paidOrders, container);
            } else {
                renderFundList(pendingOrders, paidOrders, container);
            }
        } catch(e) { container.innerHTML = '載入失敗'; console.error(e); }
    };

    // 新增：確認捐贈收款
    window.confirmDonation = async (id, type) => {
        if(confirm('確認收到款項？將寄發電子感謝狀。')) {
            await apiFetch(`/api/orders/${id}/confirm`, {method:'PUT'});
            fetchDonations(type);
        }
    };

    // 渲染捐香列表 (包含稟告按鈕)
    function renderIncenseList(pending, paid, container) {
        const filterEl = document.getElementById('incense-report-filter');
        const isUnreportedView = filterEl && filterEl.value === '0';
        
        // 收集所有未稟告的 ID (只收集已付款的)
        window.currentIncenseIds = paid.filter(o => !o.is_reported).map(o => o._id);

        let html = '';

        // 1. 待審核區塊
        if (pending.length > 0) {
            html += `<h3 style="background:#dc3545; color:white; padding:10px; border-radius:5px; margin-bottom:10px;">⚠️ 待收款審核 (${pending.length})</h3>`;
            html += pending.map(o => `
                <div class="feedback-card" style="border-left:5px solid #dc3545; background:#fff5f5;">
                    <div style="display:flex; justify-content:space-between; align-items:flex-start;">
                        <div>
                            <strong>${o.customer.name}</strong> 
                            <span style="color:#666; font-size:13px;">(末五碼: <b>${o.customer.last5 || '無'}</b>)</span>
                            <div style="color:#C48945; font-weight:bold; margin-top:5px;">$ ${o.total}</div>
                        </div>
                        <div style="text-align:right;">
                            <button class="btn btn--green" onclick="confirmDonation('${o._id}', 'donation')">✅ 已收款</button>
                            <button class="btn btn--red" onclick="delOrder('${o._id}', 'donation')">🗑️ 刪除</button>
                        </div>
                    </div>
                    <div style="color:#555; margin-top:5px; font-size:14px;">
                        ${o.items.map(i => `${i.name} x${i.qty}`).join('、')}
                    </div>
                    <div style="font-size:12px; color:#888; margin-top:5px;">
                        單號: ${o.orderId} | 申請時間: ${o.createdAt}
                    </div>
                </div>
            `).join('');
            html += `<hr style="margin:20px 0; border:0; border-top:1px dashed #ccc;">`;
        }
        
        // 2. 已付款區塊
        if (isUnreportedView && paid.length > 0) {
            html += `
            <div style="background:#fff3cd; padding:10px; margin-bottom:15px; border-radius:5px; border:1px solid #ffeeba; display:flex; justify-content:space-between; align-items:center;">
                <span>⚠️ 共 <strong>${paid.length}</strong> 筆未稟告資料</span>
                <button class="btn btn--blue" onclick="markAllReported()">✅ 將本頁標記為已稟告</button>
            </div>`;
        }

        if (paid.length === 0 && pending.length === 0) {
            container.innerHTML = '<p style="padding:20px; text-align:center; color:#999;">查無資料</p>';
            return;
        }

        html += paid.map(o => `
            <div class="feedback-card" style="border-left:5px solid ${o.is_reported ? '#28a745' : '#ffc107'};">
                <div style="display:flex; justify-content:space-between;">
                    <strong>${o.customer.name}</strong>
                    <span style="font-size:12px; padding:2px 6px; border-radius:4px; background:${o.is_reported ? '#d4edda' : '#fff3cd'}; color:${o.is_reported ? '#155724' : '#856404'};">
                        ${o.is_reported ? `已稟告 (${o.reportedAt||''})` : '未稟告'}
                    </span>
                </div>
                <div style="color:#555; margin-top:5px;">
                    ${o.items.map(i => `${i.name} x${i.qty}`).join('、')}
                </div>
                <div style="font-size:12px; color:#888; margin-top:5px;">
                    單號: ${o.orderId} | 農曆: ${o.customer.lunarBirthday || '-'}
                </div>
            </div>
        `).join('');
        
        container.innerHTML = html;
    }

    // 渲染建廟基金列表
    function renderFundList(pending, paid, container) {
        let html = '';

        // 1. 待審核區塊
        if (pending.length > 0) {
            html += `<h3 style="background:#dc3545; color:white; padding:10px; border-radius:5px; margin-bottom:10px;">⚠️ 待收款審核 (${pending.length})</h3>`;
            html += pending.map(o => `
                <div class="feedback-card" style="border-left:5px solid #dc3545; background:#fff5f5;">
                    <div style="display:flex; justify-content:space-between; align-items:flex-start;">
                        <div>
                            <strong>${o.customer.name}</strong> 
                            <span style="color:#666; font-size:13px;">(末五碼: <b>${o.customer.last5 || '無'}</b>)</span>
                            <div style="color:#C48945; font-weight:bold; margin-top:5px;">$ ${o.total}</div>
                        </div>
                        <div style="text-align:right;">
                            <button class="btn btn--green" onclick="confirmDonation('${o._id}', 'fund')">✅ 已收款</button>
                            <button class="btn btn--red" onclick="delOrder('${o._id}', 'fund')">🗑️ 刪除</button>
                        </div>
                    </div>
                    <div style="color:#555; margin-top:5px; font-size:14px;">
                        ${o.items.map(i => i.name).join('、')}
                    </div>
                    <div style="font-size:12px; color:#888; margin-top:5px;">
                        單號: ${o.orderId} | ${o.createdAt}
                    </div>
                </div>
            `).join('');
            html += `<hr style="margin:20px 0; border:0; border-top:1px dashed #ccc;">`;
        }

        // 2. 已付款區塊
        if (paid.length > 0) {
            html += paid.map(o => `
                <div class="feedback-card" style="border-left:5px solid #C48945;">
                    <div style="display:flex; justify-content:space-between;">
                        <strong>${o.customer.name}</strong>
                        <span style="color:#C48945; font-weight:bold;">$${o.total}</span>
                    </div>
                    <div style="color:#555; margin-top:5px;">
                        ${o.items.map(i => i.name).join('、')}
                    </div>
                    <div style="font-size:12px; color:#888; margin-top:5px;">
                        ${o.createdAt} | ${o.customer.address}
                    </div>
                </div>
            `).join('');
        } else if (pending.length === 0) {
            html += '<p style="padding:20px; text-align:center; color:#999;">查無資料</p>';
        }

        container.innerHTML = html;
    }

    // === 功能：列印紅紙 (Simple Red Paper Print) ===
    window.printRedPaper = async () => {
        const orders = await apiFetch('/api/donations/admin?type=donation&status=paid&reported=0');
        if (orders.length === 0) return alert('目前沒有未稟告的資料可列印');

        const printWindow = window.open('', '_blank');
        let itemsHtml = '';
        
        orders.forEach(o => {
            const itemStr = o.items.map(i => `${i.name} ${i.qty}份`).join('、');
            itemsHtml += `
                <div class="row">
                    <span class="name">${o.customer.name}</span>
                    <span class="items">${itemStr}</span>
                </div>
            `;
        });

        printWindow.document.write(`
            <html>
            <head>
                <title>稟告紅紙清單</title>
                <style>
                    body { font-family: "KaiTi", "Microsoft JhengHei", serif; padding: 20px; background: white; }
                    .list-container { width: 100%; max-width: 800px; margin: 0 auto; }
                    .header { text-align: center; font-size: 24px; font-weight: bold; margin-bottom: 30px; }
                    .row { 
                        display: flex; border-bottom: 1px dashed #000; padding: 15px 0; 
                        font-size: 20px; line-height: 1.5; color: #000; font-weight: bold;
                    }
                    .name { width: 150px; flex-shrink: 0; }
                    .items { flex: 1; }
                    @media print {
                        @page { margin: 0; }
                        body { -webkit-print-color-adjust: exact; background-color: #ffcccc; }
                    }
                </style>
            </head>
            <body>
                <div class="list-container">
                    <div class="header">承天中承府 捐香稟告清單 (${new Date().toLocaleDateString()})</div>
                    ${itemsHtml}
                </div>
                <script>window.print();<\/script>
            </body>
            </html>
        `);
        printWindow.document.close();
    };

    // === 功能：批次標記已稟告 ===
    window.markAllReported = async () => {
        if (!window.currentIncenseIds || window.currentIncenseIds.length === 0) return;
        if (!confirm(`確定將這 ${window.currentIncenseIds.length} 筆資料標記為「已稟告」嗎？`)) return;

        try {
            await apiFetch('/api/donations/mark-reported', {
                method: 'POST',
                body: JSON.stringify({ ids: window.currentIncenseIds })
            });
            alert('更新成功！');
            fetchDonations('donation'); 
        } catch(e) { alert('更新失敗'); }
    };

    /* =========================================
       5. 一般訂單管理
       ========================================= */
    const ordersList = document.getElementById('orders-list');
    
    async function fetchOrders() {
        if(!ordersList) return;
        const orders = await apiFetch('/api/orders');
        
        const pending = orders.filter(o => o.status === 'pending');
        const toShip = orders.filter(o => o.status === 'paid');
        const shipped = orders.filter(o => o.status === 'shipped');

        ordersList.innerHTML = `
            <div style="display:flex; flex-direction:column; gap:30px;">
                <div>
                    <h3 style="background:#dc3545; color:white; padding:10px; border-radius:5px; margin:0 0 10px 0;">1. 未付款 (${pending.length})</h3>
                    ${pending.length ? pending.map(o => renderShopOrder(o, 'pending')).join('') : '<p style="padding:10px;">無</p>'}
                </div>
                <div>
                    <h3 style="background:#28a745; color:white; padding:10px; border-radius:5px; margin:0 0 10px 0;">2. 待出貨 (${toShip.length})</h3>
                    ${toShip.length ? toShip.map(o => renderShopOrder(o, 'toship')).join('') : '<p style="padding:10px;">無</p>'}
                </div>
                <div>
                    <h3 style="background:#007bff; color:white; padding:10px; border-radius:5px; margin:0 0 10px 0;">3. 已出貨 (${shipped.length})</h3>
                    <div style="text-align:right;"><button class="btn btn--red" onclick="cleanupShipped()">🗑️ 清除舊單</button></div>
                    ${shipped.length ? shipped.map(o => renderShopOrder(o, 'shipped')).join('') : '<p style="padding:10px;">無</p>'}
                </div>
            </div>
        `;
    }

    function renderShopOrder(o, type) {
        let btns = `<button class="btn btn--grey" onclick='viewOrderDetails(${JSON.stringify(o).replace(/'/g, "&apos;")})'>🔍 查看詳情</button>`; 
        if(type === 'pending') {
            btns += `<button class="btn btn--green" onclick="confirmOrder('${o._id}', '${o.orderId}')">✅ 確認收款</button>
                     <button class="btn btn--red" onclick="delOrder('${o._id}', 'shop')">刪除</button>`;
        } else if(type === 'toship') {
            btns += `<button class="btn btn--blue" onclick="shipOrder('${o._id}')">🚚 出貨</button>`;
        }
        return `
        <div class="feedback-card" style="border-left:5px solid ${type==='pending'?'#dc3545':(type==='toship'?'#28a745':'#007bff')};">
            <div style="display:flex; justify-content:space-between;"><b>${o.orderId}</b> <small>${o.createdAt}</small></div>
            <div>
                ${o.customer.shippingMethod === '711' ? '<span style="color:#28a745; font-weight:bold;">[7-11]</span>' : ''}
                ${o.customer.name} / ${o.customer.phone} / $${o.total}
            </div>
            <div style="color:#666;">${o.items.map(i => `${i.name} x${i.qty}`).join(', ')}</div>
            <div style="text-align:right; margin-top:10px;">${btns}</div>
        </div>`;
    }

    window.viewOrderDetails = (o) => {
        const modalBody = document.getElementById('order-detail-body');
        modalBody.innerHTML = `
            <p><b>訂單編號:</b> ${o.orderId}</p>
            <p><b>建立時間:</b> ${o.createdAt}</p>
            <hr>
            <h4>客戶資料</h4>
            <p><b>姓名:</b> ${o.customer.name}</p>
            <p><b>電話:</b> ${o.customer.phone}</p>
            ${(() => {
                if (o.customer.shippingMethod === '711') {
                    return `<p><b>取貨:</b> <span style="background:#28a745; color:#fff; padding:2px 5px; border-radius:3px;">7-11</span> ${o.customer.storeInfo || '未抓到門市資料'}</p>`;
                } else {
                    return `<p><b>地址:</b> ${o.customer.address}</p>`;
                }
            })()}            
            <p><b>Email:</b> ${o.customer.email}</p>
            <p><b>匯款後五碼:</b> ${o.customer.last5}</p>
            <hr>
            <h4>訂單內容</h4>
            <ul>${o.items.map(i => `<li>${i.name} (${i.variantName||i.variant||'標準'}) x${i.qty} - $${i.price*i.qty}</li>`).join('')}</ul>
            <p style="text-align:right; font-size:18px; color:#C48945;"><b>總金額: $${o.total}</b></p>
            ${o.trackingNumber ? `<hr><p><b>物流單號:</b> ${o.trackingNumber}</p>` : ''}
        `;
        document.getElementById('order-detail-modal').classList.add('is-visible');
    }

    window.confirmOrder = async (id, orderId) => { if(confirm(`確認收款訂單編號：${orderId}，將回信待出貨？`)) { await apiFetch(`/api/orders/${id}/confirm`, {method:'PUT'}); fetchOrders(); } };
    window.shipOrder = async (id) => {
        const trackNum = prompt("請輸入物流單號 (寄送出貨通知信)：");
        if(trackNum !== null) { 
            await apiFetch(`/api/orders/${id}/ship`, { method:'PUT', body: JSON.stringify({trackingNumber: trackNum}) });
            alert("已出貨並通知！"); fetchOrders();
        }
    };
    window.cleanupShipped = async () => { if(confirm('刪除14天前舊單？')) { await apiFetch('/api/orders/cleanup-shipped', {method:'DELETE'}); fetchOrders(); } };
    window.delOrder = async (id, type) => { 
        if(confirm('確定刪除？系統將自動寄送「取消通知信」給客戶。')) { 
            await apiFetch(`/api/orders/${id}`, {method:'DELETE'}); 
            if(type === 'donation') fetchDonations('donation'); 
            else if(type === 'fund') fetchDonations('fund');
            else fetchOrders();
        } 
    };

    /* =========================================
       6. 信徒回饋 (三階段流程 + 統計與抽獎)
       ========================================= */
    const fbPendingList = document.getElementById('fb-pending-list');
    const fbApprovedList = document.getElementById('fb-approved-list');
    const fbSentList = document.getElementById('fb-sent-list');
    const fbEditModal = document.getElementById('feedback-edit-modal');
    const fbEditForm = document.getElementById('feedback-edit-form');

    async function fetchFeedback() {
        if(!fbPendingList) return;
        
        const pending = await apiFetch('/api/feedback/status/pending');
        const approved = await apiFetch('/api/feedback/status/approved'); 
        const sent = await apiFetch('/api/feedback/status/sent');         

// === 新增：統計數據與匯出按鈕 ===
        const totalCount = pending.length + approved.length + sent.length;
        const statsDiv = document.getElementById('fb-stats-bar');
        if(statsDiv) {
            statsDiv.innerHTML = `
                <span style="background:#6c757d; color:white; padding:8px 15px; border-radius:20px; font-weight:bold;">
                    總回饋數: ${totalCount} 筆
                </span>
                <button class="btn btn--brown" onclick="printFeedbackList()">匯出回饋</button>
            `;
        }
        // 1. 待審核
        fbPendingList.innerHTML = pending.length ? pending.map(i => {
            const badge = i.has_received ? '<span style="color:#dc3545; font-weight:bold; font-size:13px; margin-left:10px;">[⚠️ 已領取過小神衣]</span>' : '';
            return `
            <div class="feedback-card" style="border-left:5px solid #dc3545;">
                <div style="font-weight:bold; margin-bottom:12px; font-size: 16px; border-bottom: 1px solid #eee; padding-bottom: 8px;">
                    👤 暱稱：${i.nickname} ${badge}
                </div>
                <div style="background:#f9f9f9; padding:12px; border-radius:5px; margin-bottom:15px;">
                    <div class="pre-wrap" style="color:#444;">${i.content}</div>
                </div>
                <div style="text-align:right;">
                    <button class="btn btn--grey" onclick='editFb(${JSON.stringify(i).replace(/'/g, "&apos;")})'>編輯</button>
                    <button class="btn btn--green" onclick="approveFb('${i._id}')">✅ 核准 (寄信)</button>
                    <button class="btn btn--red" onclick="delFb('${i._id}')">🗑️ 刪除</button>
                </div>
            </div>`;
        }).join('') : '<p>無</p>';

        // 2. 已刊登
        fbApprovedList.innerHTML = approved.length ? approved.map(i => {
            const badge = i.has_received ? '<span style="color:#dc3545; font-weight:bold; font-size:13px; margin-left:10px;">[⚠️ 已領取過小神衣]</span>' : '';
            const lunarBday = i.lunarBirthday || '未提供';
            return `
            <div class="feedback-card" style="border-left:5px solid #28a745;">
                <div style="display:flex; justify-content:space-between; align-items:center; border-bottom: 1px solid #eee; padding-bottom: 10px; margin-bottom: 10px;">
                    <strong>編號: ${i.feedbackId || '無'}</strong>
                    <span style="color:#888; font-size:13px;">${i.approvedAt || ''}</span>
                </div>
                <div style="margin-bottom: 15px; line-height: 1.8;">
                    <strong>${i.realName}</strong> (農曆生日: ${lunarBday}) ${badge}<br>
                    <span style="color:#666; font-size:14px;">📍 ${i.address}</span>
                </div>
                <div style="display: flex; justify-content: space-between; align-items: center; border-top: 1px solid #eee; padding-top: 15px;">
                    <button class="btn btn--grey" onclick='viewFbDetail(${JSON.stringify(i).replace(/'/g, "&apos;")})'>📖 查看回饋內容</button>
                    <button class="btn btn--blue" onclick="shipGift('${i._id}')">🎁 填寫物流並寄出</button>
                </div>
            </div>`;
        }).join('') : '<p>無</p>';
            
        // 3. 已寄送
        fbSentList.innerHTML = sent.length ? sent.map(i => `
            <div class="feedback-card" 
                 style="border-left:5px solid #007bff; background:#f0f0f0; cursor:pointer; transition:0.2s;" 
                 onmouseover="this.style.background='#e2e6ea'" 
                 onmouseout="this.style.background='#f0f0f0'"
                 onclick='viewFbDetail(${JSON.stringify(i).replace(/'/g, "&apos;")})'>
                <div style="display:flex; justify-content:space-between; align-items:center;">
                    <span style="font-size:16px; font-weight:bold; color:#333;">${i.nickname}</span>
                    <span style="background:#dbeafe; color:#007bff; padding:2px 8px; border-radius:12px; font-size:12px;">
                        ${i.feedbackId || '無編號'}
                    </span>
                </div>
                <div style="text-align:right; font-size:12px; color:#888; margin-top:5px;">
                    寄出日: ${i.sentAt || '未知'} (點擊查看詳情)
                </div>
            </div>`).join('') : '<p>無</p>';
    }

    // 核准回饋
    window.approveFb = async (id) => { 
        if(confirm('確認核准？(將寄信通知信徒已刊登)')) {
            await apiFetch(`/api/feedback/${id}/approve`, {method:'PUT'});
            fetchFeedback();
        }
    };

    // 寄送禮物
    window.shipGift = async (id) => {
        const track = prompt('請輸入小神衣物流單號：');
        if(track) {
            await apiFetch(`/api/feedback/${id}/ship`, {method:'PUT', body:JSON.stringify({trackingNumber: track})});
            alert('已標記寄送並通知信徒！');
            fetchFeedback();
        }
    };
    
    // 刪除回饋
    window.delFb = async (id) => { 
        if(confirm('確認刪除？(將寄信通知信徒未獲刊登)')) {
            await apiFetch(`/api/feedback/${id}`, {method:'DELETE'});
            fetchFeedback();
        }
    };
    
    // 匯出名單
    window.exportFeedbackTxt = async () => {
        try {
            const res = await fetch('/api/feedback/export-txt', {method:'POST', headers:{'X-CSRFToken':getCsrfToken()}});
            if(res.status===404) return alert('無資料');
            const blob = await res.blob();
            const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download='回饋寄送名單.txt'; a.click();
        } catch(e) { alert('匯出失敗'); }
    };

    window.exportSentFeedbackTxt = async () => {
        try {
            const res = await fetch('/api/feedback/export-sent-txt', {method:'POST', headers:{'X-CSRFToken':getCsrfToken()}});
            if(res.status === 404) return alert('目前無已寄送資料');
            if(!res.ok) throw new Error('匯出失敗');
            const blob = await res.blob();
            const a = document.createElement('a'); 
            a.href = URL.createObjectURL(blob); 
            a.download = `已寄送名單_${new Date().toISOString().slice(0,10)}.txt`; 
            a.click();
        } catch(e) { 
            console.error(e);
            alert('匯出失敗'); 
        }
    };

    // 編輯回饋 Modal
    window.editFb = (item) => {
        if(!fbEditForm) return;
        fbEditForm.feedbackId.value = item._id; fbEditForm.realName.value = item.realName;
        fbEditForm.nickname.value = item.nickname; fbEditForm.content.value = item.content;
        fbEditForm.phone.value = item.phone; fbEditForm.address.value = item.address;
        fbEditForm.category.value = Array.isArray(item.category) ? item.category[0] : item.category;
        fbEditModal.classList.add('is-visible');
    };
    if(fbEditForm) fbEditForm.onsubmit = async (e) => {
        e.preventDefault();
        const data = {
            realName: fbEditForm.realName.value, nickname: fbEditForm.nickname.value, category: [fbEditForm.category.value],
            content: fbEditForm.content.value, phone: fbEditForm.phone.value, address: fbEditForm.address.value
        };
        await apiFetch(`/api/feedback/${fbEditForm.feedbackId.value}`, {method:'PUT', body:JSON.stringify(data)});
        fbEditModal.classList.remove('is-visible'); fetchFeedback();
    };

    // 查看詳情
    window.viewFbDetail = (item) => {
        const modal = document.getElementById('feedback-detail-modal');
        const body = document.getElementById('feedback-detail-body');
        let statusHtml = item.status === 'sent' 
            ? `<p><strong>寄出時間：</strong> ${item.sentAt || '未知'}</p><p><strong>物流單號：</strong> ${item.trackingNumber || '無'}</p>`
            : `<p><strong>核准時間：</strong> ${item.approvedAt || '未知'}</p>`;
        
        body.innerHTML = `
            <div style="border-bottom:1px solid #eee; padding-bottom:10px; margin-bottom:10px;">
                <p><strong>編號：</strong> ${item.feedbackId || '無'}</p>
                ${statusHtml}
            </div>
            <p><strong>真實姓名：</strong> ${item.realName}</p>
            <p><strong>暱稱：</strong> ${item.nickname}</p>
            <p><strong>農曆生日：</strong> ${item.lunarBirthday || '未提供'}</p>
            <p><strong>電話：</strong> ${item.phone}</p>
            <p><strong>地址：</strong> ${item.address}</p>
            <p><strong>分類：</strong> ${Array.isArray(item.category) ? item.category.join(', ') : item.category}</p>
            <div style="background:#f9f9f9; padding:15px; border-radius:8px; border:1px solid #ddd; margin-top:15px;">
                <strong style="color:#C48945;">回饋內容：</strong><br>
                <div class="pre-wrap" style="margin-top:10px;">${item.content}</div>
            </div>
        `;
        modal.classList.add('is-visible');
    };

// 回饋清單匯出功能 (含已審核與已寄送)
    window.printFeedbackList = async () => {
        const approved = await apiFetch('/api/feedback/status/approved'); 
        const sent = await apiFetch('/api/feedback/status/sent');
        // 合併已核准與已寄送的資料
        const allCandidates = [...approved, ...sent]; 

        if (allCandidates.length === 0) return alert('目前沒有符合資格的名單');

        const printWindow = window.open('', '_blank');
        
        // 依照指定格式產生 HTML
        let itemsHtml = allCandidates.map((fb, index) => `
            <div class="feedback-item">
                <div class="meta">編號: ${fb.feedbackId || '無'}</div>
                <div class="nickname">${fb.nickname}</div>
                <div class="content">${fb.content}</div>
            </div>
        `).join('');

        printWindow.document.write(`
            <html>
            <head>
                <title>信徒回饋匯出</title>
                <style>
                    body { 
                        font-family: "Microsoft JhengHei", "Heiti TC", sans-serif; 
                        padding: 40px; 
                        max-width: 800px; 
                        margin: 0 auto; 
                        color: #333;
                    }
                    .feedback-item { 
                        margin-bottom: 60px; 
                        /* 關鍵：防止內容在列印時被切斷到下一頁 */
                        page-break-inside: avoid; 
                        break-inside: avoid;      
                    }
                    .meta { 
                        font-size: 14px; 
                        color: #666; 
                        margin-bottom: 5px; 
                    }
                    .nickname { 
                        font-size: 20px; 
                        font-weight: bold; 
                        margin-bottom: 15px; 
                        color: #000; 
                    }
                    .content { 
                        font-size: 16px; 
                        line-height: 1.8; 
                        white-space: pre-wrap; /* 保留換行格式 */
                        text-align: justify; 
                    }
                    @media print {
                        body { padding: 0; margin: 2cm; }
                        /* 再次確保列印時的斷頁行為 */
                        .feedback-item { page-break-inside: avoid; }
                    }
                </style>
            </head>
            <body>
                <h2 style="text-align:center; margin-bottom: 50px; border-bottom: 2px solid #333; padding-bottom: 20px;">
                    信徒回饋匯出清單 (共 ${allCandidates.length} 筆)
                </h2>
                ${itemsHtml}
                <script>
                    // 確保圖片或樣式載入後再列印 (雖然這裡只有文字)
                    setTimeout(() => { window.print(); }, 500);
                <\/script>
            </body>
            </html>
        `);
        printWindow.document.close();
    };
    /* =========================================
       7. 系統參數與連結
       ========================================= */
    const linksList = document.getElementById('links-list');
    const bankForm = document.getElementById('bank-form');

    async function fetchLinks() {
        const links = await apiFetch('/api/links');
        linksList.innerHTML = links.map(l => `<div style="margin-bottom:10px; display:flex; align-items:center; gap:10px;"><b>${l.name}</b> <input value="${l.url}" readonly style="flex:1; padding:8px; border:1px solid #ddd; background:#f9f9f9;"> <button class="btn btn--brown" onclick="updLink('${l._id}', '${l.url}')">修改</button></div>`).join('');
    }
    
    // 1. 修改 fetchBankInfo
async function fetchBankInfo() {
    try {
        const data = await apiFetch('/api/settings/bank');
        if(bankForm) {
            // 填入 Shop 資料
            bankForm.shop_bankCode.value = data.shop.bankCode || '';
            bankForm.shop_bankName.value = data.shop.bankName || '';
            bankForm.shop_account.value = data.shop.account || '';
            
            // 填入 Fund 資料
            bankForm.fund_bankCode.value = data.fund.bankCode || '';
            bankForm.fund_bankName.value = data.fund.bankName || '';
            bankForm.fund_account.value = data.fund.account || '';
        }
    } catch(e) { console.error('Bank info load fail'); }
}

// 2. 修改表單送出事件
if(bankForm) bankForm.onsubmit = async (e) => {
    e.preventDefault();
    const payload = {
        shop: {
            bankCode: bankForm.shop_bankCode.value,
            bankName: bankForm.shop_bankName.value,
            account: bankForm.shop_account.value
        },
        fund: {
            bankCode: bankForm.fund_bankCode.value,
            bankName: bankForm.fund_bankName.value,
            account: bankForm.fund_account.value
        }
    };
    
    await apiFetch('/api/settings/bank', {method:'POST', body:JSON.stringify(payload)});
    alert('匯款資訊已更新 (已區分 一般/建廟)');
};

    window.updLink = async (id, old) => {
        const url = prompt('新網址', old);
        if(url) { await apiFetch(`/api/links/${id}`, {method:'PUT', body:JSON.stringify({url})}); fetchLinks(); }
    };

    /* =========================================
       8. 基金與公告
       ========================================= */
    const fundForm = document.getElementById('fund-form');
    const annModal = document.getElementById('announcement-modal');
    const annForm = document.getElementById('announcement-form');
    const annList = document.getElementById('announcements-list');

    async function fetchFundSettings() {
        const data = await apiFetch('/api/fund-settings');
        if(document.getElementById('fund-goal')) {
            document.getElementById('fund-goal').value = data.goal_amount;
            document.getElementById('fund-current').value = data.current_amount;
        }
    }
    if(fundForm) fundForm.onsubmit = async (e) => {
        e.preventDefault();
        await apiFetch('/api/fund-settings', {
            method:'POST', 
            body:JSON.stringify({
                goal_amount: document.getElementById('fund-goal').value
            })
        });
        alert('更新成功！目前的線上募款金額已同步刷新。');
        fetchFundSettings();
    };

    async function fetchAndRenderAnnouncements() {
        const data = await apiFetch('/api/announcements');
        annList.innerHTML = data.map(a => `
            <div class="feedback-card">
                <div><small>${a.date}</small> <b>${a.title}</b> ${a.isPinned?'<span style="color:red">[置頂]</span>':''}</div>
                <div class="pre-wrap" style="margin:10px 0;">${a.content}</div>
                <div style="text-align:right;">
                    <button class="btn btn--brown" onclick='editAnn(${JSON.stringify(a).replace(/'/g, "&apos;")})'>編輯</button>
                    <button class="btn btn--red" onclick="delAnn('${a._id}')">刪除</button>
                </div>
            </div>`).join('');
    }
    window.delAnn = async (id) => { if(confirm('刪除？')) { await apiFetch(`/api/announcements/${id}`, {method:'DELETE'}); fetchAndRenderAnnouncements(); } };
    window.editAnn = (a) => {
        annForm.reset(); document.getElementById('ann-modal-title').textContent = '編輯公告';
        annForm.announcementId.value = a._id; annForm.date.value = a.date; annForm.title.value = a.title; annForm.content.value = a.content; annForm.isPinned.checked = a.isPinned;
        annModal.classList.add('is-visible');
    };
    document.getElementById('add-announcement-btn').onclick = () => { annForm.reset(); document.getElementById('ann-modal-title').textContent = '新增公告'; annForm.announcementId.value = ''; annModal.classList.add('is-visible'); };
    if(annForm) annForm.onsubmit = async (e) => {
        e.preventDefault();
        const id = annForm.announcementId.value;
        await apiFetch(id ? `/api/announcements/${id}` : '/api/announcements', { method: id ? 'PUT' : 'POST', body: JSON.stringify({ date: annForm.date.value, title: annForm.title.value, content: annForm.content.value, isPinned: annForm.isPinned.checked }) });
        annModal.classList.remove('is-visible'); fetchAndRenderAnnouncements();
    };

    // FAQ
    const faqList = document.getElementById('faq-list');
    const faqModal = document.getElementById('faq-modal');
    const faqForm = document.getElementById('faq-form');
    async function fetchFaqCategories() { try { return await apiFetch('/api/faq/categories'); } catch(e){return [];} }
    function renderFaqCategoryBtns(cats) { document.getElementById('faq-modal-category-btns').innerHTML = cats.map(c => `<button type="button" class="btn btn--grey" style="margin:0 5px 5px 0" onclick="this.form.other_category.value='${c}'">${c}</button>`).join(''); }
    async function fetchAndRenderFaqs() {
        const faqs = await apiFetch('/api/faq');
        faqList.innerHTML = faqs.map(f => `
            <div class="feedback-card">
                <div><span style="background:#C48945; color:#fff; padding:2px 5px; border-radius:4px; font-size:12px;">${f.category}</span> ${f.isPinned?'<span style="color:red">[置頂]</span>':''} <b>${f.question}</b></div>
                <div class="pre-wrap" style="margin:10px 0; color:#555;">${f.answer}</div>
                <div style="text-align:right">
                    <button class="btn btn--brown" onclick='editFaq(${JSON.stringify(f).replace(/'/g, "&apos;")})'>編輯</button>
                    <button class="btn btn--red" onclick="delFaq('${f._id}')">刪除</button>
                </div>
            </div>`).join('');
    }
    window.delFaq = async (id) => { if(confirm('刪除？')) { await apiFetch(`/api/faq/${id}`, {method:'DELETE'}); fetchAndRenderFaqs(); } };
    window.editFaq = (f) => {
        faqForm.reset(); document.getElementById('faq-modal-title').textContent = '編輯問答';
        faqForm.faqId.value = f._id; faqForm.question.value = f.question; faqForm.answer.value = f.answer; faqForm.other_category.value = f.category; faqForm.isPinned.checked = f.isPinned;
        fetchFaqCategories().then(renderFaqCategoryBtns); faqModal.classList.add('is-visible');
    };
    document.getElementById('add-faq-btn').onclick = async () => { const cats = await fetchFaqCategories(); renderFaqCategoryBtns(cats); faqForm.reset(); document.getElementById('faq-modal-title').textContent = '新增問答'; faqForm.faqId.value = ''; faqModal.classList.add('is-visible'); };
    if(faqForm) faqForm.onsubmit = async (e) => {
        e.preventDefault(); if(!faqForm.other_category.value) return alert('分類必填');
        const id = faqForm.faqId.value;
        await apiFetch(id ? `/api/faq/${id}` : '/api/faq', { method: id ? 'PUT' : 'POST', body: JSON.stringify({ question: faqForm.question.value, answer: faqForm.answer.value, category: faqForm.other_category.value, isPinned: faqForm.isPinned.checked }) });
        faqModal.classList.remove('is-visible'); fetchAndRenderFaqs();
    };

    // 啟動檢查
    checkSession();
});