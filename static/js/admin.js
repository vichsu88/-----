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
                throw new Error(errorMessage || `請求失敗，狀態碼: ${response.status}`);
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
       2. DOM 元素與初始化
       ========================================= */
    const loginWrapper = document.getElementById('login-wrapper');
    const adminContent = document.getElementById('admin-content');
    const loginForm = document.getElementById('login-form');
    const passwordInput = document.getElementById('admin-password');
    const loginError = document.getElementById('login-error');
    const logoutBtn = document.getElementById('logout-btn');
    
    // 側邊選單相關
    const sidebar = document.getElementById('admin-sidebar');
    const sidebarToggle = document.getElementById('sidebar-toggle');
    const closeSidebarBtn = document.getElementById('close-sidebar');
    const sidebarOverlay = document.getElementById('sidebar-overlay');
    const pageTitleDisplay = document.getElementById('page-title-display');

    // 檢查登入狀態
    async function checkSession() {
        try {
            const data = await fetch('/api/session_check').then(res => res.json());
            if (data.logged_in) {
                showAdminContent();
            } else {
                showLogin();
            }
        } catch(e) { showLogin(); }
    }

    function showLogin() {
        loginWrapper.style.display = 'flex';
        adminContent.style.display = 'none';
        passwordInput.value = '';
    }

    function showAdminContent() {
        loginWrapper.style.display = 'none';
        adminContent.style.display = 'block';
        if (!adminContent.dataset.initialized) {
            setupNavigation();
            // 預設點擊第一個分頁
            const firstNav = document.querySelector('.nav-item');
            if(firstNav) firstNav.click();
            adminContent.dataset.initialized = 'true';
        }
    }

    /* =========================================
       3. 側邊導覽與手機版選單邏輯
       ========================================= */
    function setupNavigation() {
        const navItems = document.querySelectorAll('.nav-item');
        const tabContents = document.querySelectorAll('.tab-content');

        navItems.forEach(item => {
            item.addEventListener('click', () => {
                // 1. 切換按鈕狀態
                navItems.forEach(n => n.classList.remove('active'));
                item.classList.add('active');

                // 2. 切換內容顯示
                const targetId = item.dataset.tab;
                tabContents.forEach(c => c.classList.remove('active'));
                const targetContent = document.getElementById(targetId);
                if(targetContent) targetContent.classList.add('active');

                // 3. 更新標題
                if(pageTitleDisplay) pageTitleDisplay.textContent = item.dataset.title;

                // 4. 手機版點選後自動收起選單
                closeSidebar();

                // 5. 載入對應資料
                switch (targetId) {
                    case 'tab-links': 
                        fetchLinks(); 
                        break;
                    case 'tab-announcements': 
                        fetchAndRenderAnnouncements(); 
                        break;
                    case 'tab-feedback':
                        // 預設切到已刊登
                        const approvedBtn = document.querySelector('.sub-tab-btn[data-sub-tab="#approved-list-content"]');
                        if(approvedBtn) approvedBtn.click();
                        fetchApprovedFeedback();
                        fetchPendingFeedback();
                        break;
                    case 'tab-qa':
                        // 【修正重點】確保這裡呼叫的函式都存在
                        fetchFaqCategories().then(renderFaqCategoryBtns).then(fetchAndRenderFaqs);
                        break;
                    case 'tab-products': 
                        fetchAndRenderProducts(); 
                        break;
                    case 'tab-fund': 
                        fetchFundSettings(); 
                        break;
                }
            });
        });

        // 子分頁切換 (回饋管理用)
        const subTabs = document.querySelectorAll('.sub-tab-btn');
        const subContents = document.querySelectorAll('.sub-tab-content');
        subTabs.forEach(tab => {
            tab.addEventListener('click', () => {
                if(tab.classList.contains('faq-category-btn')) return; // 排除 FAQ 分類按鈕
                
                // 只針對同一組的 sub-tabs 操作
                const parent = tab.closest('.admin-sub-tabs');
                if(parent) {
                    parent.querySelectorAll('.sub-tab-btn').forEach(t => t.classList.remove('active'));
                } else {
                     // Fallback
                     subTabs.forEach(t => {
                        if(!t.classList.contains('faq-category-btn')) t.classList.remove('active');
                    });
                }
                
                subContents.forEach(c => c.classList.remove('active'));
                
                tab.classList.add('active');
                const target = document.querySelector(tab.dataset.subTab);
                if(target) target.classList.add('active');
            });
        });
    }

    function openSidebar() {
        sidebar.classList.add('open');
        sidebarOverlay.classList.add('active');
    }
    function closeSidebar() {
        sidebar.classList.remove('open');
        sidebarOverlay.classList.remove('active');
    }
    if(sidebarToggle) sidebarToggle.addEventListener('click', openSidebar);
    if(closeSidebarBtn) closeSidebarBtn.addEventListener('click', closeSidebar);
    if(sidebarOverlay) sidebarOverlay.addEventListener('click', closeSidebar);

    /* =========================================
       4. 登入登出邏輯
       ========================================= */
    loginForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        loginError.textContent = '';
        try {
            const response = await fetch('/api/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ password: passwordInput.value })
            });
            const data = await response.json();
            if (data.success) window.location.reload();
            else loginError.textContent = data.message || '登入失敗';
        } catch (err) { loginError.textContent = '連線錯誤'; }
    });

    logoutBtn.addEventListener('click', async () => {
        await apiFetch('/api/logout', { method: 'POST' });
        showLogin();
    });

    /* =========================================
       5. 商品管理 (含圖片)
       ========================================= */
    const productsListDiv = document.getElementById('products-list');
    const addProductBtn = document.getElementById('add-product-btn');
    const productModal = document.getElementById('product-modal');
    const productForm = document.getElementById('product-form');
    const productModalTitle = document.getElementById('product-modal-title');
    
    const productImageInput = document.getElementById('product-image-input');
    const previewImage = document.getElementById('preview-image');
    const removeImageBtn = document.getElementById('remove-image-btn');
    const imageHiddenInput = productForm.querySelector('input[name="image"]');

    productImageInput.addEventListener('change', function(e) {
        const file = e.target.files[0];
        if (!file) return;
        if (file.size > 2 * 1024 * 1024) {
            alert('圖片太大了！請將檔案縮小至 2MB 以內。');
            this.value = ''; return;
        }
        const reader = new FileReader();
        reader.onload = function(event) {
            previewImage.src = event.target.result;
            previewImage.style.display = 'block';
            removeImageBtn.style.display = 'inline-block';
            imageHiddenInput.value = event.target.result;
        };
        reader.readAsDataURL(file);
    });

    removeImageBtn.addEventListener('click', function() {
        productImageInput.value = '';
        imageHiddenInput.value = '';
        previewImage.src = '';
        previewImage.style.display = 'none';
        removeImageBtn.style.display = 'none';
    });

    async function fetchAndRenderProducts() {
        try {
            const products = await apiFetch('/api/products');
            if (products.length === 0) {
                productsListDiv.innerHTML = '<p style="grid-column: 1/-1; text-align:center;">目前沒有商品。</p>';
                return;
            }
            productsListDiv.innerHTML = products.map(p => {
                const safeP = JSON.stringify(p).replace(/'/g, "&apos;");
                const statusHtml = p.isActive 
                    ? '<span style="color:green; font-size:12px;">● 上架中</span>' 
                    : '<span style="color:red; font-size:12px;">● 已下架</span>';
                
                const imgHtml = p.image 
                    ? `<img src="${p.image}" style="width:100%; height:200px; object-fit:cover; border-radius:6px 6px 0 0;">`
                    : `<div style="width:100%; height:200px; background:#eee; display:flex; align-items:center; justify-content:center; color:#999; border-radius:6px 6px 0 0;">無圖片</div>`;

                return `
                <div class="feedback-card" style="padding:0; overflow:hidden; border:none; box-shadow:0 2px 8px rgba(0,0,0,0.1);">
                    ${imgHtml}
                    <div style="padding:15px;">
                        <div style="display:flex; justify-content:space-between; margin-bottom:5px;">
                            <span style="font-size:12px; color:#999; border:1px solid #ddd; padding:2px 6px; border-radius:4px;">${p.category}</span>
                            ${statusHtml}
                        </div>
                        <h4 style="margin:5px 0; font-size:18px;">${p.name}</h4>
                        <div style="color: var(--main-brown); font-weight:bold; font-size:16px;">NT$ ${p.price}</div>
                        <p style="font-size:13px; color:#666; margin:8px 0; height:40px; overflow:hidden;">${p.description || ''}</p>
                        
                        <div style="display:flex; gap:10px; margin-top:10px;">
                            <button class="btn btn--brown edit-product-btn" style="flex:1;" data-data='${safeP}'>編輯</button>
                            <button class="btn btn--red delete-product-btn" style="flex:1;" data-id="${p._id}">刪除</button>
                        </div>
                    </div>
                </div>`;
            }).join('');

            productsListDiv.querySelectorAll('.delete-product-btn').forEach(btn => {
                btn.addEventListener('click', async () => {
                    if(!confirm('確定要刪除此商品嗎？')) return;
                    try {
                        await apiFetch(`/api/products/${btn.dataset.id}`, { method: 'DELETE' });
                        fetchAndRenderProducts();
                    } catch(e) { alert(e.message); }
                });
            });
            productsListDiv.querySelectorAll('.edit-product-btn').forEach(btn => {
                btn.addEventListener('click', () => showProductModal(JSON.parse(btn.dataset.data)));
            });

        } catch (error) { console.error('商品載入失敗:', error); }
    }

    function showProductModal(product = null) {
        productForm.reset();
        previewImage.src = '';
        previewImage.style.display = 'none';
        removeImageBtn.style.display = 'none';
        imageHiddenInput.value = '';

        if (product) {
            productModalTitle.textContent = '編輯商品';
            productForm.productId.value = product._id;
            productForm.category.value = product.category;
            productForm.name.value = product.name;
            productForm.price.value = product.price;
            productForm.description.value = product.description;
            productForm.isActive.checked = product.isActive;
            if (product.image) {
                previewImage.src = product.image;
                previewImage.style.display = 'block';
                removeImageBtn.style.display = 'inline-block';
                imageHiddenInput.value = product.image;
            }
        } else {
            productModalTitle.textContent = '新增商品';
            productForm.productId.value = '';
            productForm.isActive.checked = true;
        }
        productModal.classList.add('is-visible');
    }

    if(addProductBtn) addProductBtn.addEventListener('click', () => showProductModal(null));

    productForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const id = productForm.productId.value;
        const formData = {
            category: productForm.category.value,
            name: productForm.name.value,
            price: productForm.price.value,
            description: productForm.description.value,
            isActive: productForm.isActive.checked,
            image: imageHiddenInput.value
        };
        try {
            if (id) await apiFetch(`/api/products/${id}`, { method: 'PUT', body: JSON.stringify(formData) });
            else await apiFetch('/api/products', { method: 'POST', body: JSON.stringify(formData) });
            productModal.classList.remove('is-visible');
            fetchAndRenderProducts();
        } catch (error) { alert('儲存失敗：' + error.message); }
    });

    /* =========================================
       6. 建廟基金 & 連結
       ========================================= */
    async function fetchFundSettings() {
        try {
            const data = await apiFetch('/api/fund-settings');
            document.getElementById('fund-goal').value = data.goal_amount;
            document.getElementById('fund-current').value = data.current_amount;
        } catch (error) { console.error(error); }
    }
    const fundForm = document.getElementById('fund-form');
    if(fundForm) fundForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        try {
            await apiFetch('/api/fund-settings', {
                method: 'POST',
                body: JSON.stringify({ 
                    goal_amount: document.getElementById('fund-goal').value,
                    current_amount: document.getElementById('fund-current').value 
                })
            });
            alert('設定已更新！');
        } catch (e) { alert('更新失敗：' + e.message); }
    });

    const linksListDiv = document.getElementById('links-list');
    async function fetchLinks() {
        try {
            const links = await apiFetch('/api/links');
            linksListDiv.innerHTML = links.map(link => `
                <div class="link-item" style="display:flex; gap:10px; margin-bottom:10px; align-items:center; background:#fff; padding:10px; border-radius:6px; box-shadow:0 1px 3px rgba(0,0,0,0.1);">
                    <span style="font-weight:bold; min-width:80px;">${link.name}</span>
                    <input type="text" value="${link.url}" readonly style="flex:1; padding:5px; border:1px solid #ddd; background:#eee; border-radius:4px;">
                    <button class="btn btn--brown edit-link-btn" data-id="${link._id}" data-url="${link.url}">修改</button>
                </div>
            `).join('');
            
            linksListDiv.querySelectorAll('.edit-link-btn').forEach(btn => {
                btn.addEventListener('click', async () => {
                    const newUrl = prompt('請輸入新網址', btn.dataset.url);
                    if(newUrl) {
                        await apiFetch(`/api/links/${btn.dataset.id}`, { method:'PUT', body:JSON.stringify({url:newUrl}) });
                        fetchLinks();
                    }
                });
            });
        } catch (e) { console.error(e); }
    }

    /* =========================================
       7. 信徒回饋管理
       ========================================= */
    const pendingListContainer = document.getElementById('pending-feedback-list');
    const approvedListContainer = document.getElementById('approved-feedback-list');
    
    async function fetchPendingFeedback() {
        try {
            const data = await apiFetch('/api/feedback/pending');
            pendingListContainer.innerHTML = data.length ? data.map(item => renderFeedbackCard(item, 'pending')).join('') : '<p style="text-align:center; color:#999;">目前無待審核回饋</p>';
            bindFeedbackButtons(pendingListContainer);
        } catch(e) { console.error(e); }
    }
    async function fetchApprovedFeedback() {
        try {
            const data = await apiFetch('/api/feedback/approved');
            approvedListContainer.innerHTML = data.length ? data.map(item => renderFeedbackCard(item, 'approved')).join('') : '<p style="text-align:center; color:#999;">目前無已刊登回饋</p>';
            bindFeedbackButtons(approvedListContainer);
        } catch(e) { console.error(e); }
    }

    function renderFeedbackCard(item, type) {
        // 判斷是否標記
        const isMarked = item.isMarked ? 'checked' : '';
        const markHtml = (type === 'approved') 
            ? `<label style="margin-right:10px; cursor:pointer;">
                 <input type="checkbox" class="mark-checkbox" data-id="${item._id}" ${isMarked}> 已寄出/已讀
               </label>` 
            : '';

        return `
            <div class="feedback-card" style="${item.isMarked ? 'background-color:#f0f9eb;' : ''}">
                <div class="feedback-card__header">
                   <span>${item.nickname} / ${item.category}</span>
                   <span>${item.createdAt}</span>
                </div>
                <div class="feedback-card__content" style="white-space: pre-line; margin:10px 0;">${item.content}</div>
                <div class="feedback-card__actions" style="align-items:center;">
                    ${markHtml}
                    ${type === 'pending' ? 
                      `<button class="btn btn--red action-btn" data-action="delete" data-id="${item._id}">刪除</button>
                       <button class="btn btn--brown action-btn" data-action="approve" data-id="${item._id}">同意刊登</button>` :
                      `<button class="btn btn--brown view-btn" data-data='${JSON.stringify(item).replace(/'/g, "&apos;")}' >查看詳細</button>`
                    }
                </div>
            </div>`;
    }

    function bindFeedbackButtons(container) {
        // 刪除/同意
        container.querySelectorAll('.action-btn').forEach(btn => {
            btn.addEventListener('click', async () => {
                const id = btn.dataset.id;
                const action = btn.dataset.action;
                if(!confirm('確定執行此動作？')) return;
                
                try {
                    if(action === 'approve') await apiFetch(`/api/feedback/${id}/approve`, { method:'PUT' });
                    if(action === 'delete') await apiFetch(`/api/feedback/${id}`, { method:'DELETE' });
                    
                    fetchPendingFeedback();
                    fetchApprovedFeedback();
                } catch(e) { alert(e.message); }
            });
        });
        
        // 標記 Checkbox
        container.querySelectorAll('.mark-checkbox').forEach(chk => {
            chk.addEventListener('change', async () => {
                try {
                    await apiFetch(`/api/feedback/${chk.dataset.id}/mark`, {
                        method: 'PUT',
                        body: JSON.stringify({ isMarked: chk.checked })
                    });
                    fetchApprovedFeedback(); // 重新整理以更新背景色
                } catch(e) { 
                    alert('標記失敗'); 
                    chk.checked = !chk.checked; 
                }
            });
        });

        // 查看詳細
        container.querySelectorAll('.view-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const item = JSON.parse(btn.dataset.data);
                document.getElementById('view-modal-body').innerHTML = `
                    <p><b>真實姓名:</b> ${item.realName || '無'}</p>
                    <p><b>電話:</b> ${item.phone || '無'}</p>
                    <p><b>地址:</b> ${item.address || '無'}</p>
                    <hr>
                    <p><b>內容:</b><br>${item.content}</p>
                `;
                
                // 綁定刪除按鈕
                const delBtn = document.getElementById('delete-feedback-btn');
                // 清除舊事件 (用 cloneNode 快速解法)
                const newDelBtn = delBtn.cloneNode(true);
                delBtn.parentNode.replaceChild(newDelBtn, delBtn);
                
                newDelBtn.onclick = async () => {
                    if(confirm('確定要刪除這則回饋嗎？此動作無法復原。')) {
                        await apiFetch(`/api/feedback/${item._id}`, {method:'DELETE'});
                        document.getElementById('view-modal').classList.remove('is-visible');
                        fetchApprovedFeedback();
                    }
                };
                document.getElementById('view-modal').classList.add('is-visible');
            });
        });
    }

    // 匯出功能
    document.getElementById('export-btn')?.addEventListener('click', async () => {
        const text = await apiFetch('/api/feedback/export-unmarked');
        document.getElementById('export-output-textarea').value = text;
        document.getElementById('export-modal').classList.add('is-visible');
    });
    
    document.getElementById('mark-all-btn')?.addEventListener('click', async () => {
        if(confirm('確定要將所有已審核的回饋標記為已讀？')) {
            await apiFetch('/api/feedback/mark-all-approved', {method:'PUT'});
            fetchApprovedFeedback();
        }
    });

    /* =========================================
       8. FAQ 常見問題 (修復重點)
       ========================================= */
    const faqListDiv = document.getElementById('faq-list');
    const faqCategoryBtnsDiv = document.getElementById('faq-category-btns');
    const addFaqBtn = document.getElementById('add-faq-btn');
    const faqModal = document.getElementById('faq-modal');
    const faqForm = document.getElementById('faq-form');

    // 取得分類
    async function fetchFaqCategories() {
        try {
            return await apiFetch('/api/faq/categories');
        } catch (e) {
            console.error(e);
            return [];
        }
    }

    // 渲染分類按鈕 (後台僅供顯示或簡單篩選，這裡做簡單顯示)
    function renderFaqCategoryBtns(categories) {
        if (!faqCategoryBtnsDiv) return;
        faqCategoryBtnsDiv.innerHTML = categories.map(cat => 
            `<span style="display:inline-block; padding:4px 8px; background:#e0e0e0; border-radius:12px; font-size:12px; color:#555;">${cat}</span>`
        ).join('');
    }

    // 取得並渲染列表
    async function fetchAndRenderFaqs() {
        if(!faqListDiv) return;
        try {
            const faqs = await apiFetch('/api/faq');
            faqListDiv.innerHTML = faqs.map(f => `
                <div class="feedback-card" style="position:relative;">
                    <div style="margin-bottom:5px;">
                        <span style="background:#C48945; color:#fff; font-size:12px; padding:2px 6px; border-radius:4px;">${f.category}</span>
                        ${f.isPinned ? '<span style="color:red; font-size:12px;">[置頂]</span>' : ''}
                    </div>
                    <div style="font-weight:bold; margin-bottom:5px;">Q: ${f.question}</div>
                    <div style="white-space:pre-line; color:#555;">A: ${f.answer}</div>
                    <button class="btn btn--red del-faq-btn" data-id="${f._id}" style="position:absolute; top:15px; right:15px; padding:4px 8px; font-size:12px;">刪除</button>
                </div>
            `).join('');

            // 綁定刪除
            faqListDiv.querySelectorAll('.del-faq-btn').forEach(btn => {
                btn.addEventListener('click', async () => {
                    if(confirm('確定刪除此問答？')) {
                        await apiFetch(`/api/faq/${btn.dataset.id}`, {method:'DELETE'});
                        // 重新載入分類與列表
                        fetchFaqCategories().then(renderFaqCategoryBtns).then(fetchAndRenderFaqs);
                    }
                });
            });
        } catch(e) { console.error(e); }
    }

    if(addFaqBtn) addFaqBtn.addEventListener('click', async () => {
        // 更新 Modal 中的分類建議按鈕
        const categories = await fetchFaqCategories();
        const container = document.getElementById('faq-modal-category-btns');
        if(container) {
            container.innerHTML = categories.map(c => 
                `<button type="button" class="btn" style="background:#eee; color:#333; font-size:12px; padding:4px 8px;" onclick="this.form.other_category.value='${c}'">${c}</button>`
            ).join('');
        }
        faqForm.reset();
        faqModal.classList.add('is-visible');
    });

    if(faqForm) faqForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const category = faqForm.other_category.value.trim();
        if(!category) { alert('請輸入或選擇分類'); return; }

        try {
            await apiFetch('/api/faq', {
                method: 'POST',
                body: JSON.stringify({
                    question: faqForm.question.value,
                    answer: faqForm.answer.value,
                    category: category,
                    isPinned: faqForm.isPinned.checked
                })
            });
            faqModal.classList.remove('is-visible');
            fetchFaqCategories().then(renderFaqCategoryBtns).then(fetchAndRenderFaqs);
        } catch(err) { alert(err.message); }
    });

    /* =========================================
       9. 最新消息公告 (修復重點)
       ========================================= */
    const announcementsListDiv = document.getElementById('announcements-list');
    const addAnnBtn = document.getElementById('add-announcement-btn');
    const annModal = document.getElementById('announcement-modal');
    const annForm = document.getElementById('announcement-form');

    async function fetchAndRenderAnnouncements() {
        if(!announcementsListDiv) return;
        try {
            const data = await apiFetch('/api/announcements');
            announcementsListDiv.innerHTML = data.map(a => `
                <div class="feedback-card">
                   <div style="font-size:12px; color:#888;">
                       ${a.date} 
                       ${a.isPinned ? '<span style="color:red; font-weight:bold; margin-left:5px;">[置頂]</span>' : ''}
                   </div>
                   <h3 style="margin:5px 0;">${a.title}</h3>
                   <div style="white-space:pre-line; color:#555; max-height:80px; overflow:hidden;">${a.content}</div>
                   <div style="text-align:right; margin-top:10px;">
                     <button class="btn btn--red del-ann-btn" data-id="${a._id}">刪除</button>
                   </div>
                </div>`).join('');
             
            announcementsListDiv.querySelectorAll('.del-ann-btn').forEach(b => {
                b.onclick = async () => {
                     if(confirm('確定刪除此公告？')) { 
                         await apiFetch(`/api/announcements/${b.dataset.id}`, {method:'DELETE'}); 
                         fetchAndRenderAnnouncements(); 
                     }
                };
            });
        } catch(e) { console.error(e); }
    }
    
    if(addAnnBtn) addAnnBtn.onclick = () => {
        annForm.reset();
        annModal.classList.add('is-visible');
    };
    
    if(annForm) annForm.onsubmit = async (e) => {
        e.preventDefault();
        try {
            await apiFetch('/api/announcements', {
                method:'POST', 
                body: JSON.stringify({
                    date: annForm.date.value, 
                    title: annForm.title.value, 
                    content: annForm.content.value, 
                    isPinned: annForm.isPinned.checked
                })
            });
            annModal.classList.remove('is-visible');
            fetchAndRenderAnnouncements();
        } catch(err) { alert(err.message); }
    };

    // 通用 Modal 關閉
    document.querySelectorAll('.admin-modal-overlay').forEach(modal => {
        modal.addEventListener('click', (e) => {
            if (e.target.classList.contains('modal-close-btn') || e.target === modal) {
                modal.classList.remove('is-visible');
            }
        });
    });

    // --- 啟動 ---
    checkSession();
});