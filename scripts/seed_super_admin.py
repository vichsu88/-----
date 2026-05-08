import os
import sys

from dotenv import load_dotenv
from werkzeug.security import generate_password_hash

import database
from utils.timezone import utc_now


def main():
    load_dotenv()
    username = os.environ.get("SEED_ADMIN_USERNAME", "admin").strip()
    password = os.environ.get("SEED_ADMIN_PASSWORD", "")
    mongo_uri = os.environ.get("MONGO_URI")

    if not password:
        print("SEED_ADMIN_PASSWORD is required", file=sys.stderr)
        return 1

    db = database.init_db(mongo_uri)
    if db is None:
        print("Database is not available", file=sys.stderr)
        return 1

    if db.admin_users.find_one({"username": username}):
        print(f"Admin user already exists: {username}")
        return 0

    db.admin_users.insert_one({
        "username": username,
        "password_hash": generate_password_hash(password),
        "permissions": ["super_admin"],
        "role": "super_admin",
        "createdAt": utc_now(),
    })
    print(f"Created super_admin user: {username}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
