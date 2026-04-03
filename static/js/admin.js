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
                    alert(errObj.message || errObj.error || '發生錯誤');
                } catch (e) {
                    alert('操作失敗，請檢查網路或權限');
                }
                throw error;
            }
        },

        confirmAction(msg, cb) { if (confirm(msg)) cb(); },
        safeStringify(obj) { return JSON.stringify(obj).replace(/'/g, "&apos;"); }
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
            this.setupSubTabs();
            this.setupModals();
            this.setupSidebar();
        },

        showLogin() {
            if (this.loginWrapper) this.loginWrapper.style.display = 'flex';
            if (this.adminContent) this.adminContent.style.display = 'none';
        },

        showAdminContent(role) {
            if (this.loginWrapper) this.loginWrapper.style.display = 'none';
            if (this.adminContent) {
                this.adminContent.style.display = 'block';
                this.applyRoleVisibility(role);
                if (!this.adminContent.dataset.initialized) {
                    const first = document.querySelector('.nav-item:not([style*="display: none"])');
                    if (first) first.click();
                    this.adminContent.dataset.initialized = 'true';
                }
            }
        },

        applyRoleVisibility(role) {
            document.querySelectorAll('.nav-item[data-roles]').forEach(item => {
                const allowed = item.dataset.roles.split(',');
                item.style.display = allowed.includes(role) ? '' : 'none';
            });
        },

        setupNavigation() {
            const tabActions = {
                'tab-finance': () => FinanceManager.refresh(),
                'tab-ops': () => OpsManager.loadPrintQueue(),
                'tab-data': () => DataManager.search(),
                'tab-cms': () => CMSManager.loadProducts(),
                'tab-system': () => SystemManager.loadUsers()
            };

            document.querySelectorAll('.nav-item').forEach(btn => {
                btn.addEventListener('click', () => {
                    document.querySelectorAll('.nav-item').forEach(el => el.classList.remove('active'));
                    document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
                    btn.classList.add('active');
                    const tabId = btn.dataset.tab;
                    document.getElementById(tabId)?.classList.add('active');
                    if (this.pageTitleDisplay) this.pageTitleDisplay.textContent = btn.innerText;
                    if (window.innerWidth <= 768) this.toggleSidebar(false);
                    if (tabActions[tabId]) tabActions[tabId]();
                });
            });
        },

        setupSubTabs() {
            const configs = [
                { attr: 'data-ops-tab', cls: 'ops-sub', actions: {
                    'ops-print': () => OpsManager.loadPrintQueue(),
                    'ops-ship': () => OpsManager.loadShipQueue(),
                    'ops-feedback': () => OpsManager.loadFeedbackGifts()
                }},
                { attr: 'data-data-tab', cls: 'data-sub', actions: {
                    'data-history': () => DataManager.search(),
                    'data-members': () => DataManager.loadMembers(),
                    'data-feedback': () => DataManager.loadFeedbackReview()
                }},
                { attr: 'data-cms-tab', cls: 'cms-sub', actions: {
                    'cms-products': () => CMSManager.loadProducts(),
                    'cms-announcements': () => CMSManager.loadAnnouncements(),
                    'cms-faq': () => CMSManager.loadFaqs(),
                    'cms-fund': () => CMSManager.loadFund(),
                    'cms-settings': () => CMSManager.loadSettings()
                }},
                { attr: 'data-sys-tab', cls: 'sys-sub', actions: {
                    'sys-users': () => SystemManager.loadUsers(),
                    'sys-audit': () => SystemManager.loadAuditLog(),
                    'sys-receipt': () => {}
                }}
            ];

            configs.forEach(cfg => {
                const btns = document.querySelectorAll(`[${cfg.attr}]`);
                btns.forEach(btn => {
                    btn.addEventListener('click', () => {
                        btns.forEach(b => b.classList.remove('active'));
                        btn.classList.add('active');
                        const tabId = btn.getAttribute(cfg.attr);
                        const parent = btn.closest('.tab-content');
                        if (parent) {
                            parent.querySelectorAll(`.${cfg.cls}`).forEach(p => {
                                p.style.display = p.id === tabId ? 'block' : 'none';
                            });
                        }
                        if (cfg.actions[tabId]) cfg.actions[tabId]();
                    });
                });
            });
        },

        setupSidebar() {
            const toggle = document.getElementById('sidebar-toggle');
            if (toggle) toggle.onclick = () => this.toggleSidebar(true);
            if (this.overlay) this.overlay.onclick = () => this.toggleSidebar(false);
        },

        toggleSidebar(show) {
            this.sidebar?.classList.toggle('open', show);
            if (this.overlay) this.overlay.style.display = show ? 'block' : 'none';
        },

        setupModals() {
            document.querySelectorAll('.admin-modal-overlay').forEach(m => {
                m.addEventListener('click', e => {
                    if (e.target === m || e.target.classList.contains('modal-close-btn'))
                        m.classList.remove('is-visible');
                });
            });
        },

        openModal(id) { document.getElementById(id)?.classList.add('is-visible'); },
        closeModal(id) { document.getElementById(id)?.classList.remove('is-visible'); }
    };

    /* =========================================
       3. 身份驗證 (Auth)
       ========================================= */
    const Auth = {
        role: 'super_admin',
        username: 'admin',

        async checkSession() {
            try {
                const data = await fetch('/api/session_check').then(r => r.json());
                if (data.logged_in) {
                    this.role = data.role || 'super_admin';
                    this.username = data.username || 'admin';
                    this.updateSidebarInfo();
                    UI.showAdminContent(this.role);
                } else {
                    UI.showLogin();
                }
            } catch (e) { UI.showLogin(); }
        },

        updateSidebarInfo() {
            const el = document.getElementById('sidebar-user-info');
            if (!el) return;
            const labels = { super_admin: 'SuperAdmin', finance: 'Finance', ops: 'Ops' };
            el.innerHTML = `${this.username} <span class="role-badge">${labels[this.role] || this.role}</span>`;
        },

        async login(username, password) {
            try {
                const res = await fetch('/api/login', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ username, password })
                });
                const data = await res.json();
                if (data.success) location.reload();
                else {
                    const el = document.getElementById('login-error');
                    if (el) el.textContent = data.message || '帳號或密碼錯誤';
                }
            } catch (e) { alert('連線錯誤'); }
        },

        async logout() {
            await Core.apiFetch('/api/logout', { method: 'POST' });
            location.reload();
        }
    };

    document.getElementById('login-form')?.addEventListener('submit', e => {
        e.preventDefault();
        Auth.login(
            document.getElementById('admin-username')?.value.trim() || '',
            document.getElementById('admin-password').value
        );
    });
    document.getElementById('logout-btn')?.addEventListener('click', () => Auth.logout());

    /* =========================================
       4. 💰 財務稽核中樞 (FinanceManager)
       ========================================= */
    const FinanceManager = {
        async refresh() {
            await Promise.all([this.loadPending(), this.loadSummary()]);
        },

        async loadPending() {
            const el = document.getElementById('finance-pending-list');
            if (!el) return;
            el.innerHTML = '載入中...';
            try {
                const list = await Core.apiFetch('/api/admin/finance/pending');
                if (!list.length) { el.innerHTML = '<p class="empty-state">🎉 目前沒有待收款單據</p>'; return; }
                el.innerHTML = list.map(o => `
                    <div class="feedback-card border-left-danger fb-card-pending-bg">
                        <div class="card-meta">
                            <span class="badge-source">${o.source_label}</span>
                            單號: ${o.orderId} | 送出: ${o.createdAt}
                            ${o.paymentDeadline ? ` | 期限: ${o.paymentDeadline}` : ''}
                        </div>
                        <div>
                            <strong>${o.customer?.name || '未知'}</strong> /
                            ${o.customer?.phone || ''} /
                            <span class="text-danger fw-bold">$${o.total}</span>
                        </div>
                        <div class="text-gray fs-13">${(o.items || []).map(i => i.name + ' x' + i.qty).join('、')}</div>
                        <div class="card-actions">
                            <button class="btn btn--grey" onclick='viewDonationDetail(${Core.safeStringify(o)})'>🔍 查看詳情</button>
                            <button class="btn btn--green" onclick="confirmPayment('${o._id}', '${o.orderType}')">✅ 確認收款</button>
                            <button class="btn btn--red" onclick="deleteOrder('${o._id}', '${o.orderType}')">🗑️ 刪除</button>
                        </div>
                    </div>
                `).join('');
            } catch (e) { el.innerHTML = '<p class="text-danger">載入失敗</p>'; }
        },

        async loadSummary() {
            const el = document.getElementById('finance-summary');
            if (!el) return;
            try {
                const summary = await Core.apiFetch('/api/admin/finance/summary');
                const labels = { shop: '🛍️ 結緣品', donation: '🕯️ 捐香', fund: '🏗️ 建廟基金', committee: '🏛️ 委員會' };
                let html = '';
                for (const [type, statuses] of Object.entries(summary)) {
                    const p = statuses.pending || { count: 0, total: 0 };
                    const d = statuses.paid || { count: 0, total: 0 };
                    html += `
                        <div class="card" style="min-width:150px;flex:1;">
                            <div class="fs-12 text-gray mb-5">${labels[type] || type}</div>
                            <div class="text-danger fw-bold">待收 ${p.count} 筆 $${p.total}</div>
                            <div class="text-success fs-13">已收 ${d.count} 筆 $${d.total}</div>
                        </div>`;
                }
                el.innerHTML = html || '<span class="text-gray">無資料</span>';
            } catch (e) {}
        }
    };

    /* =========================================
       5. 🛠️ 站務作業中樞 (OpsManager)
       ========================================= */
    const OpsManager = {
        printQueueData: [],

        async loadPrintQueue() {
            const el = document.getElementById('print-queue-list');
            if (!el) return;
            el.innerHTML = '載入中...';
            try {
                const orders = await Core.apiFetch('/api/admin/ops/print-queue');
                this.printQueueData = orders;
                if (!orders.length) { el.innerHTML = '<p class="empty-state">🎉 無待列印資料</p>'; return; }
                el.innerHTML = orders.map(o => `
                    <div class="feedback-card border-left-warning">
                        <div class="card-meta">單號: ${o.orderId} | 付款: ${o.paidAt}</div>
                        <div><strong>${o.customer?.name || ''}</strong> / ${o.customer?.address || '未填地址'}</div>
                        <div class="text-muted fs-13">${(o.items || []).map(i => i.name + ' x' + i.qty).join('、')}</div>
                    </div>
                `).join('');
            } catch (e) { el.innerHTML = '<p class="text-danger">載入失敗</p>'; }
        },

        printRedPaper() {
            if (!this.printQueueData.length) return alert('目前無待列印資料');
            const pw = window.open('', '_blank');
            let rows = '';
            this.printQueueData.forEach(o => {
                (o.items || []).forEach(item => {
                    rows += `<tr><td>${o.customer?.name || ''}</td><td>${item.name}</td><td>${item.qty}</td><td>${o.customer?.address || ''}</td></tr>`;
                });
            });
            pw.document.write(`
                <html><head><title>公壇手工香信徒捐香登記表</title>
                <style>
                    body { font-family: "Microsoft JhengHei", "Heiti TC", sans-serif; padding: 20px; background: white; color: #000; }
                    .header { text-align: center; font-size: 24px; font-weight: bold; margin-bottom: 20px; }
                    table { width: 100%; border-collapse: collapse; font-size: 16px; }
                    th, td { border: 1px solid #000; padding: 12px 10px; text-align: left; vertical-align: middle; }
                    @media print { @page { margin: 1cm; } }
                </style></head><body>
                <div class="header">公壇手工香信徒捐香登記表</div>
                <table>
                    <thead><tr><th width="15%">姓名</th><th width="25%">香品</th><th width="10%">數量</th><th width="50%">地址</th></tr></thead>
                    <tbody>${rows}</tbody>
                </table>
                <script>setTimeout(() => window.print(), 500);<\/script>
                </body></html>
            `);
            pw.document.close();
        },

        batchMarkPrinted() {
            const ids = this.printQueueData.map(o => o._id);
            if (!ids.length) return alert('無資料');
            Core.confirmAction(`將 ${ids.length} 筆標記為已稟告？`, async () => {
                await Core.apiFetch('/api/donations/mark-reported', { method: 'POST', body: JSON.stringify({ ids }) });
                alert('標記完成');
                this.loadPrintQueue();
            });
        },

        async loadShipQueue() {
            const el = document.getElementById('ship-queue-list');
            if (!el) return;
            el.innerHTML = '載入中...';
            try {
                const orders = await Core.apiFetch('/api/admin/ops/ship-queue');
                el.innerHTML = orders.length ? orders.map(o => `
                    <div class="feedback-card border-left-success">
                        <div class="card-meta">單號: ${o.orderId} | 付款: ${o.paidAt}</div>
                        <div>
                            ${o.customer?.shippingMethod === '711' ? '<span class="badge-711">[7-11]</span> ' : ''}
                            <strong>${o.customer?.name || ''}</strong> /
                            ${o.customer?.phone || ''} /
                            <span class="text-brown fw-bold">$${o.total}</span>
                        </div>
                        <div class="text-gray fs-13">${(o.items || []).map(i => i.name + ' x' + i.qty).join('、')}</div>
                        <div class="card-actions">
                            <button class="btn btn--grey" onclick='viewOrderDetails(${Core.safeStringify(o)})'>🔍 查看</button>
                            <button class="btn btn--blue" onclick="shipOrder('${o._id}')">🚚 出貨</button>
                        </div>
                    </div>
                `).join('') : '<p class="empty-state">🎉 無待出貨訂單</p>';
            } catch (e) { el.innerHTML = '<p class="text-danger">載入失敗</p>'; }
            this.loadShippedList();
        },

        async loadShippedList() {
            const el = document.getElementById('shipped-list');
            if (!el) return;
            try {
                const orders = await Core.apiFetch('/api/admin/ops/shipped-list');
                el.innerHTML = orders.length ? orders.map(o => `
                    <div class="feedback-card border-left-info">
                        <div class="d-flex justify-between"><b>${o.orderId}</b><small>出貨: ${o.shippedAt}</small></div>
                        <div>${o.customer?.name || ''} / ${o.customer?.phone || ''} / $${o.total}</div>
                        ${o.trackingNumber ? `<div class="fs-13 text-gray">物流: ${o.trackingNumber}</div>` : ''}
                    </div>
                `).join('') : '<p class="empty-state">近 30 天無出貨紀錄</p>';
            } catch (e) {}
        },

        refreshShip() { this.loadShipQueue(); },

        cleanupShipped() {
            Core.confirmAction('刪除 14 天前舊單？', async () => {
                await Core.apiFetch('/api/orders/cleanup-shipped', { method: 'DELETE' });
                this.loadShippedList();
            });
        },

        async loadFeedbackGifts() {
            const aEl = document.getElementById('ops-fb-approved-list');
            const sEl = document.getElementById('ops-fb-sent-list');
            if (!aEl) return;
            try {
                const [approved, sent] = await Promise.all([
                    Core.apiFetch('/api/feedback/status/approved'),
                    Core.apiFetch('/api/feedback/status/sent')
                ]);

                aEl.innerHTML = approved.length ? approved.map(i => `
                    <div class="feedback-card border-left-success">
                        <div class="d-flex justify-between align-center detail-header">
                            <strong>${i.feedbackId || '無編號'}</strong>
                            <span class="fs-13 text-gray">${i.approvedAt || ''}</span>
                        </div>
                        <div class="mb-15 lh-18">
                            <strong>${i.realName}</strong>
                            ${i.has_received ? ' <span class="badge-received-warning">[⚠️ 已領取過]</span>' : ''}<br>
                            <span class="text-gray fs-14">📍 ${i.address}</span>
                        </div>
                        <div class="fb-card-footer">
                            <button class="btn btn--grey" onclick='viewFbDetail(${Core.safeStringify(i)})'>📖 查看</button>
                            <button class="btn btn--blue" onclick="shipGift('${i._id}')">🎁 寄出</button>
                        </div>
                    </div>
                `).join('') : '<p class="empty-state">無待寄送</p>';

                if (sEl) sEl.innerHTML = sent.length ? sent.map(i => `
                    <div class="feedback-card feedback-card--sent" onclick='viewFbDetail(${Core.safeStringify(i)})'>
                        <div class="d-flex justify-between align-center">
                            <span class="fs-16 fw-bold text-dark">${i.nickname}</span>
                            <span class="badge-sent">${i.feedbackId || ''}</span>
                        </div>
                        <div class="text-right fs-12 text-gray mt-5">寄出: ${i.sentAt || '未知'}</div>
                    </div>
                `).join('') : '<p class="empty-state">無歷史紀錄</p>';
            } catch (e) { aEl.innerHTML = '<p class="text-danger">載入失敗</p>'; }
        },

        exportSentFeedback() {
            fetch('/api/feedback/export-sent-txt', { method: 'POST', headers: { 'X-CSRFToken': Core.getCsrfToken() } })
                .then(r => { if (r.status === 404) { alert('無資料'); throw new Error('no data'); } return r.blob(); })
                .then(blob => { const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = `已寄送名單_${new Date().toISOString().slice(0, 10)}.txt`; a.click(); })
                .catch(() => {});
        }
    };

    /* =========================================
       6. 🗂️ 綜合資料總管 (DataManager)
       ========================================= */
    const DataManager = {
        async search(page = 1) {
            const el = document.getElementById('history-results');
            const infoEl = document.getElementById('history-info');
            const pagEl = document.getElementById('history-pagination');
            if (!el) return;

            const idMap = { type: 'hist-type', orderId: 'hist-id', name: 'hist-name', status: 'hist-status', start: 'hist-start', end: 'hist-end' };
            const params = new URLSearchParams();
            Object.entries(idMap).forEach(([key, id]) => {
                const v = document.getElementById(id)?.value?.trim();
                if (v) params.set(key, v);
            });
            params.set('page', page);
            el.innerHTML = '搜尋中...';

            try {
                const data = await Core.apiFetch(`/api/admin/data/history?${params}`);
                if (infoEl) infoEl.textContent = `共 ${data.total} 筆 (第 ${data.page} 頁)`;

                if (!data.results.length) {
                    el.innerHTML = '<p class="empty-state">查無資料</p>';
                    if (pagEl) pagEl.innerHTML = '';
                    return;
                }

                const sLabels = { pending: '待收款', paid: '已付款', shipped: '已出貨' };
                const sColors = { pending: 'text-danger', paid: 'text-success', shipped: 'text-gray' };

                el.innerHTML = data.results.map(o => `
                    <div class="admin-list-item d-flex justify-between align-center">
                        <div class="flex-1">
                            <span class="badge-source">${o.source_label}</span>
                            <strong>${o.orderId}</strong>
                            <span class="${sColors[o.status] || ''} fs-13">[${sLabels[o.status] || o.status}]</span><br>
                            <span class="fs-14">${o.customer?.name || ''} / $${o.total} / ${o.createdAt}</span>
                        </div>
                        <button class="btn btn--grey" onclick='viewDonationDetail(${Core.safeStringify(o)})'>🔍</button>
                    </div>
                `).join('');

                if (pagEl) {
                    const totalPages = Math.ceil(data.total / data.per_page);
                    let h = '';
                    if (data.page > 1) h += `<button class="btn btn--grey" onclick="DataManager.search(${data.page - 1})">⬅ 上一頁</button>`;
                    h += `<span class="fs-14 text-gray"> 第 ${data.page} / ${totalPages} 頁 </span>`;
                    if (data.page < totalPages) h += `<button class="btn btn--grey" onclick="DataManager.search(${data.page + 1})">下一頁 ➡</button>`;
                    pagEl.innerHTML = h;
                }
            } catch (e) { el.innerHTML = '<p class="text-danger">搜尋失敗</p>'; }
        },

        exportCSV() {
            const idMap = { type: 'hist-type', name: 'hist-name', status: 'hist-status', start: 'hist-start', end: 'hist-end' };
            const params = new URLSearchParams();
            Object.entries(idMap).forEach(([key, id]) => {
                const v = document.getElementById(id)?.value?.trim();
                if (v) params.set(key, v);
            });
            window.open(`/api/admin/data/export-csv?${params}`, '_blank');
        },

        async loadMembers() {
            const el = document.getElementById('members-list');
            if (!el) return;
            el.innerHTML = '載入中...';
            try {
                const list = await Core.apiFetch('/api/admin/data/members');
                el.innerHTML = list.length ? list.map(m => `
                    <div class="admin-list-item member-card">
                        <div class="member-avatar">${m.pictureUrl ? `<img src="${m.pictureUrl}">` : ''}</div>
                        <div class="flex-1">
                            <strong>${m.displayName || '未知'}</strong>
                            ${m.realName ? `<span class="text-gray fs-13">(${m.realName})</span>` : ''}<br>
                            <span class="fs-13 text-gray">
                                訂單: ${m.orderCount || 0} | 回饋: ${m.feedbackCount || 0} |
                                最後登入: ${m.lastLoginAt || '未知'}
                            </span>
                        </div>
                    </div>
                `).join('') : '<p class="empty-state">無會員資料</p>';
            } catch (e) { el.innerHTML = '<p class="text-danger">載入失敗</p>'; }
        },

        refreshMembers() { this.loadMembers(); },

        async loadFeedbackReview() {
            const pEl = document.getElementById('fb-pending-list');
            const aEl = document.getElementById('fb-approved-list');
            const sEl = document.getElementById('fb-stats-bar');
            if (!pEl) return;
            try {
                const [pending, approved] = await Promise.all([
                    Core.apiFetch('/api/feedback/status/pending'),
                    Core.apiFetch('/api/feedback/status/approved')
                ]);

                if (sEl) sEl.innerHTML = `
                    <span class="badge-stats">待審: ${pending.length} | 已刊: ${approved.length}</span>
                    <button class="btn btn--brown" onclick="printFeedbackList()">匯出回饋</button>
                `;

                pEl.innerHTML = pending.length ? pending.map(i => `
                    <div class="feedback-card border-left-danger">
                        <div class="fb-card-header">
                            👤 ${i.nickname}
                            ${i.has_received ? ' <span class="badge-received-warning">[⚠️ 已領取過]</span>' : ''}
                        </div>
                        <div class="content-preview"><div class="pre-wrap text-muted">${i.content}</div></div>
                        <div class="text-right">
                            <button class="btn btn--grey" onclick='editFb(${Core.safeStringify(i)})'>編輯</button>
                            <button class="btn btn--green" onclick="approveFb('${i._id}')">✅ 核准</button>
                            <button class="btn btn--red" onclick="delFb('${i._id}')">🗑️ 刪除</button>
                        </div>
                    </div>
                `).join('') : '<p class="empty-state">無待審核</p>';

                if (aEl) aEl.innerHTML = approved.length ? approved.map(i => `
                    <div class="feedback-card border-left-success">
                        <div class="d-flex justify-between align-center detail-header">
                            <strong>${i.feedbackId || '無'}</strong>
                            <span class="fs-13 text-gray">${i.approvedAt || ''}</span>
                        </div>
                        <div class="mb-15 lh-18">
                            <strong>${i.realName}</strong> (農曆: ${i.lunarBirthday || '未提供'})
                            ${i.has_received ? ' <span class="badge-received-warning">[⚠️ 已領取過]</span>' : ''}<br>
                            <span class="text-gray fs-14">📍 ${i.address}</span>
                        </div>
                        <div class="fb-card-footer">
                            <button class="btn btn--grey" onclick='viewFbDetail(${Core.safeStringify(i)})'>📖 查看</button>
                            <button class="btn btn--blue" onclick="shipGift('${i._id}')">🎁 寄出</button>
                        </div>
                    </div>
                `).join('') : '<p class="empty-state">無</p>';
            } catch (e) { pEl.innerHTML = '<p class="text-danger">載入失敗</p>'; }
        },

        exportFeedbackTxt() {
            fetch('/api/feedback/export-txt', { method: 'POST', headers: { 'X-CSRFToken': Core.getCsrfToken() } })
                .then(r => { if (r.status === 404) { alert('無資料'); throw new Error('no data'); } return r.blob(); })
                .then(blob => { const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = '回饋寄送名單.txt'; a.click(); })
                .catch(() => {});
        }
    };

    /* =========================================
       7. 📝 前台內容管理 — 商品 (ProductManager)
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

            if (imgInput) imgInput.onchange = this.handleImageUpload.bind(this);
            if (addVarBtn) addVarBtn.onclick = () => this.addVariantRow();
            if (addProdBtn) addProdBtn.onclick = () => this.showModal();
            if (this.form) this.form.onsubmit = this.saveProduct.bind(this);

            if (this.listEl) {
                this.listEl.addEventListener('click', e => {
                    if (e.target.classList.contains('del-prod')) {
                        Core.confirmAction('刪除？', async () => {
                            await Core.apiFetch(`/api/products/${e.target.dataset.id}`, { method: 'DELETE' });
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
            if (!file) return;

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
                if (submitBtn) {
                    submitBtn.dataset.originalText = submitBtn.textContent;
                    submitBtn.textContent = '圖片上傳中...';
                    submitBtn.disabled = true;
                    submitBtn.style.opacity = '0.7';
                }
                const res = await fetch('https://api.cloudinary.com/v1_1/dsvj25pma/image/upload', {
                    method: 'POST', body: formData
                });
                const data = await res.json();
                if (data.secure_url) {
                    this.imgHidden.value = data.secure_url;
                } else {
                    alert('圖片上傳失敗');
                }
            } catch (err) {
                alert('圖片上傳發生錯誤');
            } finally {
                if (submitBtn) {
                    submitBtn.textContent = submitBtn.dataset.originalText || '儲存商品';
                    submitBtn.disabled = false;
                    submitBtn.style.opacity = '1';
                }
            }
        },

        addVariantRow(name = '', price = '') {
            if (!this.variantsContainer) return;
            const div = document.createElement('div');
            div.className = 'variant-row d-flex gap-10 mt-10';
            div.innerHTML = `
                <input type="text" placeholder="規格名稱" value="${name}" class="var-name mb-0 flex-2">
                <input type="number" placeholder="價格" value="${price}" class="var-price mb-0 flex-1">
                <button type="button" class="btn btn--red remove-var-btn p-10">×</button>
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
                if (titleEl) titleEl.textContent = '編輯商品';
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
                if (titleEl) titleEl.textContent = '新增商品';
                this.form.productId.value = '';
                this.addVariantRow();
            }
            UI.openModal('product-modal');
        },

        async fetchList() {
            if (!this.listEl) return;
            try {
                const products = await Core.apiFetch('/api/products');

                // Populate series datalist
                const seriesSet = new Set(products.filter(p => p.series).map(p => p.series));
                const datalist = document.getElementById('series-list');
                if (datalist) datalist.innerHTML = [...seriesSet].map(s => `<option value="${s}">`).join('');

                const groups = products.reduce((acc, p) => {
                    (acc[p.category] = acc[p.category] || []).push(p);
                    return acc;
                }, {});

                let html = '';
                for (const [cat, items] of Object.entries(groups)) {
                    html += `<h3 class="category-header">📂 ${cat}</h3>`;
                    html += items.map(p => {
                        const varsHtml = p.variants?.length > 0
                            ? p.variants.map(v => `<small>${v.name}: $${v.price}</small>`).join(' | ')
                            : `<small>單價: $${p.price}</small>`;
                        return `
                        <div class="feedback-card product-card">
                            <div class="product-thumb">${p.image ? `<img src="${p.image}">` : ''}</div>
                            <div class="flex-1">
                                ${p.isDonation ? '<span class="badge-donation">捐贈項目</span>' : ''}
                                <h4 class="my-5">${p.name}</h4>
                                <div class="text-muted">${varsHtml}</div>
                                <small class="${p.isActive ? 'text-success' : 'text-danger'}">${p.isActive ? '● 上架中' : '● 已下架'}</small>
                            </div>
                            <div class="product-actions">
                                <button class="btn btn--brown edit-prod" data-data='${Core.safeStringify(p)}'>編輯</button>
                                <button class="btn btn--red del-prod" data-id="${p._id}">刪除</button>
                            </div>
                        </div>`;
                    }).join('');
                }
                this.listEl.innerHTML = html || '<p>目前無商品</p>';
            } catch (e) { this.listEl.innerHTML = '載入失敗'; }
        },

        async saveProduct(e) {
            e.preventDefault();
            const variants = Array.from(this.variantsContainer.querySelectorAll('.variant-row'))
                .map(row => ({
                    name: row.querySelector('.var-name').value.trim(),
                    price: parseInt(row.querySelector('.var-price').value)
                }))
                .filter(v => v.name && !isNaN(v.price));

            if (variants.length === 0) return alert('請至少輸入一種規格與價格');

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
       8. 📝 前台內容管理 — 公告與問答 (ContentManager)
       ========================================= */
    const ContentManager = {
        async fetchAnnouncements() {
            const data = await Core.apiFetch('/api/announcements');
            const el = document.getElementById('announcements-list');
            if (el) el.innerHTML = data.map(a => `
                <div class="feedback-card">
                    <div><small>${a.date}</small> <b>${a.title}</b> ${a.isPinned ? '<span class="badge-pinned">[置頂]</span>' : ''}</div>
                    <div class="pre-wrap my-5">${a.content}</div>
                    <div class="text-right">
                        <button class="btn btn--brown" onclick='editAnn(${Core.safeStringify(a)})'>編輯</button>
                        <button class="btn btn--red" onclick="delAnn('${a._id}')">刪除</button>
                    </div>
                </div>
            `).join('') || '<p class="empty-state">無公告</p>';
        },

        async fetchFaqs() {
            const faqs = await Core.apiFetch('/api/faq');
            const el = document.getElementById('faq-list');
            if (el) el.innerHTML = faqs.map(f => `
                <div class="feedback-card">
                    <div><span class="badge-tag">${f.category}</span> ${f.isPinned ? '<span class="badge-pinned">[置頂]</span>' : ''} <b>${f.question}</b></div>
                    <div class="pre-wrap my-5 text-muted">${f.answer}</div>
                    <div class="text-right">
                        <button class="btn btn--brown" onclick='editFaq(${Core.safeStringify(f)})'>編輯</button>
                        <button class="btn btn--red" onclick="delFaq('${f._id}')">刪除</button>
                    </div>
                </div>
            `).join('') || '<p class="empty-state">無問答</p>';
        }
    };

    /* =========================================
       9. 📝 前台內容管理 — 設定 (SettingsManager)
       ========================================= */
    const SettingsManager = {
        async fetchLinks() {
            const links = await Core.apiFetch('/api/links');
            const el = document.getElementById('links-list');
            if (el) el.innerHTML = links.map(l => `
                <div class="links-row">
                    <b>${l.name}</b>
                    <input value="${l.url}" readonly class="input-display mb-0">
                    <button class="btn btn--brown" onclick="updLink('${l._id}', '${l.url}')">修改</button>
                </div>
            `).join('');
        },

        async fetchBankInfo() {
            const form = document.getElementById('bank-form');
            if (!form) return;
            try {
                const data = await Core.apiFetch('/api/settings/bank');
                form.shop_bankCode.value = data.shop?.bankCode || '';
                form.shop_bankName.value = data.shop?.bankName || '';
                form.shop_account.value = data.shop?.account || '';
                form.fund_bankCode.value = data.fund?.bankCode || '';
                form.fund_bankName.value = data.fund?.bankName || '';
                form.fund_account.value = data.fund?.account || '';
            } catch (e) {}
        },

        async fetchFund() {
            const data = await Core.apiFetch('/api/fund-settings');
            const goalInput = document.getElementById('fund-goal');
            const currentInput = document.getElementById('fund-current');
            if (goalInput) goalInput.value = data.goal_amount;
            if (currentInput) currentInput.value = data.current_amount;
        }
    };

    /* =========================================
       10. CMSManager 門面 (Facade)
       ========================================= */
    const CMSManager = {
        loadProducts()      { ProductManager.fetchList(); },
        loadAnnouncements() { ContentManager.fetchAnnouncements(); },
        loadFaqs()          { ContentManager.fetchFaqs(); },
        loadFund()          { SettingsManager.fetchFund(); },
        loadSettings()      { SettingsManager.fetchLinks(); SettingsManager.fetchBankInfo(); }
    };

    /* =========================================
       11. ⚙️ 系統與權限管理 (SystemManager)
       ========================================= */
    const SystemManager = {
        async loadUsers() {
            const el = document.getElementById('admin-users-list');
            if (!el) return;
            el.innerHTML = '載入中...';
            try {
                const users = await Core.apiFetch('/api/admin/system/users');
                const labels = { super_admin: 'SuperAdmin', finance: 'Finance', ops: 'Ops' };
                el.innerHTML = users.length ? users.map(u => `
                    <div class="admin-list-item d-flex justify-between align-center">
                        <div>
                            <strong>${u.username}</strong>
                            <span class="badge-role ${u.role}">${labels[u.role] || u.role}</span><br>
                            <small class="text-gray">建立於 ${u.createdAt || '未知'}</small>
                        </div>
                        <button class="btn btn--red" onclick="SystemManager.deleteUser('${u._id}', '${u.username}')">刪除</button>
                    </div>
                `).join('') : '<p class="empty-state">尚未建立管理員帳號</p>';
            } catch (e) { el.innerHTML = '<p class="text-danger">載入失敗 (需 SuperAdmin 權限)</p>'; }
        },

        showCreateUser() {
            const form = document.getElementById('admin-user-form');
            if (form) form.reset();
            UI.openModal('admin-user-modal');
        },

        deleteUser(id, username) {
            Core.confirmAction(`確定刪除管理員「${username}」？`, async () => {
                await Core.apiFetch(`/api/admin/system/users/${id}`, { method: 'DELETE' });
                this.loadUsers();
            });
        },

        async loadAuditLog() {
            const el = document.getElementById('audit-log-list');
            if (!el) return;
            el.innerHTML = '載入中...';
            try {
                const logs = await Core.apiFetch('/api/admin/system/audit-log');
                el.innerHTML = logs.length ? logs.map(l => `
                    <div class="audit-row">
                        <span class="text-gray fs-12">${l.timestamp}</span>
                        <strong class="text-brown"> ${l.admin}</strong>
                        ${l.action}
                        ${l.target ? ` <span class="text-muted">→ ${l.target}</span>` : ''}
                        ${l.details ? ` <span class="fs-12 text-gray">(${l.details})</span>` : ''}
                    </div>
                `).join('') : '<p class="empty-state">無操作紀錄</p>';
            } catch (e) { el.innerHTML = '<p class="text-danger">載入失敗</p>'; }
        },

        refreshAudit() { this.loadAuditLog(); }
    };

    /* =========================================
       12. 單據工具 (ReceiptManager & ForceDelete)
       ========================================= */
    const ReceiptManager = {
        queryInput: document.getElementById('receiptQueryInput'),
        queryBtn: document.getElementById('receiptQueryBtn'),
        saveBtn: document.getElementById('receiptSaveBtn'),
        editor: document.getElementById('receipt-json-editor'),
        wrapper: document.getElementById('receipt-editor-wrapper'),
        currentReceiptId: null,

        init() {
            if (!this.queryBtn || !this.queryInput) return;
            this.queryBtn.addEventListener('click', () => this.handleQuery());
            this.queryInput.addEventListener('keydown', e => {
                if (e.key === 'Enter') { e.preventDefault(); this.handleQuery(); }
            });
            if (this.saveBtn) this.saveBtn.addEventListener('click', () => this.handleSave());
        },

        async handleQuery() {
            const receiptId = this.queryInput.value.trim();
            if (!receiptId) return alert('請輸入單據編號');
            this.queryBtn.disabled = true;
            this.queryBtn.textContent = '查詢中...';
            try {
                const data = await Core.apiFetch(`/api/admin/receipt/${receiptId}`);
                this.currentReceiptId = receiptId;
                this.editor.value = JSON.stringify(data, null, 4);
                this.wrapper.classList.remove('d-none');
            } catch (error) {
                this.wrapper.classList.add('d-none');
                this.currentReceiptId = null;
            } finally {
                this.queryBtn.disabled = false;
                this.queryBtn.textContent = '查詢';
            }
        },

        async handleSave() {
            if (!this.currentReceiptId) return alert('請先查詢單據');
            let parsed;
            try { parsed = JSON.parse(this.editor.value); }
            catch (e) { return alert('JSON 格式錯誤，請檢查語法。\n\n' + e.message); }

            this.saveBtn.disabled = true;
            this.saveBtn.textContent = '儲存中...';
            try {
                const result = await Core.apiFetch(`/api/admin/receipt/${this.currentReceiptId}`, {
                    method: 'PUT', body: JSON.stringify(parsed)
                });
                alert(result.message || '儲存成功');
                this.handleQuery();
            } catch (error) {
                console.error('儲存失敗:', error);
            } finally {
                this.saveBtn.disabled = false;
                this.saveBtn.textContent = '💾 儲存修改';
            }
        }
    };

    const ForceDeleteManager = {
        btn: document.getElementById('forceDeleteBtn'),
        input: document.getElementById('forceDeleteInput'),

        init() {
            if (!this.btn || !this.input) return;
            this.btn.addEventListener('click', this.handleDelete.bind(this));
        },

        async handleDelete() {
            const receiptId = this.input.value.trim();
            if (!receiptId) return alert('請先輸入要刪除的單據編號！');
            Core.confirmAction(`您確定要刪除單號 ${receiptId} 嗎？此操作無法復原。`, async () => {
                try {
                    this.btn.disabled = true;
                    this.btn.innerText = '刪除中...';
                    const result = await Core.apiFetch(`/api/admin/receipt/${receiptId}`, { method: 'DELETE' });
                    if (result && result.success) {
                        alert(result.message);
                        this.input.value = '';
                    } else {
                        alert(`刪除失敗：${result.error}`);
                    }
                } catch (error) {
                    console.error('刪除單據時發生錯誤:', error);
                } finally {
                    this.btn.disabled = false;
                    this.btn.innerText = '確認刪除';
                }
            });
        }
    };

    /* =========================================
       13. 表單綁定 (Form Bindings)
       ========================================= */

    // 匯款帳號
    const bankForm = document.getElementById('bank-form');
    if (bankForm) {
        bankForm.onsubmit = async (e) => {
            e.preventDefault();
            const payload = {
                shop: { bankCode: bankForm.shop_bankCode.value, bankName: bankForm.shop_bankName.value, account: bankForm.shop_account.value },
                fund: { bankCode: bankForm.fund_bankCode.value, bankName: bankForm.fund_bankName.value, account: bankForm.fund_account.value }
            };
            await Core.apiFetch('/api/settings/bank', { method: 'POST', body: JSON.stringify(payload) });
            alert('匯款資訊已更新');
        };
    }

    // 建廟基金設定
    const fundForm = document.getElementById('fund-form');
    if (fundForm) {
        fundForm.onsubmit = async (e) => {
            e.preventDefault();
            await Core.apiFetch('/api/fund-settings', {
                method: 'POST', body: JSON.stringify({ goal_amount: document.getElementById('fund-goal').value })
            });
            alert('更新成功！');
            SettingsManager.fetchFund();
        };
    }

    // 公告與問答 Modal 設定
    const setupFormModal = (btnId, modalId, titleId, newTitle, formId, populateFn) => {
        const form = document.getElementById(formId);
        const btn = document.getElementById(btnId);
        if (!form || !btn) return;

        btn.onclick = () => {
            form.reset();
            const titleEl = document.getElementById(titleId);
            if (titleEl) titleEl.textContent = newTitle;
            if (form.announcementId) form.announcementId.value = '';
            if (form.faqId) form.faqId.value = '';
            UI.openModal(modalId);
        };

        window[`edit${titleId === 'ann-modal-title' ? 'Ann' : 'Faq'}`] = (data) => {
            form.reset();
            const titleEl = document.getElementById(titleId);
            if (titleEl) titleEl.textContent = `編輯${newTitle.replace('新增', '')}`;
            populateFn(form, data);
            UI.openModal(modalId);
        };
    };

    setupFormModal('add-announcement-btn', 'announcement-modal', 'ann-modal-title', '新增公告', 'announcement-form', (form, a) => {
        form.announcementId.value = a._id; form.date.value = a.date; form.title.value = a.title; form.content.value = a.content; form.isPinned.checked = a.isPinned;
    });
    setupFormModal('add-faq-btn', 'faq-modal', 'faq-modal-title', '新增問答', 'faq-form', (form, f) => {
        form.faqId.value = f._id; form.question.value = f.question; form.answer.value = f.answer; form.other_category.value = f.category; form.isPinned.checked = f.isPinned;
    });

    const annForm = document.getElementById('announcement-form');
    if (annForm) annForm.onsubmit = async (e) => {
        e.preventDefault();
        const id = annForm.announcementId.value;
        await Core.apiFetch(id ? `/api/announcements/${id}` : '/api/announcements', {
            method: id ? 'PUT' : 'POST',
            body: JSON.stringify({ date: annForm.date.value, title: annForm.title.value, content: annForm.content.value, isPinned: annForm.isPinned.checked })
        });
        UI.closeModal('announcement-modal');
        ContentManager.fetchAnnouncements();
    };

    const faqForm = document.getElementById('faq-form');
    if (faqForm) faqForm.onsubmit = async (e) => {
        e.preventDefault();
        if (!faqForm.other_category.value) return alert('分類必填');
        const id = faqForm.faqId.value;
        await Core.apiFetch(id ? `/api/faq/${id}` : '/api/faq', {
            method: id ? 'PUT' : 'POST',
            body: JSON.stringify({ question: faqForm.question.value, answer: faqForm.answer.value, category: faqForm.other_category.value, isPinned: faqForm.isPinned.checked })
        });
        UI.closeModal('faq-modal');
        ContentManager.fetchFaqs();
    };

    // 管理員帳號建立
    const adminUserForm = document.getElementById('admin-user-form');
    if (adminUserForm) {
        adminUserForm.onsubmit = async (e) => {
            e.preventDefault();
            await Core.apiFetch('/api/admin/system/users', {
                method: 'POST',
                body: JSON.stringify({
                    username: adminUserForm.username.value.trim(),
                    password: adminUserForm.password.value,
                    role: adminUserForm.role.value
                })
            });
            UI.closeModal('admin-user-modal');
            SystemManager.loadUsers();
        };
    }

    /* =========================================
       14. HTML 內聯事件全域綁定 (Global Bindings)
       ========================================= */

    // 曝露 Manager 到 window，供 HTML onclick 呼叫
    window.FinanceManager = FinanceManager;
    window.OpsManager = OpsManager;
    window.DataManager = DataManager;
    window.SystemManager = SystemManager;

    // --- 財務操作 ---
    window.confirmPayment = (id, orderType) => {
        const msg = orderType === 'shop' ? '確認收款？將回信待出貨通知。' : '確認收到款項？將寄發電子感謝狀。';
        Core.confirmAction(msg, async () => {
            await Core.apiFetch(`/api/orders/${id}/confirm`, { method: 'PUT' });
            FinanceManager.refresh();
        });
    };

    window.deleteOrder = (id, orderType) => {
        Core.confirmAction('確定刪除？系統將寄送取消通知信。', async () => {
            await Core.apiFetch(`/api/orders/${id}`, { method: 'DELETE' });
            FinanceManager.refresh();
        });
    };

    // --- 站務操作 ---
    window.shipOrder = async (id) => {
        const trackNum = prompt('請輸入物流單號 (寄送出貨通知信)：');
        if (trackNum) {
            await Core.apiFetch(`/api/orders/${id}/ship`, { method: 'PUT', body: JSON.stringify({ trackingNumber: trackNum }) });
            alert('已出貨並通知！');
            OpsManager.loadShipQueue();
        }
    };

    // --- 查看詳情 Modal ---
    window.viewDonationDetail = (o) => {
        const body = document.getElementById('donation-detail-body');
        if (!body) return;
        const itemsStr = (o.items || []).map(i => `${i.name} x${i.qty}`).join('、');
        body.innerHTML = `
            <div class="detail-header">
                <p class="mb-5"><strong>單號：</strong> ${o.orderId}</p>
                <p class="mb-0"><strong>送出日期：</strong> ${o.createdAt}</p>
            </div>
            <p><strong>姓名：</strong> ${o.customer?.name || ''}</p>
            <p><strong>電話：</strong> ${o.customer?.phone || '無'}</p>
            <p><strong>農曆生日：</strong> ${o.customer?.lunarBirthday || '未提供'}</p>
            <p><strong>地址：</strong> ${o.customer?.address || '無'}</p>
            <p><strong>匯款後五碼：</strong> ${o.customer?.last5 || '無'}</p>
            <div class="info-box">
                <strong class="text-brown">護持內容：</strong>
                <p class="my-5">${itemsStr}</p>
                <strong class="text-brown fs-18">總金額：$${o.total}</strong>
            </div>
        `;
        UI.openModal('donation-detail-modal');
    };

    window.viewOrderDetails = (o) => {
        const body = document.getElementById('order-detail-body');
        if (!body) return;
        const deliveryInfo = o.customer?.shippingMethod === '711'
            ? `<p><b>取貨:</b> <span class="badge-711-detail">7-11</span> ${o.customer?.storeInfo || '未抓到門市資料'}</p>`
            : `<p><b>地址:</b> ${o.customer?.address || ''}</p>`;

        body.innerHTML = `
            <p><b>訂單編號:</b> ${o.orderId}</p>
            <p><b>建立時間:</b> ${o.createdAt}</p><hr>
            <h4>客戶資料</h4>
            <p><b>姓名:</b> ${o.customer?.name || ''}</p>
            <p><b>電話:</b> ${o.customer?.phone || ''}</p>
            ${deliveryInfo}
            <p><b>Email:</b> ${o.customer?.email || ''}</p>
            <p><b>匯款後五碼:</b> ${o.customer?.last5 || ''}</p><hr>
            <h4>訂單內容</h4>
            <ul>${(o.items || []).map(i => `<li>${i.name} (${i.variantName || i.variant || '標準'}) x${i.qty} - $${i.price * i.qty}</li>`).join('')}</ul>
            <p class="total-price"><b>總金額: $${o.total}</b></p>
            ${o.trackingNumber ? `<hr><p><b>物流單號:</b> ${o.trackingNumber}</p>` : ''}
        `;
        UI.openModal('order-detail-modal');
    };

    // --- 回饋管理 ---
    window.approveFb = (id) => Core.confirmAction('確認核准？(將寄信通知)', async () => {
        await Core.apiFetch(`/api/feedback/${id}/approve`, { method: 'PUT' });
        if (document.getElementById('tab-data')?.classList.contains('active')) DataManager.loadFeedbackReview();
    });

    window.delFb = (id) => Core.confirmAction('確認刪除？(將寄信通知)', async () => {
        await Core.apiFetch(`/api/feedback/${id}`, { method: 'DELETE' });
        if (document.getElementById('tab-data')?.classList.contains('active')) DataManager.loadFeedbackReview();
    });

    window.shipGift = async (id) => {
        const track = prompt('請輸入小神衣物流單號：');
        if (track) {
            await Core.apiFetch(`/api/feedback/${id}/ship`, { method: 'PUT', body: JSON.stringify({ trackingNumber: track }) });
            alert('已標記寄送並通知！');
            if (document.getElementById('tab-ops')?.classList.contains('active')) OpsManager.loadFeedbackGifts();
            if (document.getElementById('tab-data')?.classList.contains('active')) DataManager.loadFeedbackReview();
        }
    };

    window.editFb = (item) => {
        const form = document.getElementById('feedback-edit-form');
        if (!form) return;
        form.feedbackId.value = item._id;
        form.realName.value = item.realName;
        form.nickname.value = item.nickname;
        form.content.value = item.content;
        form.phone.value = item.phone;
        form.address.value = item.address;
        form.category.value = Array.isArray(item.category) ? item.category[0] : item.category;

        form.onsubmit = async (e) => {
            e.preventDefault();
            const data = {
                realName: form.realName.value,
                nickname: form.nickname.value,
                category: [form.category.value],
                content: form.content.value,
                phone: form.phone.value,
                address: form.address.value
            };
            await Core.apiFetch(`/api/feedback/${form.feedbackId.value}`, { method: 'PUT', body: JSON.stringify(data) });
            UI.closeModal('feedback-edit-modal');
            DataManager.loadFeedbackReview();
        };
        UI.openModal('feedback-edit-modal');
    };

    window.viewFbDetail = (item) => {
        const body = document.getElementById('feedback-detail-body');
        if (!body) return;
        const statusHtml = item.status === 'sent'
            ? `<p><strong>寄出時間：</strong> ${item.sentAt || '未知'}</p><p><strong>物流單號：</strong> ${item.trackingNumber || '無'}</p>`
            : `<p><strong>核准時間：</strong> ${item.approvedAt || '未知'}</p>`;

        body.innerHTML = `
            <div class="detail-header">
                <p><strong>編號：</strong> ${item.feedbackId || '無'}</p>${statusHtml}
            </div>
            <p><strong>真實姓名：</strong> ${item.realName}</p>
            <p><strong>暱稱：</strong> ${item.nickname}</p>
            <p><strong>農曆生日：</strong> ${item.lunarBirthday || '未提供'}</p>
            <p><strong>電話：</strong> ${item.phone}</p>
            <p><strong>地址：</strong> ${item.address}</p>
            <p><strong>分類：</strong> ${Array.isArray(item.category) ? item.category.join(', ') : item.category}</p>
            <div class="info-box">
                <strong class="text-brown">回饋內容：</strong><br>
                <div class="pre-wrap mt-10">${item.content}</div>
            </div>
        `;
        UI.openModal('feedback-detail-modal');
    };

    window.printFeedbackList = async () => {
        const [approved, sent] = await Promise.all([
            Core.apiFetch('/api/feedback/status/approved'),
            Core.apiFetch('/api/feedback/status/sent')
        ]);
        const all = [...approved, ...sent];
        if (!all.length) return alert('目前沒有符合資格的名單');

        const pw = window.open('', '_blank');
        pw.document.write(`
            <html><head><title>信徒回饋匯出</title><style>
            body { font-family: "Microsoft JhengHei", "Heiti TC", sans-serif; padding: 40px; max-width: 800px; margin: 0 auto; color: #333; }
            .feedback-item { margin-bottom: 60px; page-break-inside: avoid; }
            .meta { font-size: 14px; color: #666; margin-bottom: 5px; }
            .nickname { font-size: 20px; font-weight: bold; margin-bottom: 15px; }
            .content { font-size: 16px; line-height: 1.8; white-space: pre-wrap; text-align: justify; }
            @media print { body { padding: 0; margin: 2cm; } }
            </style></head><body>
            <h2 style="text-align:center;margin-bottom:50px;border-bottom:2px solid #333;padding-bottom:20px;">信徒回饋匯出清單 (共 ${all.length} 筆)</h2>
            ${all.map(fb => `<div class="feedback-item"><div class="meta">編號: ${fb.feedbackId || '無'}</div><div class="nickname">${fb.nickname}</div><div class="content">${fb.content}</div></div>`).join('')}
            <script>setTimeout(() => window.print(), 500);<\/script>
            </body></html>
        `);
        pw.document.close();
    };

    // --- 內容管理 ---
    window.updLink = async (id, old) => {
        const url = prompt('新網址', old);
        if (url) { await Core.apiFetch(`/api/links/${id}`, { method: 'PUT', body: JSON.stringify({ url }) }); SettingsManager.fetchLinks(); }
    };

    window.delAnn = (id) => Core.confirmAction('刪除？', async () => {
        await Core.apiFetch(`/api/announcements/${id}`, { method: 'DELETE' });
        ContentManager.fetchAnnouncements();
    });

    window.delFaq = (id) => Core.confirmAction('刪除？', async () => {
        await Core.apiFetch(`/api/faq/${id}`, { method: 'DELETE' });
        ContentManager.fetchFaqs();
    });

    /* =========================================
       15. 啟動流程
       ========================================= */
    UI.init();
    Auth.checkSession();
    ReceiptManager.init();
    ForceDeleteManager.init();
});
