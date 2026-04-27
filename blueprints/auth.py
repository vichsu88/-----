import secrets

from flask import Blueprint, current_app, jsonify, redirect, render_template, request, session

from database import write_audit_log
from extensions import csrf, limiter
from schemas.auth import AdminLoginSchema
from services.auth_service import (
    authenticate_admin,
    build_line_authorize_url,
    fetch_line_profile,
    safe_next_url,
    upsert_line_user,
)
from utils.errors import AppError
from utils.security import get_json_object
from utils.validation import validate_payload

auth_bp = Blueprint('auth', __name__)


# =========================================
# LINE OAuth 登入 (前台使用者)
# =========================================

@auth_bp.route('/api/line/login')
def line_login():
    line_channel_id = current_app.config['LINE_CHANNEL_ID']
    line_callback_url = current_app.config['LINE_CALLBACK_URL']

    state = secrets.token_hex(16)
    session['line_state'] = state
    next_url = safe_next_url(request.args.get('next', '/'))
    session['line_next_url'] = next_url

    try:
        url = build_line_authorize_url(line_channel_id, line_callback_url, state)
    except AppError as error:
        return error.message, error.status_code
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
    try:
        profile = fetch_line_profile(code, line_channel_id, line_channel_secret, line_callback_url)
        user = upsert_line_user(profile)
    except AppError as error:
        return error.message, error.status_code

    session['user_line_id'] = user['line_id']
    session['user_display_name'] = user['display_name']
    session.permanent = True

    next_url = safe_next_url(session.pop('line_next_url', '/'))
    return redirect(next_url)


# =========================================
# 後台管理員登入 (RBAC 多帳號系統 — 陣列式權限)
# =========================================

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
    payload = validate_payload(AdminLoginSchema, get_json_object())
    auth_result = authenticate_admin(
        payload.username.strip(),
        payload.password,
        current_app.config['ADMIN_PASSWORD_HASH'],
    )

    if auth_result:
        session['admin_logged_in'] = True
        session['admin_username'] = auth_result['username']
        session['admin_role'] = auth_result['role']
        session['admin_permissions'] = auth_result['permissions']
        session.permanent = True
        write_audit_log(auth_result['audit_label'], '登入系統')
        return jsonify({
            "success": True,
            "message": "登入成功",
            "username": auth_result['username'],
            "role": auth_result['role'],
            "permissions": auth_result['permissions']
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
