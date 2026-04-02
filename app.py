import os
from datetime import timedelta

from dotenv import load_dotenv
from flask import Flask
from flask_cors import CORS

import database
from extensions import csrf, limiter


def create_app():
    load_dotenv()
    app = Flask(__name__)

    # =========================================
    # 1. 安全性設定
    # =========================================
    is_production = os.environ.get('RENDER') is not None
    _secret_key = os.environ.get('SECRET_KEY')
    if not _secret_key:
        if is_production:
            raise RuntimeError("SECRET_KEY 環境變數未設定，無法啟動生產環境")
        _secret_key = 'dev-insecure-key-do-not-use-in-production'

    app.config['SECRET_KEY'] = _secret_key
    app.config['SESSION_COOKIE_SECURE'] = is_production
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    app.permanent_session_lifetime = timedelta(hours=8)

    # =========================================
    # 2. 應用程式設定
    # =========================================
    app.config['SENDGRID_API_KEY'] = os.environ.get('SENDGRID_API_KEY')
    app.config['MAIL_SENDER'] = os.environ.get('MAIL_USERNAME')
    app.config['LINE_CHANNEL_ID'] = os.environ.get('LINE_CHANNEL_ID')
    app.config['LINE_CHANNEL_SECRET'] = os.environ.get('LINE_CHANNEL_SECRET')
    app.config['LINE_CALLBACK_URL'] = os.environ.get('LINE_CALLBACK_URL')
    app.config['ADMIN_PASSWORD_HASH'] = os.environ.get('ADMIN_PASSWORD_HASH')

    # =========================================
    # 3. 擴充套件初始化
    # =========================================
    csrf.init_app(app)
    limiter.init_app(app)

    allowed_origins = [
        "http://localhost:5000",
        "http://127.0.0.1:5000",
        "http://140.119.143.95:5000",
        "https://yandao.onrender.com",
    ]
    CORS(app, resources={r"/api/*": {"origins": allowed_origins}}, supports_credentials=True)

    # =========================================
    # 4. 資料庫連線
    # =========================================
    database.init_db(os.environ.get('MONGO_URI'))

    # =========================================
    # 5. 註冊 Blueprints
    # =========================================
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
