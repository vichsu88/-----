import os
import time
from datetime import timedelta

from dotenv import load_dotenv
from flask import Flask, g, request
from flask_cors import CORS
import psutil

import database
from extensions import csrf, limiter
from utils.security import validate_request_input


def _env_int(name, default):
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def create_app():
    load_dotenv()
    app = Flask(__name__)

    process = psutil.Process(os.getpid())
    memory_state = {'last_checked': 0.0}
    slow_request_ms = _env_int('SLOW_REQUEST_MS', 750)
    memory_warn_mb = _env_int('MEMORY_WARN_MB', 400)
    memory_check_interval = _env_int('MEMORY_CHECK_INTERVAL_SECONDS', 60)

    @app.before_request
    def start_request_timer():
        g.request_started_at = time.perf_counter()
        return validate_request_input()

    @app.after_request
    def add_perf_headers(response):
        started_at = getattr(g, 'request_started_at', None)
        if started_at is not None:
            elapsed_ms = (time.perf_counter() - started_at) * 1000
            response.headers['X-Response-Time'] = f'{elapsed_ms:.1f}ms'
            if elapsed_ms >= slow_request_ms:
                print(
                    f"[Slow Request] {request.method} {request.path} "
                    f"{response.status_code} {elapsed_ms:.1f}ms",
                    flush=True,
                )

        now = time.monotonic()
        if now - memory_state['last_checked'] >= memory_check_interval:
            memory_state['last_checked'] = now
            mem_mb = process.memory_info().rss / 1024 / 1024
            if mem_mb >= memory_warn_mb:
                print(f"[Memory Warning] RSS {mem_mb:.0f} MB", flush=True)

        return response

    is_production = os.environ.get('RENDER') is not None
    secret_key = os.environ.get('SECRET_KEY')
    if not secret_key:
        if is_production:
            raise RuntimeError("SECRET_KEY is required in production")
        secret_key = 'dev-insecure-key-do-not-use-in-production'

    app.config['SECRET_KEY'] = secret_key
    app.config['SESSION_COOKIE_SECURE'] = is_production
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    app.permanent_session_lifetime = timedelta(hours=8)

    app.config['SENDGRID_API_KEY'] = os.environ.get('SENDGRID_API_KEY')
    app.config['MAIL_SENDER'] = os.environ.get('MAIL_USERNAME')
    app.config['LINE_CHANNEL_ID'] = os.environ.get('LINE_CHANNEL_ID')
    app.config['LINE_CHANNEL_SECRET'] = os.environ.get('LINE_CHANNEL_SECRET')
    app.config['LINE_CALLBACK_URL'] = os.environ.get('LINE_CALLBACK_URL')
    app.config['ADMIN_PASSWORD_HASH'] = os.environ.get('ADMIN_PASSWORD_HASH')

    csrf.init_app(app)
    limiter.init_app(app)

    allowed_origins = [
        "http://localhost:5000",
        "http://127.0.0.1:5000",
        "http://140.119.143.95:5000",
        "https://yandao.onrender.com",
    ]
    CORS(app, resources={r"/api/*": {"origins": allowed_origins}}, supports_credentials=True)

    database.init_db(os.environ.get('MONGO_URI'))

    from blueprints.main import main_bp
    from blueprints.auth import auth_bp
    from blueprints.user import user_bp
    from blueprints.pickup import pickup_bp
    from blueprints.feedback import feedback_bp
    from blueprints.orders import orders_bp
    from blueprints.content import content_bp
    from blueprints.admin import admin_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(user_bp)
    app.register_blueprint(pickup_bp)
    app.register_blueprint(feedback_bp)
    app.register_blueprint(orders_bp)
    app.register_blueprint(content_bp)
    app.register_blueprint(admin_bp)

    return app


app = create_app()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
