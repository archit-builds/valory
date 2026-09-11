from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, Depends, HTTPException
from pymongo.database import Database

from app.db import get_db
from app.ingestion import ingest_athletes
from app.models.schemas import AthleteInput, SeedRequest, SeedSummary

router = APIRouter(prefix="/athletes", tags=["athletes"])


def _serialize(doc: dict) -> dict:
    doc["_id"] = str(doc["_id"])
    return doc


@router.post("/seed", response_model=SeedSummary)
def seed_athletes(payload: SeedRequest, db: Database = Depends(get_db)):
    """Bulk-ingest the full athlete JSON array. Safe to re-run — idempotent
    across all three collections."""
    return ingest_athletes(db, payload.athletes)


@router.post("", response_model=SeedSummary)
def add_athlete(payload: AthleteInput, db: Database = Depends(get_db)):
    """Single-athlete version, for incremental additions after the initial seed."""
    return ingest_athletes(db, [payload])


@router.get("")
def list_athletes(db: Database = Depends(get_db)):
    return [_serialize(a) for a in db.athletes.find()]


@router.get("/{athlete_id}")
def get_athlete(athlete_id: str, db: Database = Depends(get_db)):
    try:
        oid = ObjectId(athlete_id)
    except InvalidId:
        raise HTTPException(status_code=400, detail="Invalid athlete id")

    athlete = db.athletes.find_one({"_id": oid})
    if not athlete:
        raise HTTPException(status_code=404, detail="Athlete not found")

    edges = list(db.athlete_organisation.find({"athlete_id": oid}))
    org_ids = [e["org_id"] for e in edges]
    orgs_by_id = {o["_id"]: o for o in db.organisations.find({"_id": {"$in": org_ids}})}

    relationships = []
    for edge in edges:
        org = orgs_by_id.get(edge["org_id"])
        relationships.append(
            {
                "org_id": str(edge["org_id"]),
                "org_canonical_name": org["canonical_name"] if org else None,
                "relation_type": edge["relation_type"],
                "label": edge.get("label"),
                "resolution_method": edge.get("resolution_method"),
            }
        )

    result = _serialize(athlete)
    result["relationships"] = relationships
    return result
