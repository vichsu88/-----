from functools import wraps
from flask import session, request, redirect, url_for, jsonify


def login_required(f):
    """基本管理員登入檢查 (向下相容，任何已登入管理員皆可通過)"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'admin_logged_in' not in session:
            if request.path.startswith('/api/'):
                return jsonify({"error": "未授權，請先登入"}), 403
            return redirect(url_for('auth.admin_page'))
        return f(*args, **kwargs)
    return decorated_function


def admin_required(roles=None):
    """RBAC 角色權限裝飾器。
    roles: 允許存取的角色列表，例如 ['super_admin', 'finance']。
    roles=None 表示任何已登入管理員皆可存取。
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'admin_logged_in' not in session:
                if request.path.startswith('/api/'):
                    return jsonify({"error": "未授權，請先登入"}), 403
                return redirect(url_for('auth.admin_page'))

            if roles:
                user_role = session.get('admin_role', 'super_admin')
                if user_role not in roles:
                    return jsonify({"error": "權限不足，您的角色無法執行此操作"}), 403

            return f(*args, **kwargs)
        return decorated_function
    return decorator


def user_login_required(f):
    """前台使用者 LINE 登入檢查"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        line_id = session.get('user_line_id')
        if not line_id:
            return jsonify({"error": "請先使用 LINE 登入"}), 401
        return f(*args, **kwargs)
    return decorated_function
