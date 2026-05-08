import logging
import os

from pymongo import ASCENDING, DESCENDING, MongoClient
from pymongo.errors import PyMongoError

from utils.timezone import utc_now

db = None
_client = None
logger = logging.getLogger(__name__)
INDEX_OPTION_KEYS = ('unique', 'sparse', 'partialFilterExpression')


def _env_int(name, default):
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _single_field_name(keys):
    if len(keys) != 1:
        return None
    field_name, _direction = keys[0]
    return field_name


def _normalize_index_keys(keys):
    return [(field, direction) for field, direction in keys]


def _index_option(index_info, option):
    if option in ('unique', 'sparse'):
        return bool(index_info.get(option, False))
    return index_info.get(option)


def _index_matches(index_info, keys, kwargs):
    if _normalize_index_keys(index_info.get('key', [])) != _normalize_index_keys(keys):
        return False

    for option in INDEX_OPTION_KEYS:
        expected = kwargs.get(option, False if option in ('unique', 'sparse') else None)
        if _index_option(index_info, option) != expected:
            return False
    return True


def _has_duplicate_values(collection, field_name, partial_filter=None):
    match_stage = partial_filter or {}
    pipeline = []
    if match_stage:
        pipeline.append({"$match": match_stage})
    pipeline.extend([
        {"$group": {"_id": f"${field_name}", "count": {"$sum": 1}}},
        {"$match": {"count": {"$gt": 1}}},
        {"$limit": 1},
    ])
    return next(collection.aggregate(pipeline), None) is not None


def _drop_conflicting_index_if_safe(collection_name, collection, keys, kwargs):
    index_name = kwargs.get('name')
    if not index_name:
        return True

    existing = collection.index_information().get(index_name)
    if not existing or _index_matches(existing, keys, kwargs):
        return True

    field_name = _single_field_name(keys)
    if kwargs.get('unique') and field_name:
        partial_filter = kwargs.get('partialFilterExpression')
        if _has_duplicate_values(collection, field_name, partial_filter):
            # 舊資料若已有重複值，先保留原索引並提示清理，避免啟動時移除可用索引。
            logger.warning(
                "MongoDB unique index migration skipped because duplicate values exist",
                extra={
                    "event": "mongodb_unique_index_duplicates",
                    "target": collection_name,
                    "index": index_name,
                    "field": field_name,
                },
            )
            return False

    collection.drop_index(index_name)
    return True


def _create_index(collection_name, keys, **kwargs):
    if db is None:
        return
    try:
        collection = db[collection_name]
        if not _drop_conflicting_index_if_safe(collection_name, collection, keys, kwargs):
            return
        collection.create_index(keys, **kwargs)
    except PyMongoError as exc:
        logger.warning(
            "MongoDB index creation failed",
            extra={"event": "mongodb_index_warning", "target": collection_name},
            exc_info=exc,
        )


INDEX_SPECS = (
    ('orders', [('orderId', ASCENDING)], {'name': 'orders_order_id', 'unique': True}),
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

    ('feedback', [('feedbackId', ASCENDING)], {
        'name': 'feedback_feedback_id',
        'unique': True,
        # pending 回饋可能尚未產生編號；只限制已核准後產生的有效字串編號不可重複。
        'partialFilterExpression': {'feedbackId': {'$type': 'string', '$gt': ''}},
    }),
    ('feedback', [('lineId', ASCENDING), ('createdAt', DESCENDING)], {'name': 'feedback_line_created'}),
    ('feedback', [('lineId', ASCENDING), ('status', ASCENDING)], {'name': 'feedback_line_status'}),
    ('feedback', [('status', ASCENDING), ('createdAt', ASCENDING)], {'name': 'feedback_status_created'}),
    ('feedback', [('status', ASCENDING), ('approvedAt', DESCENDING)], {'name': 'feedback_status_approved'}),
    ('feedback', [('status', ASCENDING), ('sentAt', DESCENDING)], {'name': 'feedback_status_sent'}),

    ('users', [('lineId', ASCENDING)], {'name': 'users_line_id', 'unique': True}),
    ('users', [('lastLoginAt', DESCENDING)], {'name': 'users_last_login'}),
    ('admin_users', [('username', ASCENDING)], {'name': 'admin_users_username', 'unique': True}),
    ('counters', [('updatedAt', DESCENDING)], {'name': 'counters_updated_at'}),
    ('committee_quota_usage', [('updatedAt', DESCENDING)], {'name': 'committee_quota_usage_updated'}),
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


def get_db():
    if db is None:
        raise RuntimeError("Database is not initialized")
    return db


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
