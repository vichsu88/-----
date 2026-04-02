import secrets
import urllib.parse
from datetime import datetime, timezone

import requests
from flask import Blueprint, current_app, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash

from database import db
from extensions import csrf, limiter

auth_bp = Blueprint('auth', __name__)


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


@auth_bp.route('/admin')
def admin_page():
    return render_template('admin.html')


@auth_bp.route('/api/session_check', methods=['GET'])
def session_check():
    return jsonify({"logged_in": session.get('admin_logged_in', False)})


@csrf.exempt
@auth_bp.route('/api/login', methods=['POST'])
@limiter.limit("5 per minute")
def api_login():
    password = request.json.get('password')
    admin_hash = current_app.config['ADMIN_PASSWORD_HASH']
    if admin_hash and check_password_hash(admin_hash, password):
        session['admin_logged_in'] = True
        session.permanent = True
        return jsonify({"success": True, "message": "登入成功"})
    return jsonify({"success": False, "message": "密碼錯誤"}), 401


@auth_bp.route('/api/logout', methods=['POST'])
def api_logout():
    session.pop('admin_logged_in', None)
    return jsonify({"success": True})
