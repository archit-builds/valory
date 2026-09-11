"""
Athlete-side dedup. Simpler than org resolution because input is manual
JSON authored by one person — no fuzzy/embedding layers needed, just
normalized-name + DOB matching.
"""
from datetime import datetime, timezone
from typing import Optional

from bson import ObjectId
from pymongo.database import Database

from app.resolution.normalize import normalize_athlete_name


def resolve_athlete(db: Database, athlete_input: dict) -> tuple[ObjectId, bool]:
    """
    Returns (athlete_id, was_newly_created).
    Idempotency key: (normalized_name, dob). If dob is missing, falls back
    to normalized_name alone and this is treated as a lower-confidence
    dedup — logged as a warning rather than silently trusted.
    """
    normalized_name = normalize_athlete_name(athlete_input["full_name"])
    dob = athlete_input.get("dob")

    query: dict = {"normalized_name": normalized_name}
    low_confidence_dedup = False
    if dob:
        query["dob"] = dob
    else:
        low_confidence_dedup = True

    existing = db.athletes.find_one(query)
    if existing:
        return existing["_id"], False

    now = datetime.now(timezone.utc)
    doc = {
        "full_name": athlete_input["full_name"],
        "normalized_name": normalized_name,
        "dob": dob,
        "disciplines": athlete_input.get("disciplines", []),
        "events": athlete_input.get("events", []),
        "primary_location": athlete_input.get("primary_location"),
        "state": athlete_input.get("state"),
        "created_at": now,
        "updated_at": now,
    }
    if low_confidence_dedup:
        doc["_dedup_warning"] = "no DOB provided — dedup relied on name only"

    result = db.athletes.insert_one(doc)
    return result.inserted_id, True
