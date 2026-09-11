from fastapi import APIRouter, Depends, Query
from pymongo import DESCENDING
from pymongo.database import Database

from app.db import get_db

router = APIRouter(prefix="/resolution-logs", tags=["logs"])


@router.get("")
def list_logs(
    db: Database = Depends(get_db),
    limit: int = Query(50, ge=1, le=500),
    skip: int = Query(0, ge=0),
):
    logs = []
    cursor = db.resolution_logs.find().sort("timestamp", DESCENDING).skip(skip).limit(limit)
    for log in cursor:
        log["_id"] = str(log["_id"])
        if log.get("matched_org_id"):
            log["matched_org_id"] = str(log["matched_org_id"])
        logs.append(log)
    return {"total": db.resolution_logs.count_documents({}), "results": logs}
