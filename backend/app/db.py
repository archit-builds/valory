"""
MongoDB connection + index setup.

get_db() is the single entrypoint the rest of the app uses. In tests, it's
monkeypatched to return a mongomock database instead of a real connection —
see tests/conftest.py.
"""
from pymongo import MongoClient, ASCENDING
from pymongo.database import Database

from app.config import settings

_client: MongoClient | None = None
_db: Database | None = None


def get_db() -> Database:
    global _client, _db
    if _db is None:
        _client = MongoClient(settings.MONGO_URI)
        _db = _client[settings.MONGO_DB_NAME]
        ensure_indexes(_db)
    return _db


def ensure_indexes(db: Database) -> None:
    """Idempotent index creation — safe to call on every startup."""
    db.athletes.create_index(
        [("normalized_name", ASCENDING), ("dob", ASCENDING)],
        unique=True,
        name="uniq_athlete_name_dob",
    )
    db.organisations.create_index(
        [("normalized_name", ASCENDING)],
        unique=True,
        name="uniq_org_normalized_name",
    )
    db.organisations.create_index(
        [("known_names.name", ASCENDING)],
        name="known_names_lookup",
    )
    db.athlete_organisation.create_index(
        [("athlete_id", ASCENDING), ("org_id", ASCENDING), ("relation_type", ASCENDING)],
        unique=True,
        name="uniq_athlete_org_relation",
    )
    db.resolution_logs.create_index([("timestamp", ASCENDING)], name="logs_by_time")
