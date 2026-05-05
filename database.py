import os
import logging

from pymongo import ASCENDING, DESCENDING, MongoClient
from pymongo.errors import PyMongoError

from utils.timezone import utc_now

db = None
_client = None
logger = logging.getLogger(__name__)


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
        logger.warning(
            "MongoDB index creation failed",
            extra={"event": "mongodb_index_warning", "target": collection_name},
            exc_info=exc,
        )


INDEX_SPECS = (
    ('orders', [('orderId', ASCENDING)], {'name': 'orders_order_id'}),
    ('orders', [('lineId', ASCENDING), ('createdAt', DESCENDING)], {'name': 'orders_line_created'}),
    ('orders', [('lineId', ASCENDING), ('orderType', ASCENDING), ('createdAt', DESCENDING)], {'name': 'orders_line_type_created'}),
    ('orders', [('lineId', ASCENDING), ('orderType', ASCENDING), ('status', ASCENDING)], {'name': 'orders_line_type_status'}),
    ('orders', [('orderType', ASCENDING), ('createdAt', DESCENDING)], {'name': 'orders_type_created'}),
    ('orders', [('orderType', ASCENDING), ('status', ASCENDING), ('updatedAt', DESCENDING)], {'name': 'orders_type_status_updated'}),
    ('orders', [('orderType', ASCENDING), ('status', ASCENDING), ('createdAt', DESCENDING)], {'name': 'orders_type_status_created'}),
    ('orders', [('orderType', ASCENDING), ('status', ASCENDING), ('is_reported', ASCENDING), ('paidAt', ASCENDING)], {'name': 'orders_type_status_reported_paid'}),
    ('orders', [('orderType', ASCENDING), ('is_reported', ASCENDING), ('createdAt', DESCENDING)], {'name': 'orders_type_reported_created'}),
    ('orders', [('status', ASCENDING), ('createdAt', DESCENDING)], {'name': 'orders_status_created'}),
    ('orders', [('status', ASCENDING), ('paidAt', ASCENDING)], {'name': 'orders_status_paid'}),
    ('orders', [('status', ASCENDING), ('shippedAt', DESCENDING)], {'name': 'orders_status_shipped'}),
    ('orders', [('status', ASCENDING), ('orderType', ASCENDING), ('updatedAt', DESCENDING)], {'name': 'orders_status_type_updated'}),
    ('orders', [('orderType', ASCENDING), ('status', ASCENDING), ('items.name', ASCENDING)], {'name': 'orders_type_status_item'}),
    ('orders', [('items.name', ASCENDING), ('orderType', ASCENDING), ('status', ASCENDING)], {'name': 'orders_item_type_status'}),

    ('feedback', [('feedbackId', ASCENDING)], {'name': 'feedback_feedback_id'}),
    ('feedback', [('lineId', ASCENDING), ('createdAt', DESCENDING)], {'name': 'feedback_line_created'}),
    ('feedback', [('lineId', ASCENDING), ('status', ASCENDING)], {'name': 'feedback_line_status'}),
    ('feedback', [('status', ASCENDING), ('createdAt', ASCENDING)], {'name': 'feedback_status_created'}),
    ('feedback', [('status', ASCENDING), ('approvedAt', DESCENDING)], {'name': 'feedback_status_approved'}),
    ('feedback', [('status', ASCENDING), ('sentAt', DESCENDING)], {'name': 'feedback_status_sent'}),

    ('users', [('lineId', ASCENDING)], {'name': 'users_line_id'}),
    ('users', [('lastLoginAt', DESCENDING)], {'name': 'users_last_login'}),
    ('admin_users', [('username', ASCENDING)], {'name': 'admin_users_username'}),
    ('settings', [('type', ASCENDING)], {'name': 'settings_type'}),
    ('temple_fund', [('type', ASCENDING)], {'name': 'temple_fund_type'}),
    ('links', [('name', ASCENDING)], {'name': 'links_name'}),

    ('pickups', [('pickupDate', ASCENDING)], {'name': 'pickups_pickup_date'}),
    ('pickups', [('lineId', ASCENDING), ('pickupDate', DESCENDING)], {'name': 'pickups_line_pickup_date'}),
    ('pickups', [('clothes.clothId', ASCENDING), ('pickupDate', ASCENDING)], {'name': 'pickups_cloth_pickup_date'}),
    ('shipments', [('pickupDate', ASCENDING)], {'name': 'shipments_pickup_date'}),

    ('products', [('category', ASCENDING), ('createdAt', DESCENDING)], {'name': 'products_category_created'}),
    ('products', [('isActive', ASCENDING), ('category', ASCENDING), ('createdAt', DESCENDING)], {'name': 'products_active_category_created'}),
    ('announcements', [('isPinned', DESCENDING), ('_id', DESCENDING)], {'name': 'announcements_pinned_id'}),
    ('announcements', [('isPinned', DESCENDING), ('date', DESCENDING)], {'name': 'announcements_pinned_date'}),
    ('faq', [('category', ASCENDING), ('isPinned', DESCENDING), ('createdAt', DESCENDING)], {'name': 'faq_category_pinned_created'}),
    ('audit_log', [('timestamp', DESCENDING)], {'name': 'audit_log_timestamp'}),
)


def ensure_indexes():
    """Create indexes used by the API hot paths.

    MongoDB create_index is idempotent, so this is safe to run on app startup.
    """
    if db is None:
        return

    for collection_name, keys, kwargs in INDEX_SPECS:
        _create_index(collection_name, keys, **kwargs)


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
            logger.info("MongoDB connected", extra={"event": "mongodb_connected"})
        except Exception as e:
            db = None
            _client = None
            logger.exception("MongoDB connection failed", extra={"event": "mongodb_connection_failed"})
    else:
        logger.warning("Missing MONGO_URI", extra={"event": "mongodb_missing_uri"})
    return db


def get_client():
    return _client


def write_audit_log(admin_username, action, target='', details=''):
    """Write an admin audit log entry."""
    if db is None:
        return
    try:
        db.audit_log.insert_one({
            "timestamp": utc_now(),
            "admin": admin_username or 'system',
            "action": action,
            "target": target,
            "details": details
        })
    except Exception as e:
        logger.exception("Audit log write failed", extra={"event": "audit_log_failed"})
