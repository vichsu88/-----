document.addEventListener('DOMContentLoaded', () => {
    const loginContainer = document.getElementById('login-container');
    const adminContent = document.getElementById('admin-content');
    const loginForm = document.getElementById('login-form');
    const passwordInput = document.getElementById('admin-password');
    const loginError = document.getElementById('login-error');
    const logoutBtn = document.getElementById('logout-btn');
    const linksListDiv = document.getElementById('links-list');

    // --- 主流程：檢查登入狀態 ---
    async function checkSession() {
        const response = await fetch('/api/session_check');
        const data = await response.json();
        if (data.logged_in) {
            showAdminContent();
        } else {
            showLogin();
        }
    }

    // --- 登入表單提交 ---
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

    // --- 登出按鈕 ---
    logoutBtn.addEventListener('click', async () => {
        await fetch('/api/logout', { method: 'POST' });
        showLogin();
    });

    // --- 函式：獲取並顯示連結 ---
    async function fetchLinks() {
        try {
            const response = await fetch('/api/links');
            if (!response.ok) throw new Error('獲取連結失敗');
            const links = await response.json();

            linksListDiv.innerHTML = ''; // 清空列表
            links.forEach(link => {
                const item = document.createElement('div');
                item.className = 'link-item';
                item.innerHTML = `
                    <span>${link.name}</span>
                    <div>
                        <input type="text" value="${link.url}" readonly style="width: 300px; border:none; background:transparent;">
                        <button class="edit-btn" data-id="${link._id}">修改</button>
                    </div>
                `;
                linksListDiv.appendChild(item);
            });
        } catch (error) {
            console.error('Error:', error);
            alert(error.message);
        }
    } // <--- 多餘的括號已被移除

    // --- 顯示/隱藏畫面的函式 ---
    function showLogin() {
        loginContainer.style.display = 'block';
        adminContent.style.display = 'none';
        passwordInput.value = '';
    }

    function showAdminContent() {
        loginContainer.style.display = 'none';
        adminContent.style.display = 'block';
        fetchLinks(); // 登入成功後，載入連結資料
    }
    
    // --- 連結列表的修改邏輯 ---
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
                fetchLinks(); // 成功後重新整理列表
            } catch (error) {
                console.error('Error:', error);
                alert(error.message);
            }
        }
    });

    // --- 啟動！ ---
    checkSession();
});