import os
import sys

from dotenv import load_dotenv

import database
from services.committee_service import seed_default_committee_quota


def main():
    load_dotenv()
    mongo_uri = os.environ.get("MONGO_URI")

    db = database.init_db(mongo_uri)
    if db is None:
        print("Database is not available", file=sys.stderr)
        return 1

    created = seed_default_committee_quota(db)
    if created:
        print("Seeded default committee quota settings")
    else:
        print("Committee quota settings already exist")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
