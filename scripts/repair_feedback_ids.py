import argparse
import os
import sys

from dotenv import load_dotenv

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import database
from services.sequence_service import generate_feedback_id
from utils.timezone import utc_now


def _duplicate_feedback_ids(db):
    pipeline = [
        {"$match": {"feedbackId": {"$type": "string", "$gt": ""}}},
        {"$sort": {"approvedAt": 1, "sentAt": 1, "createdAt": 1, "_id": 1}},
        {
            "$group": {
                "_id": "$feedbackId",
                "count": {"$sum": 1},
                "docs": {
                    "$push": {
                        "_id": "$_id",
                        "status": "$status",
                        "createdAt": "$createdAt",
                        "approvedAt": "$approvedAt",
                        "sentAt": "$sentAt",
                    }
                },
            }
        },
        {"$match": {"count": {"$gt": 1}}},
        {"$sort": {"_id": 1}},
    ]
    return list(db.feedback.aggregate(pipeline))


def _next_unused_feedback_id(db):
    for _ in range(50):
        feedback_id = generate_feedback_id()
        if not db.feedback.find_one({"feedbackId": feedback_id}, {"_id": 1}):
            return feedback_id
    raise RuntimeError("Unable to generate an unused feedbackId")


def repair_feedback_ids(db, *, apply=False):
    duplicates = _duplicate_feedback_ids(db)
    if not duplicates:
        print("No duplicate feedbackId values found.")
        return 0

    updates = []
    for group in duplicates:
        keep_doc, *duplicate_docs = group["docs"]
        print(f"Duplicate feedbackId {group['_id']}: keeping {keep_doc['_id']}")
        for doc in duplicate_docs:
            new_id = _next_unused_feedback_id(db) if apply else "<new feedbackId>"
            updates.append((doc["_id"], group["_id"], new_id))
            print(f"  {'update' if apply else 'would update'} {doc['_id']}: {group['_id']} -> {new_id}")

    if not apply:
        print(f"Dry run only. Re-run with --apply to update {len(updates)} document(s).")
        return len(updates)

    now = utc_now()
    for doc_id, _old_id, new_id in updates:
        db.feedback.update_one(
            {"_id": doc_id},
            {"$set": {"feedbackId": new_id, "updatedAt": now}},
        )

    database.ensure_indexes()
    print(f"Updated {len(updates)} duplicate feedback document(s) and re-ran index creation.")
    return len(updates)


def main():
    parser = argparse.ArgumentParser(description="Repair duplicate feedbackId values before creating the unique index.")
    parser.add_argument("--apply", action="store_true", help="Apply updates. Without this flag, only prints a dry run.")
    args = parser.parse_args()

    load_dotenv()
    db = database.init_db(os.environ.get("MONGO_URI"))
    if db is None:
        print("Database is not available", file=sys.stderr)
        return 1

    repair_feedback_ids(db, apply=args.apply)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
