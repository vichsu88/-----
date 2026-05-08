import os
import time
import logging
from datetime import timedelta

from dotenv import load_dotenv
from flask import Flask, g, jsonify, request
from flask_cors import CORS
from flask_wtf.csrf import CSRFError
from werkzeug.exceptions import HTTPException

import database
from extensions import csrf, limiter
from utils.errors import AppError
from utils.logging_config import configure_logging
from utils.security import validate_request_input


logger = logging.getLogger(__name__)


BLUEPRINT_IMPORTS = (
    ('blueprints.main', 'main_bp'),
    ('blueprints.auth', 'auth_bp'),
    ('blueprints.user', 'user_bp'),
    ('blueprints.pickup', 'pickup_bp'),
    ('blueprints.feedback', 'feedback_bp'),
    ('blueprints.orders', 'orders_bp'),
    ('blueprints.content', 'content_bp'),
    ('blueprints.admin.finance', 'admin_finance_bp'),
    ('blueprints.admin', 'admin_bp'),
)


def _env_int(name, default):
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _set_default_header(response, name, value):
    if name not in response.headers:
        response.headers[name] = value


def _security_headers(is_production):
    csp = (
        "default-src 'self'; "
        "base-uri 'self'; "
        "object-src 'none'; "
        "frame-ancestors 'none'; "
        "form-action 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com data:; "
        "img-src 'self' data: https:; "
        "connect-src 'self' https://api.cloudinary.com; "
        "frame-src https://www.youtube.com https://www.youtube-nocookie.com"
    )
    headers = {
        "Content-Security-Policy": csp,
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "strict-origin-when-cross-origin",
        "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()",
        "Cross-Origin-Opener-Policy": "same-origin",
    }
    if is_production:
        headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains; preload"
    return headers


def _register_blueprints(app):
    for module_name, blueprint_name in BLUEPRINT_IMPORTS:
        module = __import__(module_name, fromlist=[blueprint_name])
        app.register_blueprint(getattr(module, blueprint_name))


def create_app():
    load_dotenv()
    configure_logging()
    app = Flask(__name__)

    slow_request_ms = _env_int('SLOW_REQUEST_MS', 750)
    is_production = os.environ.get('RENDER') is not None
    secure_headers = _security_headers(is_production)

    @app.errorhandler(AppError)
    def handle_app_error(error):
        payload = {"error": error.message, "code": error.code}
        if error.details is not None:
            payload["details"] = error.details
        return jsonify(payload), error.status_code

    @app.errorhandler(CSRFError)
    def handle_csrf_error(error):
        if request.path.startswith('/api/'):
            return jsonify({
                "error": "Security token expired. Please refresh the page and try again.",
                "code": "csrf_error",
            }), 400
        return error.description, 400

    @app.errorhandler(Exception)
    def handle_unexpected_error(error):
        if isinstance(error, HTTPException):
            return error
        logger.exception(
            "Unhandled server error",
            extra={"event": "unhandled_error", "path": request.path, "method": request.method},
        )
        return jsonify({"error": "Internal server error", "code": "internal_server_error"}), 500

    @app.before_request
    def start_request_timer():
        g.request_started_at = time.perf_counter()
        return validate_request_input()

    @app.after_request
    def add_response_headers(response):
        started_at = getattr(g, 'request_started_at', None)
        if started_at is not None:
            elapsed_ms = (time.perf_counter() - started_at) * 1000
            response.headers['X-Response-Time'] = f'{elapsed_ms:.1f}ms'
            if elapsed_ms >= slow_request_ms:
                logger.warning(
                    "Slow request",
                    extra={
                        "event": "slow_request",
                        "method": request.method,
                        "path": request.path,
                        "status_code": response.status_code,
                        "elapsed_ms": round(elapsed_ms, 1),
                        "remote_addr": request.remote_addr,
                    },
                )

        for name, value in secure_headers.items():
            _set_default_header(response, name, value)

        if request.path == '/admin' or request.path.startswith('/api/'):
            _set_default_header(response, "Cache-Control", "no-store, max-age=0")
            _set_default_header(response, "Pragma", "no-cache")

        return response

    secret_key = os.environ.get('SECRET_KEY')
    if not secret_key:
        if is_production:
            raise RuntimeError("SECRET_KEY is required in production")
        secret_key = 'dev-insecure-key-do-not-use-in-production'

    app.config['SECRET_KEY'] = secret_key
    app.config['SESSION_COOKIE_SECURE'] = is_production
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    app.config['MAX_CONTENT_LENGTH'] = _env_int('MAX_CONTENT_LENGTH', 1_000_000)
    app.config['SEND_FILE_MAX_AGE_DEFAULT'] = _env_int(
        'STATIC_CACHE_SECONDS',
        31536000 if is_production else 0,
    )
    app.permanent_session_lifetime = timedelta(hours=8)

    app.config['SENDGRID_API_KEY'] = os.environ.get('SENDGRID_API_KEY')
    app.config['MAIL_SENDER'] = os.environ.get('MAIL_USERNAME')
    app.config['LINE_CHANNEL_ID'] = os.environ.get('LINE_CHANNEL_ID')
    app.config['LINE_CHANNEL_SECRET'] = os.environ.get('LINE_CHANNEL_SECRET')
    app.config['LINE_CALLBACK_URL'] = os.environ.get('LINE_CALLBACK_URL')
    app.config['ADMIN_PASSWORD_HASH'] = os.environ.get('ADMIN_PASSWORD_HASH')
    ratelimit_storage_uri = (
        os.environ.get('RATELIMIT_STORAGE_URI')
        or os.environ.get('REDIS_URL')
        or os.environ.get('CELERY_BROKER_URL')
        or 'memory://'
    )
    # Production 必須使用 Redis 等集中式儲存
    if is_production and ratelimit_storage_uri.strip().lower() == 'memory://':
        raise RuntimeError(
            "RATELIMIT_STORAGE_URI or REDIS_URL is required in production."
        )

    app.config['RATELIMIT_STORAGE_URI'] = ratelimit_storage_uri

    csrf.init_app(app)
    limiter.init_app(app)

    env_origins = [
        origin.strip()
        for origin in os.environ.get('CORS_ORIGINS', '').split(',')
        if origin.strip()
    ]
    allowed_origins = env_origins or [
        "http://localhost:5000",
        "http://127.0.0.1:5000",
        "http://140.119.143.95:5000",
        "https://yandao.onrender.com",
    ]
    CORS(app, resources={r"/api/*": {"origins": allowed_origins}}, supports_credentials=True)

    database.init_db(os.environ.get('MONGO_URI'))

    _register_blueprints(app)

    return app


app = create_app()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
