import secrets
import urllib.parse
from datetime import datetime, timezone

import requests
from flask import Blueprint, current_app, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash

from database import db, write_audit_log
from extensions import csrf, limiter

auth_bp = Blueprint('auth', __name__)


# =========================================
# LINE OAuth 登入 (前台使用者)
# =========================================

@auth_bp.route('/api/line/login')
def line_login():
    line_channel_id = current_app.config['LINE_CHANNEL_ID']
    line_callback_url = current_app.config['LINE_CALLBACK_URL']

    if not line_channel_id:
        return "伺服器尚未設定 LINE_CHANNEL_ID", 500

    state = secrets.token_hex(16)
    session['line_state'] = state
    next_url = request.args.get('next', '/')
    session['line_next_url'] = next_url

    url = (
        "https://access.line.me/oauth2/v2.1/authorize?"
        "response_type=code&"
        f"client_id={line_channel_id}&"
        f"redirect_uri={urllib.parse.quote(line_callback_url)}&"
        f"state={state}&"
        "scope=profile%20openid"
    )
    return redirect(url)


@auth_bp.route('/api/line/callback')
def line_callback():
    line_channel_id = current_app.config['LINE_CHANNEL_ID']
    line_channel_secret = current_app.config['LINE_CHANNEL_SECRET']
    line_callback_url = current_app.config['LINE_CALLBACK_URL']

    code = request.args.get('code')
    state = request.args.get('state')
    session_state = session.get('line_state')

    if state != session_state:
        return "登入狀態驗證失敗，請重新操作", 400

    token_url = "https://api.line.me/oauth2/v2.1/token"
    headers = {'Content-Type': 'application/x-www-form-urlencoded'}
    data = {
        'grant_type': 'authorization_code',
        'code': code,
        'redirect_uri': line_callback_url,
        'client_id': line_channel_id,
        'client_secret': line_channel_secret
    }

    token_res = requests.post(token_url, headers=headers, data=data)
    if token_res.status_code != 200:
        return f"獲取 Token 失敗: {token_res.text}", 400

    access_token = token_res.json().get('access_token')
    profile_url = "https://api.line.me/v2/profile"
    profile_headers = {'Authorization': f'Bearer {access_token}'}
    profile_res = requests.get(profile_url, headers=profile_headers)

    if profile_res.status_code != 200:
        return "獲取使用者資料失敗", 400

    profile = profile_res.json()
    line_id = profile.get('userId')
    display_name = profile.get('displayName')
    picture_url = profile.get('pictureUrl', '')

    if db is not None:
        db.users.update_one(
            {'lineId': line_id},
            {'$set': {
                'lineId': line_id,
                'displayName': display_name,
                'pictureUrl': picture_url,
                'lastLoginAt': datetime.now(timezone.utc).replace(tzinfo=None)
            },
            '$setOnInsert': {'createdAt': datetime.now(timezone.utc).replace(tzinfo=None)}},
            upsert=True
        )

    session['user_line_id'] = line_id
    session['user_display_name'] = display_name
    session.permanent = True

    next_url = session.pop('line_next_url', '/')
    return redirect(next_url)


# =========================================
# 後台管理員登入 (RBAC 多帳號系統 — 陣列式權限)
# =========================================

def _resolve_permissions(admin_user):
    """從 DB 文件解析權限陣列 (相容舊版 role 字串)"""
    perms = admin_user.get('permissions', [])
    if perms:
        return perms
    # 向下相容：舊資料只有 role 字串
    legacy_role = admin_user.get('role', 'ops')
    if legacy_role == 'super_admin':
        return ['super_admin']
    return [legacy_role]


@auth_bp.route('/admin')
def admin_page():
    return render_template('admin.html')


@auth_bp.route('/api/session_check', methods=['GET'])
def session_check():
    if session.get('admin_logged_in'):
        permissions = session.get('admin_permissions', [])
        if not permissions:
            legacy = session.get('admin_role', 'super_admin')
            permissions = [legacy]
        return jsonify({
            "logged_in": True,
            "username": session.get('admin_username', 'admin'),
            "role": session.get('admin_role', 'super_admin'),
            "permissions": permissions
        })
    return jsonify({"logged_in": False})


@csrf.exempt
@auth_bp.route('/api/login', methods=['POST'])
@limiter.limit("5 per minute")
def api_login():
    data = request.json or {}
    username = data.get('username', '').strip()
    password = data.get('password', '')

    # 方式一：多帳號系統 — 查詢 AdminUser collection
    if username and db is not None:
        admin_user = db.admin_users.find_one({"username": username})
        if admin_user and check_password_hash(admin_user['password_hash'], password):
            permissions = _resolve_permissions(admin_user)
            session['admin_logged_in'] = True
            session['admin_username'] = admin_user['username']
            session['admin_role'] = 'super_admin' if 'super_admin' in permissions else (permissions[0] if permissions else 'ops')
            session['admin_permissions'] = permissions
            session.permanent = True
            write_audit_log(admin_user['username'], '登入系統')
            return jsonify({
                "success": True,
                "message": "登入成功",
                "username": admin_user['username'],
                "role": session['admin_role'],
                "permissions": permissions
            })

    # 方式二：環境變數密碼 (向下相容，視為 super_admin)
    admin_hash = current_app.config['ADMIN_PASSWORD_HASH']
    if admin_hash and check_password_hash(admin_hash, password):
        session['admin_logged_in'] = True
        session['admin_username'] = 'admin'
        session['admin_role'] = 'super_admin'
        session['admin_permissions'] = ['super_admin']
        session.permanent = True
        write_audit_log('admin', '登入系統 (主密碼)')
        return jsonify({
            "success": True,
            "message": "登入成功",
            "username": "admin",
            "role": "super_admin",
            "permissions": ["super_admin"]
        })

    return jsonify({"success": False, "message": "帳號或密碼錯誤"}), 401


@auth_bp.route('/api/logout', methods=['POST'])
def api_logout():
    username = session.get('admin_username', 'unknown')
    write_audit_log(username, '登出系統')
    session.pop('admin_logged_in', None)
    session.pop('admin_username', None)
    session.pop('admin_role', None)
    session.pop('admin_permissions', None)
    return jsonify({"success": True})
