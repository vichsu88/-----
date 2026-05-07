const FINANCE_ACTIONS = new Set([
    'refresh-finance',
    'view-finance-detail',
    'confirm-payment',
    'delete-order',
]);

const DEFAULT_SELECTORS = {
    root: '#tab-finance',
    summary: '#finance-summary',
    pendingList: '#finance-pending-list',
};

function createElement(tag, options = {}) {
    const el = document.createElement(tag);
    if (options.className) el.className = options.className;
    if (options.text !== undefined) el.textContent = String(options.text);
    if (options.dataset) {
        Object.entries(options.dataset).forEach(([key, value]) => {
            if (value !== undefined && value !== null) {
                el.dataset[key] = String(value);
            }
        });
    }
    return el;
}

function appendText(parent, text, className = '') {
    parent.appendChild(createElement('span', { className, text }));
}

function formatMoney(value) {
    const amount = Number(value || 0);
    return amount.toLocaleString('zh-TW', { maximumFractionDigits: 0 });
}

function normalizeOrder(order) {
    return {
        ...order,
        _id: String(order?._id || ''),
        orderId: String(order?.orderId || ''),
        orderType: String(order?.orderType || ''),
        source_label: String(order?.source_label || order?.orderType || '未知'),
        createdAt: String(order?.createdAt || ''),
        paymentDeadline: String(order?.paymentDeadline || ''),
        total: Number(order?.total || 0),
        customer: order?.customer && typeof order.customer === 'object' ? order.customer : {},
        items: Array.isArray(order?.items) ? order.items : [],
    };
}

function setStatus(container, message, className = 'empty-state') {
    if (!container) return;
    container.replaceChildren(createElement('p', { className, text: message }));
}

async function confirmThen(confirmAction, message, task) {
    // 相容兩種呼叫：confirmAction(message) 回傳 boolean，或既有 Core.confirmAction(message, cb)。
    if (confirmAction.length >= 2) {
        return confirmAction(message, task);
    }
    if (await confirmAction(message)) {
        return task();
    }
    return undefined;
}

export function createFinanceModule({
    apiFetch,
    confirmAction = message => window.confirm(message),
    modal = {},
    selectors = {},
    documentRef = document,
} = {}) {
    if (typeof apiFetch !== 'function') {
        throw new Error('createFinanceModule requires apiFetch');
    }

    const config = { ...DEFAULT_SELECTORS, ...selectors };
    const orderCache = new Map();
    let initialized = false;

    function getRoot() {
        return documentRef.querySelector(config.root);
    }

    function getOrderFromButton(button) {
        const order = orderCache.get(button.dataset.id || '');
        if (!order) {
            throw new Error('找不到單據資料，請重新整理後再試。');
        }
        return order;
    }

    function renderSummaryCard(type, statuses) {
        const card = createElement('section', { className: 'card finance-summary-card' });
        const label = createElement('div', {
            className: 'fs-12 text-gray mb-5',
            text: {
                shop: '結緣品',
                donation: '捐香',
                fund: '建廟基金',
                committee: '委員會',
            }[type] || type,
        });
        const pending = statuses.pending || { count: 0, total: 0 };
        const paid = statuses.paid || { count: 0, total: 0 };
        const pendingText = createElement('div', {
            className: 'text-danger fw-bold',
            text: `待收 ${pending.count} 筆 / $${formatMoney(pending.total)}`,
        });
        const paidText = createElement('div', {
            className: 'text-success fs-13',
            text: `已收 ${paid.count} 筆 / $${formatMoney(paid.total)}`,
        });
        card.append(label, pendingText, paidText);
        return card;
    }

    function renderOrderCard(rawOrder) {
        const order = normalizeOrder(rawOrder);
        orderCache.set(order._id, order);

        const card = createElement('article', {
            className: 'feedback-card border-left-danger fb-card-pending-bg',
        });

        const meta = createElement('div', { className: 'card-meta' });
        appendText(meta, order.source_label, 'badge-source');
        appendText(meta, ` 單號: ${order.orderId} | 建立: ${order.createdAt}`);
        if (order.paymentDeadline) {
            appendText(meta, ` | 期限: ${order.paymentDeadline}`);
        }

        const customer = createElement('div');
        const name = createElement('strong', { text: order.customer.name || '未知' });
        customer.append(name);
        appendText(customer, ` / ${order.customer.phone || ''} / `);
        appendText(customer, `$${formatMoney(order.total)}`, 'text-danger fw-bold');

        const items = createElement('div', {
            className: 'text-gray fs-13',
            text: order.items.map(item => `${item.name || ''} x${item.qty || 1}`).join('、'),
        });

        const actions = createElement('div', { className: 'card-actions' });
        actions.append(
            createElement('button', {
                className: 'btn btn--grey',
                text: '查看詳情',
                dataset: { action: 'view-finance-detail', id: order._id },
            }),
            createElement('button', {
                className: 'btn btn--green',
                text: '確認收款',
                dataset: { action: 'confirm-payment', id: order._id },
            }),
            createElement('button', {
                className: 'btn btn--red',
                text: '刪除',
                dataset: { action: 'delete-order', id: order._id },
            }),
        );

        card.append(meta, customer, items, actions);
        return card;
    }

    async function loadSummary() {
        const container = documentRef.querySelector(config.summary);
        if (!container) return;

        const summary = await apiFetch('/api/admin/finance/summary');
        const fragment = document.createDocumentFragment();
        Object.entries(summary || {}).forEach(([type, statuses]) => {
            fragment.appendChild(renderSummaryCard(type, statuses || {}));
        });

        if (!fragment.childNodes.length) {
            setStatus(container, '尚無摘要資料');
            return;
        }
        container.replaceChildren(fragment);
    }

    async function loadPending() {
        const container = documentRef.querySelector(config.pendingList);
        if (!container) return;

        setStatus(container, '載入中...', 'text-gray');
        orderCache.clear();

        const orders = await apiFetch('/api/admin/finance/pending');
        if (!Array.isArray(orders) || !orders.length) {
            setStatus(container, '目前沒有待收款單據');
            return;
        }

        const fragment = document.createDocumentFragment();
        orders.forEach(order => fragment.appendChild(renderOrderCard(order)));
        container.replaceChildren(fragment);
    }

    async function refresh() {
        await Promise.all([loadSummary(), loadPending()]);
    }

    function viewDetail(button) {
        const order = getOrderFromButton(button);
        if (typeof modal.showFinanceOrderDetail === 'function') {
            modal.showFinanceOrderDetail(order);
            return;
        }
        documentRef.dispatchEvent(new CustomEvent('admin:finance:view-detail', {
            detail: { order },
        }));
    }

    async function confirmPayment(button) {
        const order = getOrderFromButton(button);
        const message = order.orderType === 'shop'
            ? '確認收款？此單據會進入待出貨流程。'
            : '確認收到款項？此單據會進入後續站務流程。';

        await confirmThen(confirmAction, message, async () => {
            button.disabled = true;
            try {
                await apiFetch(`/api/orders/${encodeURIComponent(order._id)}/confirm`, { method: 'PUT' });
                await refresh();
            } finally {
                button.disabled = false;
            }
        });
    }

    async function deleteOrder(button) {
        const order = getOrderFromButton(button);
        await confirmThen(confirmAction, '確定刪除這筆單據？系統將依後端規則處理取消通知。', async () => {
            button.disabled = true;
            try {
                await apiFetch(`/api/orders/${encodeURIComponent(order._id)}`, { method: 'DELETE' });
                await refresh();
            } finally {
                button.disabled = false;
            }
        });
    }

    async function handleClick(event) {
        const button = event.target.closest('[data-action]');
        if (!button || !FINANCE_ACTIONS.has(button.dataset.action)) return;
        if (!button.closest(config.root)) return;

        event.preventDefault();
        try {
            switch (button.dataset.action) {
                case 'refresh-finance':
                    await refresh();
                    break;
                case 'view-finance-detail':
                    viewDetail(button);
                    break;
                case 'confirm-payment':
                    await confirmPayment(button);
                    break;
                case 'delete-order':
                    await deleteOrder(button);
                    break;
                default:
                    break;
            }
        } catch (error) {
            console.error('[finance]', error);
            window.alert(error.message || '財務操作失敗，請稍後再試。');
        }
    }

    function init() {
        if (initialized) return;
        documentRef.addEventListener('click', handleClick);
        initialized = true;
    }

    function destroy() {
        if (!initialized) return;
        documentRef.removeEventListener('click', handleClick);
        initialized = false;
        orderCache.clear();
    }

    return {
        init,
        destroy,
        refresh,
        loadPending,
        loadSummary,
    };
}
