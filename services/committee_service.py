from repositories.committee_quota_repository import sync_committee_quota_usages
from utils.timezone import utc_now


DEFAULT_COMMITTEE_ROLES = (
    {"name": "[建廟] 籌備主委", "limit": 1, "price": 50000},
    {"name": "[建廟] 籌備副主委", "limit": 10, "price": 36000},
    {"name": "[建廟] 建廟功德金", "limit": 999, "price": 10000},
    {"name": "[顧問] 顧問主席", "limit": 1, "price": 50000},
    {"name": "[顧問] 顧問副主席", "limit": 7, "price": 36000},
    {"name": "[顧問] 顧問", "limit": 999, "price": 20000},
    {"name": "[本府] 主委", "limit": 1, "price": 50000},
    {"name": "[本府] 副主委", "limit": 7, "price": 36000},
    {"name": "[本府] 委員", "limit": 999, "price": 25000},
)


def get_default_committee_roles():
    return [role.copy() for role in DEFAULT_COMMITTEE_ROLES]


def merge_committee_roles(db_roles):
    role_map = {role.get("name"): role for role in (db_roles or []) if role.get("name")}
    return [role_map.get(default["name"], default.copy()) for default in DEFAULT_COMMITTEE_ROLES]


def seed_default_committee_quota(db):
    existing = db.settings.find_one({"type": "committee_quota"}, {"roles": 1})
    if existing and existing.get("roles"):
        return False

    now = utc_now()
    roles = get_default_committee_roles()
    db.settings.update_one(
        {"type": "committee_quota"},
        {
            "$set": {"roles": roles, "updatedAt": now},
            "$setOnInsert": {"createdAt": now},
        },
        upsert=True,
    )
    sync_committee_quota_usages(roles)
    return True
