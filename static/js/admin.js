document.addEventListener('DOMContentLoaded', () => {
    // --- DOM 元素宣告 (新增回饋管理相關元素) ---
    const loginContainer = document.getElementById('login-container');
    const adminContent = document.getElementById('admin-content');
    const loginForm = document.getElementById('login-form');
    const passwordInput = document.getElementById('admin-password');
    const loginError = document.getElementById('login-error');
    const logoutBtn = document.getElementById('logout-btn');
    
    // 連結管理
    const linksListDiv = document.getElementById('links-list');

    // 回饋管理
    const pendingListContainer = document.getElementById('pending-feedback-list');
    const approvedListContainer = document.getElementById('approved-feedback-list');
    const markAllBtn = document.getElementById('mark-all-btn');
    const exportBtn = document.getElementById('export-btn');
    const exportOutputContainer = document.getElementById('export-output-container');
    const exportTextarea = document.getElementById('export-output');


    // --- 函式定義 ---

    // 登入/登出/Session檢查
    async function checkSession() {
        const response = await fetch('/api/session_check');
        const data = await response.json();
        if (data.logged_in) {
            showAdminContent();
        } else {
            showLogin();
        }
    }

    loginForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        loginError.textContent = '';
        const response = await fetch('/api/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ password: passwordInput.value })
        });
        const data = await response.json();
        if (data.success) {
            showAdminContent();
        } else {
            loginError.textContent = data.message || '登入失敗';
        }
    });

    logoutBtn.addEventListener('click', async () => {
        await fetch('/api/logout', { method: 'POST' });
        showLogin();
    });

    function showLogin() {
        loginContainer.style.display = 'block';
        adminContent.style.display = 'none';
        passwordInput.value = '';
    }

    function showAdminContent() {
        loginContainer.style.display = 'none';
        adminContent.style.display = 'block';
        fetchLinks(); 
        // 登入後預設載入回饋列表
        fetchApprovedFeedback();
        fetchPendingFeedback();
    }

    // 連結管理
    async function fetchLinks() {
        try {
            const response = await fetch('/api/links');
            if (!response.ok) throw new Error('獲取連結失敗');
            const links = await response.json();
            linksListDiv.innerHTML = ''; 
            links.forEach(link => {
                const item = document.createElement('div');
                item.className = 'link-item';
                item.innerHTML = `
                    <span class="link-name-display">${link.name}</span>
                    <input class="link-url-display" type="text" value="${link.url}" readonly>
                    <button class="edit-btn btn" data-id="${link._id}">修改</button>
                `;
                linksListDiv.appendChild(item);
            });
        } catch (error) { console.error('Error fetching links:', error); }
    }
    
    linksListDiv.addEventListener('click', async function(event) {
        if (event.target.classList.contains('edit-btn')) {
            const target = event.target;
            const id = target.dataset.id;
            const inputField = target.closest('.link-item').querySelector('input[type="text"]');
            const currentUrl = inputField.value;
            const newUrl = prompt('請輸入新的連結網址：', currentUrl);
            if (newUrl === null || newUrl.trim() === '') return;
            try {
                const response = await fetch(`/api/links/${id}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ url: newUrl })
                });
                if (!response.ok) throw new Error('更新失敗');
                fetchLinks();
            } catch (error) { console.error('Error updating link:', error); }
        }
    });

    // --- ↓↓↓ 全新：回饋管理相關函式 ↓↓↓ ---

    // 獲取並渲染「待審核」列表
    async function fetchPendingFeedback() {
        try {
            const response = await fetch('/api/feedback/pending');
            if (!response.ok) throw new Error('讀取待審核資料失敗');
            const data = await response.json();
            pendingListContainer.innerHTML = '';
            if (data.length === 0) {
                pendingListContainer.innerHTML = '<p>目前沒有待審核的回饋。</p>';
                return;
            }
            data.forEach(item => {
                const card = document.createElement('div');
                card.className = 'feedback-card';
                card.innerHTML = `
                    <div class="feedback-card__header">
                        <span class="feedback-card__info"><span class="nickname">${item.nickname}</span> / ${item.category.join(', ')}</span>
                        <span>${item.createdAt}</span>
                    </div>
                    <p class="feedback-card__content">${item.content}</p>
                    <div class="feedback-card__actions">
                        <button class="btn delete-feedback-btn" data-id="${item._id}">不同意刪除</button>
                        <button class="btn btn--brown approve-feedback-btn" data-id="${item._id}">同意刊登</button>
                    </div>
                `;
                pendingListContainer.appendChild(card);
            });
        } catch (error) { console.error('Error fetching pending feedback:', error); }
    }
    
    // 獲取並渲染「已審核」列表
    async function fetchApprovedFeedback() {
        try {
            const response = await fetch('/api/feedback/approved');
            if (!response.ok) throw new Error('讀取已審核資料失敗');
            const data = await response.json();
            approvedListContainer.innerHTML = '';
             if (data.length === 0) {
                approvedListContainer.innerHTML = '<p>目前沒有已審核的回饋。</p>';
                return;
            }
            data.forEach(item => {
                const card = document.createElement('div');
                card.className = 'feedback-card';
                const isMarked = item.isMarked;
                card.innerHTML = `
                    <div class="feedback-card__header">
                        <span class="feedback-card__info"><span class="nickname">${item.nickname}</span> / ${item.category.join(', ')}</span>
                        <span>${item.createdAt}</span>
                    </div>
                    <p class="feedback-card__content">${item.content}</p>
                    <div class="feedback-card__actions">
                        <button class="btn btn--brown view-feedback-btn" data-id="${item._id}">查看</button>
                    </div>
                `;
                card.querySelector('.view-feedback-btn').addEventListener('click', () => {
                    showDetailModal(item); // 把這筆資料顯示在 modal 裡
                });
                approvedListContainer.appendChild(card);
            });
        } catch (error) { console.error('Error fetching approved feedback:', error); }
    }

    // 處理所有回饋相關的按鈕點擊
    adminContent.addEventListener('click', async (e) => {
        const target = e.target;
        const id = target.dataset.id;

        if (target.classList.contains('approve-feedback-btn')) {
            if (!confirm('確定要同意刊登這則回饋嗎？')) return;
            await fetch(`/api/feedback/${id}/approve`, { method: 'PUT' });
            fetchPendingFeedback(); 
            fetchApprovedFeedback();
        }

        if (target.classList.contains('delete-feedback-btn')) {
             if (!confirm('確定要永久刪除這則回饋嗎？')) return;
             await fetch(`/api/feedback/${id}`, { method: 'DELETE' });
             fetchPendingFeedback();
        }

        if (target.classList.contains('mark-feedback-btn')) {
            const isMarked = target.dataset.marked === 'true';
            await fetch(`/api/feedback/${id}/mark`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ isMarked: !isMarked })
            });
            fetchApprovedFeedback();
        }
    });
    
    // 全部標記按鈕
    markAllBtn.addEventListener('click', async () => {
        if (!confirm('確定要將所有已審核的回饋都標記為已處理嗎？')) return;
        await fetch('/api/feedback/mark-all-approved', { method: 'PUT' });
        fetchApprovedFeedback();
    });

// --- 修改後的輸出寄件資訊邏輯 ---
const exportModal = document.getElementById('export-modal');
const exportTextareaInModal = document.getElementById('export-output-textarea');

exportBtn.addEventListener('click', async () => {
    try {
        const response = await fetch('/api/feedback/export-unmarked');
        const textData = await response.text();
        exportTextareaInModal.value = textData; // 將文字填入彈窗中的 textarea
        exportModal.classList.add('is-visible'); // 顯示彈窗
    } catch (error) {
        console.error('Error exporting data:', error);
        alert('導出時發生錯誤');
    }
});

// 讓彈窗可以被關閉
exportModal.addEventListener('click', (e) => {
    // 如果點擊的是關閉按鈕，或是彈窗的背景
    if (e.target.classList.contains('modal-close-btn') || e.target.id === 'export-modal') {
        exportModal.classList.remove('is-visible');
    }
});

    // --- 主頁籤與子頁籤切換邏輯 ---
    function setupTabs() {
        // 主頁籤
        const mainTabs = document.querySelectorAll('.tab-btn');
        const mainContents = document.querySelectorAll('.tab-content');
        mainTabs.forEach(tab => {
            tab.addEventListener('click', () => {
                mainTabs.forEach(t => t.classList.remove('active'));
                mainContents.forEach(c => c.classList.remove('active'));
                tab.classList.add('active');
                const activeContent = document.getElementById(tab.dataset.tab);
                if(activeContent) activeContent.classList.add('active');
                
                if (tab.dataset.tab === 'tab-feedback') {
                    // 確保預設顯示第一個子頁籤
                    document.querySelector('.sub-tab-btn[data-sub-tab="#approved-list-content"]').click();
                    fetchApprovedFeedback();
                    fetchPendingFeedback();
                } else if (tab.dataset.tab === 'tab-links') {
                    fetchLinks();
                }
            });
        });

        // 子頁籤
        const subTabs = document.querySelectorAll('.sub-tab-btn');
        const subContents = document.querySelectorAll('.sub-tab-content');
        subTabs.forEach(tab => {
            tab.addEventListener('click', () => {
                subTabs.forEach(t => t.classList.remove('active'));
                subContents.forEach(c => c.classList.remove('active'));
                tab.classList.add('active');
                const activeSubContent = document.querySelector(tab.dataset.subTab);
                if(activeSubContent) activeSubContent.classList.add('active');
            });
        });
    }
function showDetailModal(feedback) {
  const modal = document.getElementById('view-modal');
  const body = document.getElementById('view-modal-body');

  const text = `
【真實姓名】${feedback.realName || '(未填)'}
【暱稱】${feedback.nickname}
【類別】${feedback.category.join(', ')}
【寄件地址】${feedback.address || '(未填)'}
【聯絡電話】${feedback.phone || '(未填)'}
【填寫時間】${feedback.createdAt}

【回饋內容】
${feedback.content}
  `;

  body.textContent = text;
  modal.classList.add('is-visible');

  // ✅ 綁定刪除按鈕
  const deleteBtn = document.getElementById('delete-feedback-btn');
  deleteBtn.onclick = async () => {
    const confirmed = confirm('確定要刪除這則回饋嗎？此操作無法復原。');
    if (!confirmed) return;

    try {
      const res = await fetch(`/api/feedback/${feedback._id}`, {
        method: 'DELETE'
      });
      if (!res.ok) throw new Error('刪除失敗');
      alert('已成功刪除該筆回饋');
      closeDetailModal();
      fetchApprovedFeedback();  // 重新載入列表
    } catch (err) {
      alert(err.message);
    }
  };
}

function closeDetailModal() {
  document.getElementById('view-modal').classList.remove('is-visible');
}
// 讓查看 modal 也能關閉
document.getElementById('view-modal').addEventListener('click', (e) => {
  if (e.target.classList.contains('modal-close-btn') || e.target.id === 'view-modal') {
    closeDetailModal();
  }
});
// -------------- FAQ 管理區 --------------

// 1. 元素綁定
const faqListDiv = document.getElementById('faq-list');
const faqCategoryBtnsDiv = document.getElementById('faq-category-btns');
const addFaqBtn = document.getElementById('add-faq-btn');
const faqModal = document.getElementById('faq-modal');
const faqForm = document.getElementById('faq-form');
const faqModalCategoryBtns = document.getElementById('faq-modal-category-btns');

// 2. 狀態
let faqCategories = [];
let currentFaqCategory = '';  // '' 代表全部

// 3. FAQ 主流程
async function fetchFaqCategories() {
  const res = await fetch('/api/faq/categories');
  faqCategories = await res.json();
}

// FAQ 分類按鈕渲染
function renderFaqCategoryBtns() {
  let html = `<button class="sub-tab-btn faq-category-btn" data-category="">全部</button>`;
  faqCategories.forEach(cat => {
    html += `<button class="sub-tab-btn faq-category-btn" data-category="${cat}">${cat}</button>`;
  });
  faqCategoryBtnsDiv.innerHTML = html;
  // 綁定事件
  faqCategoryBtnsDiv.querySelectorAll('.faq-category-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      currentFaqCategory = btn.dataset.category;
      renderFaqCategoryBtns();  // 切換active
      btn.classList.add('active');
      fetchAndRenderFaqs();
    });
  });
  // 設定active
  faqCategoryBtnsDiv.querySelectorAll('.faq-category-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.category === currentFaqCategory);
  });
}

// FAQ 卡片渲染
async function fetchAndRenderFaqs() {
  let url = '/api/faq';
  if (currentFaqCategory) url += '?category=' + encodeURIComponent(currentFaqCategory);
  const res = await fetch(url);
  const faqs = await res.json();
  if (!Array.isArray(faqs) || faqs.length === 0) {
    faqListDiv.innerHTML = `<p>目前沒有問答。</p>`;
    return;
  }
  faqListDiv.innerHTML = faqs.map(faq => `
    <div class="feedback-card" style="border-color:${faq.isPinned ? '#E6BA67' : '#ddd'};">
      <div class="feedback-card__content">
        <b>Q：</b>${faq.question}<br>
        <b>A：</b>${faq.answer}
      </div>
      <div class="feedback-card__actions">
        <button class="btn btn--brown delete-faq-btn" data-id="${faq._id}">刪除</button>
      </div>
    </div>
  `).join('');
  // 綁定刪除
  faqListDiv.querySelectorAll('.delete-faq-btn').forEach(btn => {
    btn.onclick = async () => {
      if (!confirm('確定要刪除這則問答？')) return;
      if (!confirm('真的要永久刪除？此操作無法復原。')) return;
      await fetch(`/api/faq/${btn.dataset.id}`, {method:'DELETE'});
      fetchAndRenderFaqs();
      fetchFaqCategories().then(renderFaqCategoryBtns);
    };
  });
}

// 新增 FAQ 按鈕
addFaqBtn.addEventListener('click', async () => {
  faqForm.reset();
  // 分類按鈕同步現有
  faqModalCategoryBtns.innerHTML = faqCategories.map(cat => 
    `<button type="button" class="btn btn--brown modal-cat-btn" data-cat="${cat}">${cat}</button>`
  ).join('');
  faqModal.classList.add('is-visible');

  // 單選切換
  faqModalCategoryBtns.querySelectorAll('.modal-cat-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      // 選到後直接填到 other_category 並 disable
      faqForm.other_category.value = btn.textContent;
      faqForm.other_category.disabled = true;
      faqModalCategoryBtns.querySelectorAll('.modal-cat-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
    });
  });

  // 若使用者點空白自訂分類則啟用
  faqForm.other_category.addEventListener('focus', () => {
    faqForm.other_category.disabled = false;
    faqModalCategoryBtns.querySelectorAll('.modal-cat-btn').forEach(b => b.classList.remove('active'));
    faqForm.other_category.value = '';
  });
});

// FAQ 浮層關閉
faqModal.addEventListener('click', e => {
  if (e.target.classList.contains('modal-close-btn') || e.target.id === 'faq-modal') {
    faqModal.classList.remove('is-visible');
  }
});

// FAQ 新增表單提交
faqForm.addEventListener('submit', async e => {
  e.preventDefault();
  const question = faqForm.question.value.trim();
  const answer = faqForm.answer.value.trim();
  const category = faqForm.other_category.value.trim();
  const isPinned = faqForm.isPinned.checked;
  if (!question || !answer || !category) {
    alert('請完整填寫');
    return;
  }
  // 驗證分類只能中文
  if (!/^[\u4e00-\u9fff]+$/.test(category)) {
    alert('分類只能輸入中文！');
    return;
  }
  await fetch('/api/faq', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({question, answer, category, isPinned})
  });
  faqModal.classList.remove('is-visible');
  fetchAndRenderFaqs();
  fetchFaqCategories().then(renderFaqCategoryBtns);
});

// 切到問答分頁自動載入
document.querySelector('.tab-btn[data-tab="tab-qa"]').addEventListener('click', async ()=>{
  await fetchFaqCategories();
  renderFaqCategoryBtns();
  fetchAndRenderFaqs();
});

// 預設先載入一次 FAQ
fetchFaqCategories().then(renderFaqCategoryBtns);
fetchAndRenderFaqs();
// --- 公告管理區 (V2 - 查看/刪除模式) ---

// 1. 元素綁定
const announcementsListDiv = document.getElementById('announcements-list');
const addAnnouncementBtn = document.getElementById('add-announcement-btn');

// 新增/編輯用的表單彈窗
const announcementFormModal = document.getElementById('announcement-modal');
const announcementForm = document.getElementById('announcement-form');
const announcementFormTitle = document.getElementById('announcement-modal-title');

// 【全新】查看詳情用的彈窗
const announcementViewModal = document.getElementById('announcement-view-modal');
const announcementViewModalBody = document.getElementById('announcement-view-modal-body');
const deleteAnnouncementFromModalBtn = document.getElementById('delete-announcement-from-modal-btn');


// 2. 渲染公告列表
async function fetchAndRenderAnnouncements() {
    try {
        const response = await fetch('/api/announcements');
        if (!response.ok) throw new Error('無法獲取公告');
        const announcements = await response.json();

        if (announcements.length === 0) {
            announcementsListDiv.innerHTML = '<p>目前沒有任何公告。</p>';
            return;
        }

        announcementsListDiv.innerHTML = announcements.map(item => `
            <div class="feedback-card" style="border-left: 4px solid ${item.isPinned ? '#C48945' : '#ddd'};">
                <div class="feedback-card__header">
                    <span class="feedback-card__info">${item.date}</span>
                    ${item.isPinned ? '<span style="color: #C48945; font-weight: bold;">置頂</span>' : ''}
                </div>
                <p class="feedback-card__content" style="font-weight: bold; font-size: 1.1em; margin-bottom: 10px;">${item.title}</p>
                <div class="feedback-card__actions">
                    <button class="btn btn--brown view-announcement-btn" data-id="${item._id}">查看</button>
                </div>
            </div>
        `).join('');

        // 【全新】為每個「查看」按鈕綁定事件
        announcementsListDiv.querySelectorAll('.view-announcement-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const announcementData = announcements.find(a => a._id === btn.dataset.id);
                if (announcementData) {
                    showAnnouncementDetailModal(announcementData);
                }
            });
        });

    } catch (error) {
        console.error('Error fetching announcements:', error);
        announcementsListDiv.innerHTML = '<p style="color: red;">載入公告失敗。</p>';
    }
}

// 3. 【全新】顯示公告詳情彈窗的函式
function showAnnouncementDetailModal(item) {
    const formattedText = `
【公告日期】${item.date}
【是否置頂】${item.isPinned ? '是' : '否'}

【標題】
${item.title}

【內文】
${item.content}
    `;
    announcementViewModalBody.textContent = formattedText.trim();
    
    // 為彈窗內的刪除按鈕設置點擊事件
    deleteAnnouncementFromModalBtn.onclick = async () => {
        if (!confirm('確定要永久刪除這則公告嗎？此操作無法復原。')) return;

        try {
            const response = await fetch(`/api/announcements/${item._id}`, { method: 'DELETE' });
            if (!response.ok) throw new Error('刪除失敗');
            
            closeAnnouncementDetailModal(); // 關閉彈窗
            fetchAndRenderAnnouncements();  // 重新整理列表
        } catch (error) {
            console.error(error);
            alert('刪除時發生錯誤。');
        }
    };

    announcementViewModal.classList.add('is-visible');
}

// 4. 【全新】關閉詳情彈窗的函式
function closeAnnouncementDetailModal() {
    announcementViewModal.classList.remove('is-visible');
}

// 5. 新增按鈕的邏輯 (不變)
addAnnouncementBtn.addEventListener('click', () => {
    announcementFormTitle.textContent = '新增公告';
    announcementForm.reset();
    announcementForm.announcementId.value = '';
    announcementFormModal.classList.add('is-visible');
});

// 6. 新增表單的提交邏輯 (不變, 只處理新增)
announcementForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const formData = { /* ... 省略，這部分邏輯與之前相同，只處理新增 ... */
        date: announcementForm.date.value.trim(),
        title: announcementForm.title.value.trim(),
        content: announcementForm.content.value.trim(),
        isPinned: announcementForm.isPinned.checked
    };
    // ... 表單驗證 ...
    if (!formData.date || !formData.title || !formData.content) {
        alert('日期、標題和內文為必填欄位。');
        return;
    }
    // ... 提交到 POST ...
    try {
        const response = await fetch('/api/announcements', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(formData)
        });
        if (!response.ok) throw new Error('新增失敗');
        announcementFormModal.classList.remove('is-visible');
        fetchAndRenderAnnouncements();
    } catch (error) {
        alert(`儲存失敗：${error.message}`);
    }
});

// 7. 關閉彈出視窗的通用邏輯
// 關閉「新增」彈窗
announcementFormModal.addEventListener('click', (e) => {
    if (e.target.classList.contains('modal-close-btn') || e.target.id === 'announcement-modal') {
        announcementFormModal.classList.remove('is-visible');
    }
});
// 關閉「查看」彈窗
announcementViewModal.addEventListener('click', (e) => {
    if (e.target.classList.contains('modal-close-btn') || e.target.id === 'announcement-view-modal') {
        closeAnnouncementDetailModal();
    }
});


// 8. 切換到公告分頁時，自動載入
document.querySelector('.tab-btn[data-tab="tab-announcements"]').addEventListener('click', fetchAndRenderAnnouncements);    // --- 啟動！ ---
    checkSession();
    setupTabs();
});