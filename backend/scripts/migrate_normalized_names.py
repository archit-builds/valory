"""
Migration: Recompute normalized_name for all organisations using the new
identity-preserving normalization logic.

Old logic stripped stopwords (india, sports, ltd, etc.) which caused
data loss — e.g. "Boxing Federation of India" → "boxing federation of".

New logic is deterministic and lossless — only lowercases, removes
diacritics, replaces punctuation, and collapses whitespace.

Usage (from backend/ with venv activated):
    python -m scripts.migrate_normalized_names
"""
from pymongo import MongoClient

from app.config import settings
from app.resolution.normalize import normalize_org_name


def run() -> None:
    client = MongoClient(settings.MONGO_URI)
    db = client[settings.MONGO_DB_NAME]

    orgs = list(
        db.organisations.find(
            {},
            {"_id": 1, "canonical_name": 1, "normalized_name": 1},
        )
    )

    print(f"Found {len(orgs)} organisation(s). Recomputing normalized_name ...\n")

    updated = 0
    unchanged = 0

    for org in orgs:
        canonical = org.get("canonical_name", "")
        old_norm = org.get("normalized_name", "")
        new_norm = normalize_org_name(canonical)

        if new_norm == old_norm:
            unchanged += 1
            continue

        db.organisations.update_one(
            {"_id": org["_id"]},
            {"$set": {"normalized_name": new_norm}},
        )
        print(f"  UPDATED  {canonical!r}")
        print(f"           old: {old_norm!r}")
        print(f"           new: {new_norm!r}\n")
        updated += 1

    print(f"Done. {updated} updated, {unchanged} already correct (out of {len(orgs)} total).")
    client.close()


if __name__ == "__main__":
    run()
