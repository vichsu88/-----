document.addEventListener('DOMContentLoaded', () => {

    /* =========================================
       1. 核心 API 與全域工具 (Core)
       ========================================= */
    const Core = {
        getCsrfToken: () => document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') || '',
        
        async apiFetch(url, options = {}) {
            const headers = { 
                'Content-Type': 'application/json', 
                'X-CSRFToken': this.getCsrfToken(), 
                ...(options.headers || {}) 
            };
            try {
                const response = await fetch(url, { ...options, credentials: 'include', headers });
                if (!response.ok) throw new Error((await response.text()) || `Error: ${response.status}`);
                const contentType = response.headers.get('content-type');
                return contentType?.includes('json') ? response.json() : response.text();
            } catch (error) { 
                console.error('API Fetch Error:', error); 
                try {
                    const errObj = JSON.parse(error.message);
                    alert(errObj.message || '發生錯誤');
                } catch(e) {
                    alert('操作失敗，請檢查網路或權限'); 
                }
                throw error; 
            }
        },

        confirmAction(message, actionCallback) {
            if (confirm(message)) actionCallback();
        },
        
        // 工具：安全地序列化資料至 HTML 屬性
        safeStringify(obj) {
            return JSON.stringify(obj).replace(/'/g, "&apos;");
        }
    };

    /* =========================================
       2. 介面與導覽控制 (UI & Navigation)
       ========================================= */
    const UI = {
        loginWrapper: document.getElementById('login-wrapper'),
        adminContent: document.getElementById('admin-content'),
        pageTitleDisplay: document.getElementById('page-title-display'),
        sidebar: document.getElementById('admin-sidebar'),
        overlay: document.getElementById('sidebar-overlay'),

        init() {
            this.setupNavigation();
            this.setupModals();
            this.setupSidebar();
        },

        showLogin() {
            if(this.loginWrapper) this.loginWrapper.style.display = 'flex';
            if(this.adminContent) this.adminContent.style.display = 'none';
        },

        showAdminContent() {
            if(this.loginWrapper) this.loginWrapper.style.display = 'none';
            if(this.adminContent) {
                this.adminContent.style.display = 'block';
                if (!this.adminContent.dataset.initialized) {
                    document.querySelector('.nav-item[data-tab="tab-products"]')?.click();
                    this.adminContent.dataset.initialized = 'true';
                    if (window.updateNotificationBadges) window.updateNotificationBadges();
                }
            }
        },

        setupNavigation() {
            // 使用策略模式 (Object Map) 優化 If-Else 鏈
            const tabActions = {
                'tab-products': () => ProductManager.fetchList(),
                'tab-donations': () => window.switchDonationTab('incense'),
                'tab-orders': () => OrderManager.fetchList(),
                'tab-feedback': () => FeedbackManager.fetchList(),
                'tab-fund': () => { SettingsManager.fetchFund(); ContentManager.fetchAnnouncements(); },
                'tab-qa': () => ContentManager.fetchFaqs(),
                'tab-links': () => { SettingsManager.fetchLinks(); SettingsManager.fetchBankInfo(); }
            };

            const navItems = document.querySelectorAll('.nav-item');
            const tabContents = document.querySelectorAll('.tab-content');

            navItems.forEach(btn => {
                btn.addEventListener('click', () => {
                    // UI 切換
                    navItems.forEach(el => el.classList.remove('active'));
                    tabContents.forEach(el => el.classList.remove('active'));
                    
                    btn.classList.add('active');
                    const tabId = btn.dataset.tab;
                    document.getElementById(tabId)?.classList.add('active');
                    if (this.pageTitleDisplay) this.pageTitleDisplay.textContent = btn.innerText;
                    
                    if (window.innerWidth <= 768) this.toggleSidebar(false);

                    // 執行對應的資料載入
                    if(tabActions[tabId]) tabActions[tabId]();
                });
            });
        },

        setupSidebar() {
            const toggleBtn = document.getElementById('sidebar-toggle');
            if (toggleBtn) toggleBtn.onclick = () => this.toggleSidebar(true);
            if (this.overlay) this.overlay.onclick = () => this.toggleSidebar(false);
        },

        toggleSidebar(show) {
            this.sidebar?.classList.toggle('open', show);
            if(this.overlay) this.overlay.style.display = show ? 'block' : 'none';
        },

        setupModals() {
            document.querySelectorAll('.admin-modal-overlay').forEach(m => {
                m.addEventListener('click', (e) => { 
                    if(e.target === m || e.target.classList.contains('modal-close-btn')) {
                        m.classList.remove('is-visible'); 
                    }
                });
            });
        },

        openModal(modalId) { document.getElementById(modalId)?.classList.add('is-visible'); },
        closeModal(modalId) { document.getElementById(modalId)?.classList.remove('is-visible'); }
    };

    /* =========================================
       3. 身份驗證 (Auth)
       ========================================= */
    const Auth = {
        async checkSession() {
            try {
                const data = await fetch('/api/session_check').then(res => res.json());
                data.logged_in ? UI.showAdminContent() : UI.showLogin();
            } catch(e) { 
                UI.showLogin(); 
            }
        },
        
        async login(password) {
            try {
                const res = await fetch('/api/login', { 
                    method: 'POST', 
                    headers: { 'Content-Type': 'application/json' }, 
                    body: JSON.stringify({ password }) 
                });
                const data = await res.json();
                if (data.success) location.reload(); 
                else {
                    const errEl = document.getElementById('login-error');
                    if(errEl) errEl.textContent = '密碼錯誤';
                }
            } catch (err) { alert('連線錯誤'); }
        },

        async logout() {
            await Core.apiFetch('/api/logout', { method: 'POST' }); 
            location.reload();
        }
    };

    document.getElementById('login-form')?.addEventListener('submit', (e) => {
        e.preventDefault();
        Auth.login(document.getElementById('admin-password').value);
    });
    const logoutBtn = document.getElementById('logout-btn');
    if(logoutBtn) logoutBtn.onclick = Auth.logout;

    /* =========================================
       4. 商品管理 (Product Manager)
       ========================================= */
    const ProductManager = {
        listEl: document.getElementById('products-list'),
        form: document.getElementById('product-form'),
        variantsContainer: document.getElementById('variants-container'),
        imgPreview: document.getElementById('preview-image'),
        imgHidden: document.querySelector('#product-form [name="image"]'),

        init() {
            const imgInput = document.getElementById('product-image-input');
            const addVarBtn = document.getElementById('add-variant-btn');
            const addProdBtn = document.getElementById('add-product-btn');

            if(imgInput) imgInput.onchange = this.handleImageUpload.bind(this);
            if(addVarBtn) addVarBtn.onclick = () => this.addVariantRow();
            if(addProdBtn) addProdBtn.onclick = () => this.showModal();
            if(this.form) this.form.onsubmit = this.saveProduct.bind(this);

            // 使用事件委派優化按鈕點擊效能
            if(this.listEl) {
                this.listEl.addEventListener('click', (e) => {
                    if (e.target.classList.contains('del-prod')) {
                        Core.confirmAction('刪除？', async () => {
                            await Core.apiFetch(`/api/products/${e.target.dataset.id}`, {method:'DELETE'}); 
                            this.fetchList(); 
                        });
                    } else if (e.target.classList.contains('edit-prod')) {
                        this.showModal(JSON.parse(e.target.dataset.data));
                    }
                });
            }
        },

        async handleImageUpload(e) {
            const file = e.target.files[0];
            if(!file) return;

            const localReader = new FileReader();
            localReader.onload = (ev) => {
                this.imgPreview.src = ev.target.result;
                this.imgPreview.style.display = 'block';
            };
            localReader.readAsDataURL(file);

            const formData = new FormData();
            formData.append('file', file);
            formData.append('upload_preset', 'temple_upload');

            const submitBtn = document.querySelector('#product-form button[type="submit"]');
            
            try {
                if(submitBtn) { 
                    submitBtn.dataset.originalText = submitBtn.textContent;
                    submitBtn.textContent = '圖片上傳中...'; 
                    submitBtn.disabled = true; 
                    submitBtn.style.opacity = '0.7';
                }

                const res = await fetch(`https://api.cloudinary.com/v1_1/dsvj25pma/image/upload`, {
                    method: 'POST', body: formData
                });
                const data = await res.json();

                if(data.secure_url) {
                    this.imgHidden.value = data.secure_url; 
                } else {
                    alert('圖片上傳失敗');
                }
            } catch (err) {
                alert('圖片上傳發生錯誤');
            } finally {
                if(submitBtn) { 
                    submitBtn.textContent = submitBtn.dataset.originalText || '儲存商品'; 
                    submitBtn.disabled = false; 
                    submitBtn.style.opacity = '1';
                }
            }
        },

        addVariantRow(name='', price='') {
            if(!this.variantsContainer) return;
            const div = document.createElement('div');
            div.className = 'variant-row d-flex gap-10 mt-10';
            div.innerHTML = `
                <input type="text" placeholder="規格名稱" class="var-name mb-0" value="${name}" style="flex:2;">
                <input type="number" placeholder="價格" class="var-price mb-0" value="${price}" style="flex:1;">
                <button type="button" class="btn btn--red remove-var-btn" style="padding:8px 12px;">×</button>
            `;
            div.querySelector('.remove-var-btn').onclick = () => div.remove();
            this.variantsContainer.appendChild(div);
        },

        showModal(p = null) {
            this.form.reset(); 
            this.variantsContainer.innerHTML = ''; 
            this.imgPreview.style.display = 'none'; 
            this.imgHidden.value = '';
            this.form.seriesSort.value = 10;

            const titleEl = document.getElementById('product-modal-title');

            if (p) {
                if(titleEl) titleEl.textContent = '編輯商品';
                this.form.productId.value = p._id;
                this.form.category.value = p.category;
                this.form.name.value = p.name;
                this.form.description.value = p.description;
                this.form.isActive.checked = p.isActive;
                this.form.isDonation.checked = p.isDonation || false;
                this.form.series.value = p.series || '';
                this.form.seriesSort.value = p.seriesSort || 0;
                
                if (p.image) { 
                    this.imgPreview.src = p.image; 
                    this.imgPreview.style.display = 'block'; 
                    this.imgHidden.value = p.image; 
                }
                if (p.variants?.length > 0) {
                    p.variants.forEach(v => this.addVariantRow(v.name, v.price));
                } else {
                    this.addVariantRow('標準', p.price);
                }
            } else {
                if(titleEl) titleEl.textContent = '新增商品';
                this.form.productId.value = '';
                this.addVariantRow();
            }
            UI.openModal('product-modal');
        },

        async fetchList() {
            if(!this.listEl) return;
            try {
                const products = await Core.apiFetch('/api/products');
                const groups = products.reduce((acc, p) => {
                    (acc[p.category] = acc[p.category] || []).push(p);
                    return acc;
                }, {});

                let html = '';
                for (const [cat, items] of Object.entries(groups)) {
                    html += `<h3 style="background:#eee; padding:10px; border-radius:5px; color:#555;">📂 ${cat}</h3>`;
                    html += items.map(p => {
                        const varsHtml = p.variants?.length > 0 
                            ? p.variants.map(v => `<small>${v.name}: $${v.price}</small>`).join(' | ')
                            : `<small>單價: $${p.price}</small>`;

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
                                <button class="btn btn--brown edit-prod" data-data='${Core.safeStringify(p)}'>編輯</button>
                                <button class="btn btn--red del-prod" data-id="${p._id}">刪除</button>
                            </div>
                        </div>`;
                    }).join('');
                }
                this.listEl.innerHTML = html || '<p>目前無商品</p>';
            } catch(e) { 
                this.listEl.innerHTML = '載入失敗'; 
            }
        },

        async saveProduct(e) {
            e.preventDefault();
            const variants = Array.from(this.variantsContainer.querySelectorAll('.variant-row'))
                .map(row => ({
                    name: row.querySelector('.var-name').value.trim(),
                    price: parseInt(row.querySelector('.var-price').value)
                }))
                .filter(v => v.name && !isNaN(v.price));

            if(variants.length === 0) return alert('請至少輸入一種規格與價格');

            const data = {
                category: this.form.category.value,
                name: this.form.name.value,
                description: this.form.description.value,
                image: this.imgHidden.value,
                series: this.form.series.value.trim(),
                seriesSort: parseInt(this.form.seriesSort.value) || 0,
                isActive: this.form.isActive.checked,
                isDonation: this.form.isDonation.checked,
                variants: variants,
                price: variants[0].price
            };
            
            const id = this.form.productId.value;
            await Core.apiFetch(id ? `/api/products/${id}` : '/api/products', { 
                method: id ? 'PUT' : 'POST', 
                body: JSON.stringify(data) 
            });
            UI.closeModal('product-modal');
            this.fetchList();
        }
    };
    ProductManager.init();

    /* =========================================
       5. 訂單與捐贈管理 (Orders & Donations)
       ========================================= */
    const OrderManager = {
        async fetchList() {
            const listEl = document.getElementById('orders-list');
            if(!listEl) return;
            
            try {
                const orders = await Core.apiFetch('/api/orders');
                
                // 一次迴圈完成三種狀態的分類，提升效能
                const categorizedOrders = orders.reduce((acc, o) => {
                    if (['pending', 'paid', 'shipped'].includes(o.status)) {
                        acc[o.status].push(o);
                    }
                    return acc;
                }, { pending: [], paid: [], shipped: [] });

                listEl.innerHTML = `
                    <div style="display:flex; flex-direction:column; gap:30px;">
                        <div>
                            <h3 style="background:#dc3545; color:white; padding:10px; border-radius:5px; margin:0 0 10px 0;">1. 未付款 (${categorizedOrders.pending.length})</h3>
                            ${categorizedOrders.pending.length ? categorizedOrders.pending.map(o => this.renderCard(o, 'pending')).join('') : '<p style="padding:10px;">無</p>'}
                        </div>
                        <div>
                            <h3 style="background:#28a745; color:white; padding:10px; border-radius:5px; margin:0 0 10px 0;">2. 待出貨 (${categorizedOrders.paid.length})</h3>
                            ${categorizedOrders.paid.length ? categorizedOrders.paid.map(o => this.renderCard(o, 'toship')).join('') : '<p style="padding:10px;">無</p>'}
                        </div>
                        <div>
                            <h3 style="background:#007bff; color:white; padding:10px; border-radius:5px; margin:0 0 10px 0;">3. 已出貨 (${categorizedOrders.shipped.length})</h3>
                            <div style="text-align:right;"><button class="btn btn--red" onclick="cleanupShipped()">🗑️ 清除舊單</button></div>
                            ${categorizedOrders.shipped.length ? categorizedOrders.shipped.map(o => this.renderCard(o, 'shipped')).join('') : '<p style="padding:10px;">無</p>'}
                        </div>
                    </div>
                `;

                if (window.updateNotificationBadges) window.updateNotificationBadges();
            } catch(e) {
                listEl.innerHTML = '<p>載入失敗</p>';
            }
        },

        renderCard(o, type) {
            let btns = `<button class="btn btn--grey" onclick='viewOrderDetails(${Core.safeStringify(o)})'>🔍 查看詳情</button>`; 
            if(type === 'pending') {
                btns += `<button class="btn btn--green" onclick="confirmOrder('${o._id}', '${o.orderId}')">✅ 確認收款</button>
                         <button class="btn btn--red" onclick="delOrder('${o._id}', 'shop')">刪除</button>`;
            } else if(type === 'toship') {
                btns += `<button class="btn btn--blue" onclick="shipOrder('${o._id}')">🚚 出貨</button>`;
            }
            const borderColor = type === 'pending' ? '#dc3545' : (type === 'toship' ? '#28a745' : '#007bff');
            
            return `
            <div class="feedback-card" style="border-left:5px solid ${borderColor};">
                <div style="display:flex; justify-content:space-between;"><b>${o.orderId}</b> <small>${o.createdAt}</small></div>
                <div>
                    ${o.customer.shippingMethod === '711' ? '<span style="color:#28a745; font-weight:bold;">[7-11]</span>' : ''}
                    ${o.customer.name} / ${o.customer.phone} / $${o.total}
                </div>
                <div style="color:#666;">${o.items.map(i => `${i.name} x${i.qty}`).join(', ')}</div>
                <div style="text-align:right; margin-top:10px;">${btns}</div>
            </div>`;
        }
    };

    /* =========================================
       6. 信徒回饋管理 (Feedback)
       ========================================= */
    const FeedbackManager = {
        async fetchList() {
            const pendingList = document.getElementById('fb-pending-list');
            const approvedList = document.getElementById('fb-approved-list');
            const sentList = document.getElementById('fb-sent-list');
            if(!pendingList) return;
            
            const [pending, approved, sent] = await Promise.all([
                Core.apiFetch('/api/feedback/status/pending'),
                Core.apiFetch('/api/feedback/status/approved'),
                Core.apiFetch('/api/feedback/status/sent')
            ]);

            const statsDiv = document.getElementById('fb-stats-bar');
            if(statsDiv) {
                statsDiv.innerHTML = `
                    <span style="background:#6c757d; color:white; padding:8px 15px; border-radius:20px; font-weight:bold;">
                        總回饋數: ${pending.length + approved.length + sent.length} 筆
                    </span>
                    <button class="btn btn--brown" onclick="printFeedbackList()">匯出回饋</button>
                `;
            }

            pendingList.innerHTML = pending.length ? pending.map(i => `
                <div class="feedback-card" style="border-left:5px solid #dc3545;">
                    <div style="font-weight:bold; margin-bottom:12px; font-size: 16px; border-bottom: 1px solid #eee; padding-bottom: 8px;">
                        👤 暱稱：${i.nickname} ${i.has_received ? '<span style="color:#dc3545; font-weight:bold; font-size:13px; margin-left:10px;">[⚠️ 已領取過小神衣]</span>' : ''}
                    </div>
                    <div style="background:#f9f9f9; padding:12px; border-radius:5px; margin-bottom:15px;">
                        <div class="pre-wrap" style="color:#444;">${i.content}</div>
                    </div>
                    <div style="text-align:right;">
                        <button class="btn btn--grey" onclick='editFb(${Core.safeStringify(i)})'>編輯</button>
                        <button class="btn btn--green" onclick="approveFb('${i._id}')">✅ 核准 (寄信)</button>
                        <button class="btn btn--red" onclick="delFb('${i._id}')">🗑️ 刪除</button>
                    </div>
                </div>`).join('') : '<p>無</p>';

            if(approvedList) approvedList.innerHTML = approved.length ? approved.map(i => `
                <div class="feedback-card" style="border-left:5px solid #28a745;">
                    <div style="display:flex; justify-content:space-between; align-items:center; border-bottom: 1px solid #eee; padding-bottom: 10px; margin-bottom: 10px;">
                        <strong>編號: ${i.feedbackId || '無'}</strong>
                        <span style="color:#888; font-size:13px;">${i.approvedAt || ''}</span>
                    </div>
                    <div style="margin-bottom: 15px; line-height: 1.8;">
                        <strong>${i.realName}</strong> (農曆生日: ${i.lunarBirthday || '未提供'}) 
                        ${i.has_received ? '<span style="color:#dc3545; font-weight:bold; font-size:13px; margin-left:10px;">[⚠️ 已領取過小神衣]</span>' : ''}<br>
                        <span style="color:#666; font-size:14px;">📍 ${i.address}</span>
                    </div>
                    <div style="display: flex; justify-content: space-between; align-items: center; border-top: 1px solid #eee; padding-top: 15px;">
                        <button class="btn btn--grey" onclick='viewFbDetail(${Core.safeStringify(i)})'>📖 查看回饋內容</button>
                        <button class="btn btn--blue" onclick="shipGift('${i._id}')">🎁 填寫物流並寄出</button>
                    </div>
                </div>`).join('') : '<p>無</p>';
                
            if(sentList) sentList.innerHTML = sent.length ? sent.map(i => `
                <div class="feedback-card" style="border-left:5px solid #007bff; background:#f0f0f0; cursor:pointer;" 
                     onmouseover="this.style.background='#e2e6ea'" onmouseout="this.style.background='#f0f0f0'"
                     onclick='viewFbDetail(${Core.safeStringify(i)})'>
                    <div style="display:flex; justify-content:space-between; align-items:center;">
                        <span style="font-size:16px; font-weight:bold; color:#333;">${i.nickname}</span>
                        <span style="background:#dbeafe; color:#007bff; padding:2px 8px; border-radius:12px; font-size:12px;">${i.feedbackId || '無編號'}</span>
                    </div>
                    <div style="text-align:right; font-size:12px; color:#888; margin-top:5px;">
                        寄出日: ${i.sentAt || '未知'} (點擊查看詳情)
                    </div>
                </div>`).join('') : '<p>無</p>';
        }
    };

    /* =========================================
       7. 系統設定與公告 (Settings & Content)
       ========================================= */
    const SettingsManager = {
        async fetchLinks() {
            const links = await Core.apiFetch('/api/links');
            const el = document.getElementById('links-list');
            if(el) el.innerHTML = links.map(l => `
                <div style="margin-bottom:10px; display:flex; align-items:center; gap:10px;">
                    <b>${l.name}</b> 
                    <input value="${l.url}" readonly style="flex:1; padding:8px; border:1px solid #ddd; background:#f9f9f9;"> 
                    <button class="btn btn--brown" onclick="updLink('${l._id}', '${l.url}')">修改</button>
                </div>`).join('');
        },

        async fetchBankInfo() {
            const form = document.getElementById('bank-form');
            if(!form) return;
            try {
                const data = await Core.apiFetch('/api/settings/bank');
                form.shop_bankCode.value = data.shop?.bankCode || '';
                form.shop_bankName.value = data.shop?.bankName || '';
                form.shop_account.value = data.shop?.account || '';
                form.fund_bankCode.value = data.fund?.bankCode || '';
                form.fund_bankName.value = data.fund?.bankName || '';
                form.fund_account.value = data.fund?.account || '';
            } catch(e) {}
        },

        async fetchFund() {
            const data = await Core.apiFetch('/api/fund-settings');
            const goalInput = document.getElementById('fund-goal');
            const currentInput = document.getElementById('fund-current');
            if(goalInput) goalInput.value = data.goal_amount;
            if(currentInput) currentInput.value = data.current_amount;
        }
    };

    const ContentManager = {
        async fetchAnnouncements() {
            const data = await Core.apiFetch('/api/announcements');
            const el = document.getElementById('announcements-list');
            if(el) el.innerHTML = data.map(a => `
                <div class="feedback-card">
                    <div><small>${a.date}</small> <b>${a.title}</b> ${a.isPinned?'<span style="color:red">[置頂]</span>':''}</div>
                    <div class="pre-wrap" style="margin:10px 0;">${a.content}</div>
                    <div style="text-align:right;">
                        <button class="btn btn--brown" onclick='editAnn(${Core.safeStringify(a)})'>編輯</button>
                        <button class="btn btn--red" onclick="delAnn('${a._id}')">刪除</button>
                    </div>
                </div>`).join('');
        },

        async fetchFaqs() {
            const faqs = await Core.apiFetch('/api/faq');
            const el = document.getElementById('faq-list');
            if(el) el.innerHTML = faqs.map(f => `
                <div class="feedback-card">
                    <div><span style="background:#C48945; color:#fff; padding:2px 5px; border-radius:4px; font-size:12px;">${f.category}</span> ${f.isPinned?'<span style="color:red">[置頂]</span>':''} <b>${f.question}</b></div>
                    <div class="pre-wrap" style="margin:10px 0; color:#555;">${f.answer}</div>
                    <div style="text-align:right">
                        <button class="btn btn--brown" onclick='editFaq(${Core.safeStringify(f)})'>編輯</button>
                        <button class="btn btn--red" onclick="delFaq('${f._id}')">刪除</button>
                    </div>
                </div>`).join('');
        }
    };

    // 表單綁定
    const bankForm = document.getElementById('bank-form');
    if(bankForm) {
        bankForm.onsubmit = async (e) => {
            e.preventDefault();
            const payload = {
                shop: { bankCode: bankForm.shop_bankCode.value, bankName: bankForm.shop_bankName.value, account: bankForm.shop_account.value },
                fund: { bankCode: bankForm.fund_bankCode.value, bankName: bankForm.fund_bankName.value, account: bankForm.fund_account.value }
            };
            await Core.apiFetch('/api/settings/bank', {method:'POST', body:JSON.stringify(payload)});
            alert('匯款資訊已更新 (已區分 一般/建廟)');
        };
    }

    const fundForm = document.getElementById('fund-form');
    if(fundForm) {
        fundForm.onsubmit = async (e) => {
            e.preventDefault();
            await Core.apiFetch('/api/fund-settings', {
                method:'POST', body:JSON.stringify({ goal_amount: document.getElementById('fund-goal').value })
            });
            alert('更新成功！目前的線上募款金額已同步刷新。');
            SettingsManager.fetchFund();
        };
    }

    /* =========================================
       8. 導出所有 HTML 內聯事件綁定 (Global Bindings)
       ========================================= */
       
    // ▼▼▼ 背景更新通知標籤的函式 ▼▼▼
    window.updateNotificationBadges = async () => {
        try {
            // Promise.all 並行請求提升網路效率
            const [orders, donations] = await Promise.all([
                Core.apiFetch('/api/orders'),
                Core.apiFetch('/api/donations/admin')
            ]);

            const pendingOrders = orders.filter(o => o.status === 'pending').length;
            const badgeOrders = document.getElementById('badge-orders');
            if (badgeOrders) badgeOrders.classList.toggle('d-none', pendingOrders === 0);

            const pendingDonations = donations.filter(o => o.status === 'pending').length;
            const badgeDonations = document.getElementById('badge-donations');
            if (badgeDonations) badgeDonations.classList.toggle('d-none', pendingDonations === 0);

        } catch (e) {
            console.error('更新通知標籤失敗', e);
        }
    };

    // --- Utils ---
    window.toggleContent = function(id, btn) {
        const box = document.getElementById(`content-${id}`);
        if(box) {
            box.classList.toggle('expanded');
            btn.textContent = box.classList.contains('expanded') ? '收起內容' : '顯示完整內容';
        }
    };

    // --- Donations ---
    window.switchDonationTab = (type) => {
        document.querySelectorAll('.sub-tab-btn').forEach(b => b.classList.remove('active'));
        if(window.event?.target?.classList) window.event.target.classList.add('active');
        
        ['incense', 'fund', 'committee'].forEach(tab => {
            const el = document.getElementById(`subtab-${tab}`);
            if(el) el.style.display = type === tab ? 'block' : 'none';
        });
        
        window.fetchDonations(type);
    };

    window.exportDonationList = async (type) => {
        try {
            const res = await fetch('/api/donations/export-txt', {
                method: 'POST',
                headers: { 
                    'Content-Type': 'application/json',
                    'X-CSRFToken': Core.getCsrfToken() 
                },
                body: JSON.stringify({ type: type })
            });
            
            if (res.status === 404) return alert('目前無資料可供匯出');
            if (!res.ok) throw new Error('匯出失敗');
            
            const blob = await res.blob();
            const a = document.createElement('a'); 
            a.href = URL.createObjectURL(blob); 
            
            let typeName = type === 'fund' ? '建廟基金' : (type === 'committee' ? '委員會' : '日常捐香');
            a.download = `${typeName}名單_${new Date().toISOString().slice(0,10)}.txt`; 
            a.click();
        } catch(e) { 
            alert('匯出發生錯誤，請檢查網路或系統狀態'); 
        }
    };

    window.fetchDonations = async (type) => {
        if(!type) {
            if (document.getElementById('subtab-fund')?.style.display === 'block') type = 'fund';
            else if (document.getElementById('subtab-committee')?.style.display === 'block') type = 'committee';
            else type = 'donation';
        }

        const containerMap = { 'donation': 'incense-list', 'fund': 'fund-list', 'committee': 'committee-list' };
        const container = document.getElementById(containerMap[type]);
        if(!container) return;
        
        container.innerHTML = '<p>載入中...</p>';
        let url = `/api/donations/admin?type=${type}`;
        
        if (type === 'donation') {
            const filterEl = document.getElementById('incense-report-filter');
            if (filterEl && filterEl.value !== '') url += `&reported=${filterEl.value}`;
        }

        try {
            const orders = await Core.apiFetch(url);
            
            // 一次過濾分群提升效率
            const grouped = orders.reduce((acc, o) => {
                if (o.status === 'pending' || o.status === 'paid') acc[o.status].push(o);
                return acc;
            }, { pending: [], paid: [] });

            if (type === 'donation') renderIncenseList(grouped.pending, grouped.paid, container);
            else renderFundList(grouped.pending, grouped.paid, container, type); 

            if (window.updateNotificationBadges) window.updateNotificationBadges();

        } catch(e) { container.innerHTML = '載入失敗'; }
    };

    window.confirmDonation = (id, type) => {
        Core.confirmAction('確認收到款項？將寄發電子感謝狀。', async () => {
            await Core.apiFetch(`/api/orders/${id}/confirm`, {method:'PUT'});
            window.fetchDonations(type);
        });
    };

    window.viewDonationDetail = (o) => {
        const modal = document.getElementById('donation-detail-modal');
        const body = document.getElementById('donation-detail-body');
        if(!modal || !body) return;

        const itemsStr = o.items.map(i => `${i.name} x${i.qty}`).join('、');

        body.innerHTML = `
            <div style="border-bottom:1px solid #eee; padding-bottom:10px; margin-bottom:10px;">
                <p style="margin:0 0 5px 0;"><strong>單號：</strong> ${o.orderId}</p>
                <p style="margin:0;"><strong>送出日期：</strong> ${o.createdAt}</p>
            </div>
            <p><strong>姓名：</strong> ${o.customer.name}</p>
            <p><strong>電話：</strong> ${o.customer.phone || '無'}</p>
            <p><strong>農曆生日：</strong> ${o.customer.lunarBirthday || '未提供'}</p>
            <p><strong>地址：</strong> ${o.customer.address || '無'}</p>
            <p><strong>匯款後五碼：</strong> ${o.customer.last5 || '無'}</p>
            <div style="background:#f9f9f9; padding:15px; border-radius:8px; border:1px solid #ddd; margin-top:15px;">
                <strong style="color:#C48945;">護持內容：</strong>
                <p style="margin:5px 0;">${itemsStr}</p>
                <strong style="color:#C48945; font-size: 18px;">總金額：$${o.total}</strong>
            </div>
        `;
        modal.classList.add('is-visible');
    };

    window.printRedPaper = async () => {
        const orders = await Core.apiFetch('/api/donations/admin?type=donation&status=paid&reported=0');
        if (orders.length === 0) return alert('目前沒有未稟告的資料可列印');

        const printWindow = window.open('', '_blank');
        let itemsHtml = '';
        
        orders.forEach((o) => {
            const name = o.customer.name || '';
            const address = o.customer.address || '';
            
            o.items.forEach(item => {
                itemsHtml += `
                    <tr>
                        <td>${name}</td>
                        <td>${item.name}</td>
                        <td>${item.qty}</td>
                        <td>${address}</td>
                    </tr>
                `;
            });
        });

        printWindow.document.write(`
            <html>
            <head>
                <title>公壇手工香信徒捐香登記表</title>
                <style>
                    body { font-family: "Microsoft JhengHei", "Heiti TC", sans-serif; padding: 20px; background: white; color: #000; }
                    .list-container { width: 100%; max-width: 1000px; margin: 0 auto; }
                    .header { text-align: center; font-size: 24px; font-weight: bold; margin-bottom: 20px; }
                    table { width: 100%; border-collapse: collapse; font-size: 16px; margin-top: 10px; }
                    th, td { border: 1px solid #000; padding: 12px 10px; text-align: left; vertical-align: middle; }
                    th { font-weight: bold; }
                    @media print {
                        @page { margin: 1cm; }
                        body { -webkit-print-color-adjust: exact; }
                    }
                </style>
            </head>
            <body>
                <div class="list-container">
                    <div class="header">公壇手工香信徒捐香登記表</div>
                    <table>
                        <thead>
                            <tr>
                                <th width="15%">姓名</th>
                                <th width="25%">香品</th>
                                <th width="10%">數量</th>
                                <th width="50%">地址</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${itemsHtml}
                        </tbody>
                    </table>
                </div>
                <script>setTimeout(() => { window.print(); }, 500);<\/script>
            </body>
            </html>
        `);
        printWindow.document.close();
    };

    window.markAllReported = async () => {
        if (!window.currentIncenseIds?.length) return;
        Core.confirmAction(`確定將這 ${window.currentIncenseIds.length} 筆資料標記為「已稟告」嗎？`, async () => {
            try {
                await Core.apiFetch('/api/donations/mark-reported', {
                    method: 'POST', body: JSON.stringify({ ids: window.currentIncenseIds })
                });
                alert('更新成功！');
                window.fetchDonations('donation'); 
            } catch(e) { alert('更新失敗'); }
        });
    };

    // --- Orders ---
    window.fetchOrders = () => OrderManager.fetchList();
    
    window.viewOrderDetails = (o) => {
        const modalBody = document.getElementById('order-detail-body');
        if(!modalBody) return;
        
        const deliveryInfo = o.customer.shippingMethod === '711' 
            ? `<p><b>取貨:</b> <span style="background:#28a745; color:#fff; padding:2px 5px; border-radius:3px;">7-11</span> ${o.customer.storeInfo || '未抓到門市資料'}</p>`
            : `<p><b>地址:</b> ${o.customer.address}</p>`;

        modalBody.innerHTML = `
            <p><b>訂單編號:</b> ${o.orderId}</p>
            <p><b>建立時間:</b> ${o.createdAt}</p><hr>
            <h4>客戶資料</h4>
            <p><b>姓名:</b> ${o.customer.name}</p>
            <p><b>電話:</b> ${o.customer.phone}</p>
            ${deliveryInfo}            
            <p><b>Email:</b> ${o.customer.email}</p>
            <p><b>匯款後五碼:</b> ${o.customer.last5}</p><hr>
            <h4>訂單內容</h4>
            <ul>${o.items.map(i => `<li>${i.name} (${i.variantName||i.variant||'標準'}) x${i.qty} - $${i.price*i.qty}</li>`).join('')}</ul>
            <p style="text-align:right; font-size:18px; color:#C48945;"><b>總金額: $${o.total}</b></p>
            ${o.trackingNumber ? `<hr><p><b>物流單號:</b> ${o.trackingNumber}</p>` : ''}
        `;
        UI.openModal('order-detail-modal');
    };

    window.confirmOrder = (id, orderId) => { 
        Core.confirmAction(`確認收款訂單編號：${orderId}，將回信待出貨？`, async () => { 
            await Core.apiFetch(`/api/orders/${id}/confirm`, {method:'PUT'}); 
            OrderManager.fetchList(); 
        }); 
    };

    window.shipOrder = async (id) => {
        const trackNum = prompt("請輸入物流單號 (寄送出貨通知信)：");
        if(trackNum) { 
            await Core.apiFetch(`/api/orders/${id}/ship`, { method:'PUT', body: JSON.stringify({trackingNumber: trackNum}) });
            alert("已出貨並通知！"); 
            OrderManager.fetchList();
        }
    };

    window.cleanupShipped = () => { 
        Core.confirmAction('刪除14天前舊單？', async () => { 
            await Core.apiFetch('/api/orders/cleanup-shipped', {method:'DELETE'}); 
            OrderManager.fetchList(); 
        }); 
    };

    window.delOrder = (id, type) => { 
        Core.confirmAction('確定刪除？系統將自動寄送「取消通知信」給客戶。', async () => { 
            await Core.apiFetch(`/api/orders/${id}`, {method:'DELETE'}); 
            if(['donation', 'fund', 'committee'].includes(type)) window.fetchDonations(type); 
            else OrderManager.fetchList();
        }); 
    };

    // --- Feedback ---
    window.approveFb = (id) => Core.confirmAction('確認核准？(將寄信通知信徒已刊登)', async () => { await Core.apiFetch(`/api/feedback/${id}/approve`, {method:'PUT'}); FeedbackManager.fetchList(); });
    window.delFb = (id) => Core.confirmAction('確認刪除？(將寄信通知信徒未獲刊登)', async () => { await Core.apiFetch(`/api/feedback/${id}`, {method:'DELETE'}); FeedbackManager.fetchList(); });
    window.shipGift = async (id) => {
        const track = prompt('請輸入小神衣物流單號：');
        if(track) {
            await Core.apiFetch(`/api/feedback/${id}/ship`, {method:'PUT', body:JSON.stringify({trackingNumber: track})});
            alert('已標記寄送並通知信徒！'); FeedbackManager.fetchList();
        }
    };

    window.exportFeedbackTxt = async () => {
        try {
            const res = await fetch('/api/feedback/export-txt', {method:'POST', headers:{'X-CSRFToken':Core.getCsrfToken()}});
            if(res.status===404) return alert('無資料');
            const blob = await res.blob();
            const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download='回饋寄送名單.txt'; a.click();
        } catch(e) { alert('匯出失敗'); }
    };

    window.exportSentFeedbackTxt = async () => {
        try {
            const res = await fetch('/api/feedback/export-sent-txt', {method:'POST', headers:{'X-CSRFToken':Core.getCsrfToken()}});
            if(res.status === 404) return alert('目前無已寄送資料');
            const blob = await res.blob();
            const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = `已寄送名單_${new Date().toISOString().slice(0,10)}.txt`; a.click();
        } catch(e) { alert('匯出失敗'); }
    };

    window.editFb = (item) => {
        const form = document.getElementById('feedback-edit-form');
        if(!form) return;
        form.feedbackId.value = item._id; form.realName.value = item.realName;
        form.nickname.value = item.nickname; form.content.value = item.content;
        form.phone.value = item.phone; form.address.value = item.address;
        form.category.value = Array.isArray(item.category) ? item.category[0] : item.category;
        
        form.onsubmit = async (e) => {
            e.preventDefault();
            const data = {
                realName: form.realName.value, nickname: form.nickname.value, category: [form.category.value],
                content: form.content.value, phone: form.phone.value, address: form.address.value
            };
            await Core.apiFetch(`/api/feedback/${form.feedbackId.value}`, {method:'PUT', body:JSON.stringify(data)});
            UI.closeModal('feedback-edit-modal'); FeedbackManager.fetchList();
        };
        UI.openModal('feedback-edit-modal');
    };

    window.viewFbDetail = (item) => {
        const body = document.getElementById('feedback-detail-body');
        if(!body) return;
        
        const statusHtml = item.status === 'sent' 
            ? `<p><strong>寄出時間：</strong> ${item.sentAt || '未知'}</p><p><strong>物流單號：</strong> ${item.trackingNumber || '無'}</p>`
            : `<p><strong>核准時間：</strong> ${item.approvedAt || '未知'}</p>`;
        
        body.innerHTML = `
            <div style="border-bottom:1px solid #eee; padding-bottom:10px; margin-bottom:10px;">
                <p><strong>編號：</strong> ${item.feedbackId || '無'}</p>${statusHtml}
            </div>
            <p><strong>真實姓名：</strong> ${item.realName}</p><p><strong>暱稱：</strong> ${item.nickname}</p>
            <p><strong>農曆生日：</strong> ${item.lunarBirthday || '未提供'}</p>
            <p><strong>電話：</strong> ${item.phone}</p><p><strong>地址：</strong> ${item.address}</p>
            <p><strong>分類：</strong> ${Array.isArray(item.category) ? item.category.join(', ') : item.category}</p>
            <div style="background:#f9f9f9; padding:15px; border-radius:8px; border:1px solid #ddd; margin-top:15px;">
                <strong style="color:#C48945;">回饋內容：</strong><br>
                <div class="pre-wrap" style="margin-top:10px;">${item.content}</div>
            </div>
        `;
        UI.openModal('feedback-detail-modal');
    };

    window.printFeedbackList = async () => {
        const [approved, sent] = await Promise.all([Core.apiFetch('/api/feedback/status/approved'), Core.apiFetch('/api/feedback/status/sent')]);
        const allCandidates = [...approved, ...sent]; 
        if (allCandidates.length === 0) return alert('目前沒有符合資格的名單');

        const printWindow = window.open('', '_blank');
        const itemsHtml = allCandidates.map(fb => `
            <div class="feedback-item">
                <div class="meta">編號: ${fb.feedbackId || '無'}</div>
                <div class="nickname">${fb.nickname}</div>
                <div class="content">${fb.content}</div>
            </div>
        `).join('');

        printWindow.document.write(`
            <html><head><title>信徒回饋匯出</title><style>
            body { font-family: "Microsoft JhengHei", "Heiti TC", sans-serif; padding: 40px; max-width: 800px; margin: 0 auto; color: #333; }
            .feedback-item { margin-bottom: 60px; page-break-inside: avoid; break-inside: avoid; }
            .meta { font-size: 14px; color: #666; margin-bottom: 5px; }
            .nickname { font-size: 20px; font-weight: bold; margin-bottom: 15px; color: #000; }
            .content { font-size: 16px; line-height: 1.8; white-space: pre-wrap; text-align: justify; }
            @media print { body { padding: 0; margin: 2cm; } .feedback-item { page-break-inside: avoid; } }
            </style></head><body>
            <h2 style="text-align:center; margin-bottom: 50px; border-bottom: 2px solid #333; padding-bottom: 20px;">信徒回饋匯出清單 (共 ${allCandidates.length} 筆)</h2>
            ${itemsHtml}
            <script>setTimeout(() => { window.print(); }, 500);<\/script>
            </body></html>
        `);
        printWindow.document.close();
    };

    // --- Content, Links & FAQs ---
    window.updLink = async (id, old) => {
        const url = prompt('新網址', old);
        if(url) { await Core.apiFetch(`/api/links/${id}`, {method:'PUT', body:JSON.stringify({url})}); SettingsManager.fetchLinks(); }
    };

    window.delAnn = (id) => Core.confirmAction('刪除？', async () => { await Core.apiFetch(`/api/announcements/${id}`, {method:'DELETE'}); ContentManager.fetchAnnouncements(); });
    window.delFaq = (id) => Core.confirmAction('刪除？', async () => { await Core.apiFetch(`/api/faq/${id}`, {method:'DELETE'}); ContentManager.fetchFaqs(); });

    const setupFormModal = (btnId, modalId, titleId, newTitle, formId, populateFn) => {
        const form = document.getElementById(formId);
        const btn = document.getElementById(btnId);
        if(!form || !btn) return;
        
        btn.onclick = () => {
            form.reset(); 
            const titleEl = document.getElementById(titleId);
            if(titleEl) titleEl.textContent = newTitle;
            
            if(form.announcementId) form.announcementId.value = '';
            if(form.faqId) form.faqId.value = '';
            UI.openModal(modalId);
        };
        window[`edit${titleId === 'ann-modal-title' ? 'Ann' : 'Faq'}`] = (data) => {
            form.reset(); 
            const titleEl = document.getElementById(titleId);
            if(titleEl) titleEl.textContent = `編輯${newTitle.replace('新增', '')}`;
            
            populateFn(form, data); UI.openModal(modalId);
        };
    };
    
    setupFormModal('add-announcement-btn', 'announcement-modal', 'ann-modal-title', '新增公告', 'announcement-form', (form, a) => {
        form.announcementId.value = a._id; form.date.value = a.date; form.title.value = a.title; form.content.value = a.content; form.isPinned.checked = a.isPinned;
    });

    setupFormModal('add-faq-btn', 'faq-modal', 'faq-modal-title', '新增問答', 'faq-form', (form, f) => {
        form.faqId.value = f._id; form.question.value = f.question; form.answer.value = f.answer; form.other_category.value = f.category; form.isPinned.checked = f.isPinned;
    });

    const annForm = document.getElementById('announcement-form');
    if(annForm) annForm.onsubmit = async (e) => {
        e.preventDefault();
        const id = annForm.announcementId.value;
        await Core.apiFetch(id ? `/api/announcements/${id}` : '/api/announcements', { method: id ? 'PUT' : 'POST', body: JSON.stringify({ date: annForm.date.value, title: annForm.title.value, content: annForm.content.value, isPinned: annForm.isPinned.checked }) });
        UI.closeModal('announcement-modal'); ContentManager.fetchAnnouncements();
    };

    const faqForm = document.getElementById('faq-form');
    if(faqForm) faqForm.onsubmit = async (e) => {
        e.preventDefault(); if(!faqForm.other_category.value) return alert('分類必填');
        const id = faqForm.faqId.value;
        await Core.apiFetch(id ? `/api/faq/${id}` : '/api/faq', { method: id ? 'PUT' : 'POST', body: JSON.stringify({ question: faqForm.question.value, answer: faqForm.answer.value, category: faqForm.other_category.value, isPinned: faqForm.isPinned.checked }) });
        UI.closeModal('faq-modal'); ContentManager.fetchFaqs();
    };
    // ==========================================
// 單據強制刪除功能 (Hard Delete)
// ==========================================
document.addEventListener('DOMContentLoaded', () => {
    const forceDeleteBtn = document.getElementById('forceDeleteBtn');
    const forceDeleteInput = document.getElementById('forceDeleteInput');

    if (forceDeleteBtn && forceDeleteInput) {
        forceDeleteBtn.addEventListener('click', async () => {
            const receiptId = forceDeleteInput.value.trim();
            
            // 1. 檢查是否有輸入
            if (!receiptId) {
                alert('請先輸入要刪除的單據編號！');
                return;
            }

            // 2. 防呆二次確認視窗
            const isConfirmed = confirm(`您確定要刪除單號 ${receiptId} 嗎？此操作無法復原。`);
            
            // 如果管理員按「取消」，就中斷執行
            if (!isConfirmed) return;

            // 3. 呼叫後端 API 進行刪除
            try {
                // 為了防止誤觸，按鈕先呈現處理中狀態
                forceDeleteBtn.disabled = true;
                forceDeleteBtn.innerText = '刪除中...';

                // 註：因為你的 app.py 有啟用 CSRFProtect，如果 admin.js 已經有統一處理 CSRF Header，這裡就可以照舊。
                // 若沒有，你可能需要從 html meta tag 抓 csrf_token 放在 headers 裡。若有報 400 CSRF 錯誤我們再來補上。
                const response = await fetch(`/api/admin/receipt/${receiptId}`, {
                    method: 'DELETE',
                    headers: {
                        'Content-Type': 'application/json'
                    }
                });

                const result = await response.json();

                if (response.ok && result.success) {
                    // 刪除成功
                    alert(result.message);
                    forceDeleteInput.value = ''; // 清空輸入框
                } else {
                    // 找不到單號或格式錯誤
                    alert(`刪除失敗：${result.error}`);
                }
            } catch (error) {
                console.error('刪除單據時發生錯誤:', error);
                alert('系統發生異常，請確認網路連線或聯繫開發人員。');
            } finally {
                // 恢復按鈕狀態
                forceDeleteBtn.disabled = false;
                forceDeleteBtn.innerText = '確認刪除';
            }
        });
    }
});
    /* =========================================
       9. HTML 區塊渲染輔助函式
       ========================================= */
    function renderIncenseList(pending, paid, container) {
        const filterEl = document.getElementById('incense-report-filter');
        const isUnreportedView = filterEl && filterEl.value === '0';
        window.currentIncenseIds = paid.filter(o => !o.is_reported).map(o => o._id);
        let html = '';

        if (pending.length > 0) {
            html += `<h3 style="background:#dc3545; color:white; padding:10px; border-radius:5px; margin-bottom:10px;">⚠️ 待收款審核 (${pending.length})</h3>`;
            html += pending.map(o => `
                <div class="feedback-card" style="border-left:5px solid #dc3545; background:#fff5f5;">
                    <div style="font-size:12px; color:#888; border-bottom:1px solid #eee; padding-bottom:8px; margin-bottom:8px;">單號: ${o.orderId} | 送出日期: ${o.createdAt}</div>
                    <div><strong>${o.customer.name}</strong> / <span style="color:#555;">${o.items.map(i => `${i.name} x${i.qty}`).join('、')}</span> / <span style="color:#dc3545; font-weight:bold;">未收款 ($${o.total})</span></div>
                    <div style="text-align:right; margin-top:10px; padding-top:10px; border-top:1px dashed #ccc;">
                        <button class="btn btn--grey" onclick='viewDonationDetail(${Core.safeStringify(o)})'>🔍 查看完整內容</button>
                        <button class="btn btn--green" onclick="confirmDonation('${o._id}', 'donation')">✅ 已收款</button>
                        <button class="btn btn--red" onclick="delOrder('${o._id}', 'donation')">🗑️ 刪除</button>
                    </div>
                </div>`).join('');
            html += `<hr style="margin:20px 0; border:0; border-top:1px dashed #ccc;">`;
        }
        
        if (isUnreportedView && paid.length > 0) {
            html += `<div style="background:#fff3cd; padding:10px; margin-bottom:15px; border-radius:5px; border:1px solid #ffeeba; display:flex; justify-content:space-between; align-items:center;">
                <span>⚠️ 共 <strong>${paid.length}</strong> 筆未稟告資料</span><button class="btn btn--blue" onclick="markAllReported()">✅ 將本頁標記為已稟告</button></div>`;
        }

        if (paid.length === 0 && pending.length === 0) return container.innerHTML = '<p style="padding:20px; text-align:center; color:#999;">查無資料</p>';

        html += paid.map(o => `
            <div class="feedback-card" style="border-left:5px solid ${o.is_reported ? '#28a745' : '#ffc107'};">
                <div style="font-size:12px; color:#888; border-bottom:1px solid #eee; padding-bottom:8px; margin-bottom:8px;">單號: ${o.orderId} | 送出日期: ${o.createdAt}</div>
                <div><strong>${o.customer.name}</strong> / <span style="color:#555;">${o.items.map(i => `${i.name} x${i.qty}`).join('、')}</span> / <span style="font-weight:bold; color:${o.is_reported ? '#155724' : '#856404'};">${o.is_reported ? '已稟告' : '未稟告'}</span></div>
                <div style="text-align:right; margin-top:10px;"><button class="btn btn--grey" onclick='viewDonationDetail(${Core.safeStringify(o)})'>🔍 查看完整內容</button></div>
            </div>`).join('');
        
        container.innerHTML = html;
    }

    function renderFundList(pending, paid, container, orderType = 'fund') {
        let html = '';
        if (pending.length > 0) {
            html += `<h3 style="background:#dc3545; color:white; padding:10px; border-radius:5px; margin-bottom:10px;">⚠️ 待收款審核 (${pending.length})</h3>`;
            html += pending.map(o => `
                <div class="feedback-card" style="border-left:5px solid #dc3545; background:#fff5f5;">
                    <div style="font-size:12px; color:#888; border-bottom:1px solid #eee; padding-bottom:8px; margin-bottom:8px;">單號: ${o.orderId} | 送出日期: ${o.createdAt}</div>
                    <div><strong>${o.customer.name}</strong> / <span style="color:#555;">${o.items.map(i => i.name).join('、')}</span> / <span style="color:#dc3545; font-weight:bold;">金額: $${o.total}</span></div>
                    <div style="text-align:right; margin-top:10px; padding-top:10px; border-top:1px dashed #ccc;">
                        <button class="btn btn--grey" onclick='viewDonationDetail(${Core.safeStringify(o)})'>🔍 查看完整內容</button>
                        <button class="btn btn--green" onclick="confirmDonation('${o._id}', '${orderType}')">✅ 已收款</button>
                        <button class="btn btn--red" onclick="delOrder('${o._id}', '${orderType}')">🗑️ 刪除</button>
                    </div>
                </div>`).join('');
            html += `<hr style="margin:20px 0; border:0; border-top:1px dashed #ccc;">`;
        }

        if (paid.length > 0) {
            html += paid.map(o => {
                const amountDisplay = orderType === 'committee' ? '' : ` / <span style="color:#C48945; font-weight:bold;">金額: $${o.total}</span>`;
                return `
                <div class="feedback-card" style="border-left:5px solid #C48945;">
                    <div style="font-size:12px; color:#888; border-bottom:1px solid #eee; padding-bottom:8px; margin-bottom:8px;">單號: ${o.orderId} | 送出日期: ${o.createdAt}</div>
                    <div><strong>${o.customer.name}</strong> / <span style="color:#555;">${o.items.map(i => i.name).join('、')}</span>${amountDisplay}</div>
                    <div style="text-align:right; margin-top:10px;"><button class="btn btn--grey" onclick='viewDonationDetail(${Core.safeStringify(o)})'>🔍 查看完整內容</button></div>
                </div>`
            }).join('');
        } else if (pending.length === 0) {
            html += '<p style="padding:20px; text-align:center; color:#999;">查無資料</p>';
        }
        container.innerHTML = html;
    }
    

    // 啟動流程
    UI.init();
    Auth.checkSession();
});