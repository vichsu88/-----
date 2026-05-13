import urllib.parse

import requests
from flask import current_app, has_app_context
from pymongo.errors import DuplicateKeyError
from werkzeug.security import check_password_hash

import database
from utils.errors import ServiceUnavailableError, ValidationError
from utils.timezone import utc_now


LOCAL_CALLBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}


def _normalized_hostname(host):
    if not host:
        return ""
    if "://" in host:
        return urllib.parse.urlparse(host).hostname or ""
    host = host.rsplit("@", 1)[-1]
    if host.startswith("["):
        return host[1:].split("]", 1)[0].lower()
    return host.split(":", 1)[0].lower()


def _is_local_hostname(host):
    return _normalized_hostname(host) in LOCAL_CALLBACK_HOSTS


def resolve_line_callback_url(configured_callback_url, request_callback_url, request_host):
    if not configured_callback_url:
        return request_callback_url

    configured_host = urllib.parse.urlparse(configured_callback_url).hostname
    if _is_local_hostname(configured_host) and request_host and not _is_local_hostname(request_host):
        return request_callback_url

    return configured_callback_url


def safe_next_url(next_url):
    if not next_url:
        return "/"
    if any(char in next_url for char in ("\\", "\r", "\n")):
        return "/"
    parsed = urllib.parse.urlparse(next_url)
    if parsed.scheme or parsed.netloc or not next_url.startswith("/") or next_url.startswith("//"):
        return "/"
    return next_url


def build_line_authorize_url(line_channel_id, line_callback_url, state):
    if not line_channel_id:
        raise ServiceUnavailableError("LINE_CHANNEL_ID is not configured")
    if not line_callback_url:
        raise ServiceUnavailableError("LINE_CALLBACK_URL is not configured")
    if not state:
        raise ValidationError("OAuth state is missing")
    return (
        "https://access.line.me/oauth2/v2.1/authorize?"
        "response_type=code&"
        f"client_id={line_channel_id}&"
        f"redirect_uri={urllib.parse.quote(line_callback_url)}&"
        f"state={state}&"
        "scope=profile%20openid"
    )


def fetch_line_profile(code, line_channel_id, line_channel_secret, line_callback_url):
    if not code:
        raise ValidationError("LINE login code is missing")
    if not line_channel_id:
        raise ServiceUnavailableError("LINE_CHANNEL_ID is not configured")
    if not line_channel_secret:
        raise ServiceUnavailableError("LINE_CHANNEL_SECRET is not configured")
    if not line_callback_url:
        raise ServiceUnavailableError("LINE_CALLBACK_URL is not configured")

    token_url = "https://api.line.me/oauth2/v2.1/token"
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": line_callback_url,
        "client_id": line_channel_id,
        "client_secret": line_channel_secret,
    }

    try:
        token_res = requests.post(token_url, headers=headers, data=data, timeout=10)
    except requests.RequestException as exc:
        raise ServiceUnavailableError("LINE token service is unavailable") from exc

    if token_res.status_code != 200:
        raise ValidationError("LINE token exchange failed", details={"status_code": token_res.status_code})

    access_token = token_res.json().get("access_token")
    if not access_token:
        raise ValidationError("LINE access token is missing")

    profile_url = "https://api.line.me/v2/profile"
    profile_headers = {"Authorization": f"Bearer {access_token}"}
    try:
        profile_res = requests.get(profile_url, headers=profile_headers, timeout=10)
    except requests.RequestException as exc:
        raise ServiceUnavailableError("LINE profile service is unavailable") from exc

    if profile_res.status_code != 200:
        raise ValidationError("LINE profile fetch failed", details={"status_code": profile_res.status_code})

    return profile_res.json()


def upsert_line_user(profile):
    line_id = profile.get("userId")
    if not line_id:
        raise ValidationError("LINE profile is missing user id")

    display_name = profile.get("displayName")
    picture_url = profile.get("pictureUrl", "")
    now = utc_now()

    if database.db is not None:
        update_doc = {
            "$set": {
                "lineId": line_id,
                "displayName": display_name,
                "pictureUrl": picture_url,
                "lastLoginAt": now,
            },
            "$setOnInsert": {"createdAt": now},
        }
        try:
            database.db.users.update_one({"lineId": line_id}, update_doc, upsert=True)
        except DuplicateKeyError:
            # unique lineId 在高併發登入時可能剛好由另一個請求建立，改走一般更新即可。
            database.db.users.update_one({"lineId": line_id}, {"$set": update_doc["$set"]})

    return {
        "line_id": line_id,
        "display_name": display_name,
        "picture_url": picture_url,
    }


def resolve_permissions(admin_user):
    permissions = admin_user.get("permissions", [])
    if permissions:
        return permissions
    legacy_role = admin_user.get("role", "ops")
    if legacy_role == "super_admin":
        return ["super_admin"]
    return [legacy_role]


def authenticate_admin(username, password, admin_password_hash):
    if username and database.db is not None:
        admin_user = database.db.admin_users.find_one({"username": username})
        if admin_user and check_password_hash(admin_user["password_hash"], password):
            permissions = resolve_permissions(admin_user)
            role = "super_admin" if "super_admin" in permissions else (permissions[0] if permissions else "ops")
            return {
                "username": admin_user["username"],
                "role": role,
                "permissions": permissions,
                "audit_label": admin_user["username"],
            }

    allow_legacy_admin = (
        current_app.config.get("ALLOW_LEGACY_ADMIN", False)
        if has_app_context()
        else False
    )
    if (
        allow_legacy_admin
        and username == "admin"
        and admin_password_hash
        and check_password_hash(admin_password_hash, password)
    ):
        return {
            "username": "admin",
            "role": "super_admin",
            "permissions": ["super_admin"],
            "audit_label": "admin",
        }

    return None
