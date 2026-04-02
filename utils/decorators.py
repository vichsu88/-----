from functools import wraps
from flask import session, request, redirect, url_for, jsonify


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'admin_logged_in' not in session:
            if request.path.startswith('/api/'):
                return jsonify({"error": "未授權，請先登入"}), 403
            return redirect(url_for('auth.admin_page'))
        return f(*args, **kwargs)
    return decorated_function


def user_login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        line_id = session.get('user_line_id')
        if not line_id:
            return jsonify({"error": "請先使用 LINE 登入"}), 401
        return f(*args, **kwargs)
    return decorated_function
