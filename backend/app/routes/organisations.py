from fastapi import APIRouter, Depends
from pymongo.database import Database

from app.db import get_db

router = APIRouter(prefix="/organisations", tags=["organisations"])


@router.get("")
def list_organisations(db: Database = Depends(get_db)):
    orgs = []
    for org in db.organisations.find():
        org["_id"] = str(org["_id"])
        org.pop("embedding", None)  # don't ship raw vectors to the frontend
        orgs.append(org)
    return orgs
