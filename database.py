import os
from datetime import datetime, timezone

from pymongo import ASCENDING, DESCENDING, MongoClient
from pymongo.errors import PyMongoError

db = None
_client = None


def _env_int(name, default):
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _create_index(collection_name, keys, **kwargs):
    if db is None:
        return
    try:
        db[collection_name].create_index(keys, **kwargs)
    except PyMongoError as exc:
        print(f"[MongoDB Index Warning] {collection_name}.{kwargs.get('name', keys)}: {exc}")


def ensure_indexes():
    """Create indexes used by the API hot paths.

    MongoDB create_index is idempotent, so this is safe to run on app startup.
    """
    if db is None:
        return

    _create_index('orders', [('orderId', ASCENDING)], name='orders_order_id')
    _create_index('orders', [('lineId', ASCENDING), ('createdAt', DESCENDING)], name='orders_line_created')
    _create_index('orders', [('lineId', ASCENDING), ('orderType', ASCENDING), ('status', ASCENDING)], name='orders_line_type_status')
    _create_index('orders', [('orderType', ASCENDING), ('status', ASCENDING), ('updatedAt', DESCENDING)], name='orders_type_status_updated')
    _create_index('orders', [('orderType', ASCENDING), ('status', ASCENDING), ('createdAt', DESCENDING)], name='orders_type_status_created')
    _create_index('orders', [('orderType', ASCENDING), ('is_reported', ASCENDING), ('createdAt', DESCENDING)], name='orders_type_reported_created')
    _create_index('orders', [('status', ASCENDING), ('createdAt', DESCENDING)], name='orders_status_created')
    _create_index('orders', [('status', ASCENDING), ('paidAt', ASCENDING)], name='orders_status_paid')
    _create_index('orders', [('status', ASCENDING), ('shippedAt', DESCENDING)], name='orders_status_shipped')
    _create_index('orders', [('status', ASCENDING), ('orderType', ASCENDING), ('updatedAt', DESCENDING)], name='orders_status_type_updated')
    _create_index('orders', [('orderType', ASCENDING), ('status', ASCENDING), ('items.name', ASCENDING)], name='orders_type_status_item')
    _create_index('orders', [('items.name', ASCENDING), ('orderType', ASCENDING), ('status', ASCENDING)], name='orders_item_type_status')

    _create_index('feedback', [('feedbackId', ASCENDING)], name='feedback_feedback_id')
    _create_index('feedback', [('lineId', ASCENDING), ('createdAt', DESCENDING)], name='feedback_line_created')
    _create_index('feedback', [('lineId', ASCENDING), ('status', ASCENDING)], name='feedback_line_status')
    _create_index('feedback', [('status', ASCENDING), ('createdAt', ASCENDING)], name='feedback_status_created')
    _create_index('feedback', [('status', ASCENDING), ('approvedAt', DESCENDING)], name='feedback_status_approved')
    _create_index('feedback', [('status', ASCENDING), ('sentAt', DESCENDING)], name='feedback_status_sent')

    _create_index('users', [('lineId', ASCENDING)], name='users_line_id')
    _create_index('users', [('lastLoginAt', DESCENDING)], name='users_last_login')
    _create_index('admin_users', [('username', ASCENDING)], name='admin_users_username')
    _create_index('settings', [('type', ASCENDING)], name='settings_type')

    _create_index('pickups', [('pickupDate', ASCENDING)], name='pickups_pickup_date')
    _create_index('pickups', [('lineId', ASCENDING), ('pickupDate', DESCENDING)], name='pickups_line_pickup_date')
    _create_index('pickups', [('clothes.clothId', ASCENDING), ('pickupDate', ASCENDING)], name='pickups_cloth_pickup_date')
    _create_index('shipments', [('pickupDate', ASCENDING)], name='shipments_pickup_date')

    _create_index('products', [('category', ASCENDING), ('createdAt', DESCENDING)], name='products_category_created')
    _create_index('products', [('isActive', ASCENDING), ('category', ASCENDING), ('createdAt', DESCENDING)], name='products_active_category_created')
    _create_index('announcements', [('isPinned', DESCENDING), ('_id', DESCENDING)], name='announcements_pinned_id')
    _create_index('faq', [('category', ASCENDING), ('isPinned', DESCENDING), ('createdAt', DESCENDING)], name='faq_category_pinned_created')
    _create_index('audit_log', [('timestamp', DESCENDING)], name='audit_log_timestamp')


def init_db(mongo_uri):
    global db, _client
    if mongo_uri:
        try:
            _client = MongoClient(
                mongo_uri,
                appname='chentien-temple-api',
                maxPoolSize=_env_int('MONGO_MAX_POOL_SIZE', 50),
                minPoolSize=_env_int('MONGO_MIN_POOL_SIZE', 0),
                connectTimeoutMS=_env_int('MONGO_CONNECT_TIMEOUT_MS', 5000),
                serverSelectionTimeoutMS=_env_int('MONGO_SERVER_SELECTION_TIMEOUT_MS', 5000),
                socketTimeoutMS=_env_int('MONGO_SOCKET_TIMEOUT_MS', 20000),
                retryWrites=True,
            )
            db = _client['ChentienTempleDB']
            _client.admin.command('ping')
            ensure_indexes()
            print("--- MongoDB connected ---")
        except Exception as e:
            db = None
            _client = None
            print(f"--- MongoDB connection failed: {e} ---")
    else:
        print("--- Missing MONGO_URI ---")
    return db


def get_client():
    return _client


def write_audit_log(admin_username, action, target='', details=''):
    """Write an admin audit log entry."""
    if db is None:
        return
    try:
        db.audit_log.insert_one({
            "timestamp": datetime.now(timezone.utc).replace(tzinfo=None),
            "admin": admin_username or 'system',
            "action": action,
            "target": target,
            "details": details
        })
    except Exception as e:
        print(f"[AuditLog Error] {e}")
