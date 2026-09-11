"""
Run directly (not via the API) to seed the database from athletes_seed.json:

    cd backend
    python -m app.seed.seed_runner

Safe to re-run — idempotent across all three collections (see spec.md /
README for details on the idempotency keys).
"""
import json
from pathlib import Path

from app.db import get_db
from app.ingestion import ingest_athletes
from app.models.schemas import AthleteInput

SEED_FILE = Path(__file__).parent / "athletes_seed.json"


def main():
    with open(SEED_FILE) as f:
        raw_athletes = json.load(f)

    athletes = [AthleteInput(**a) for a in raw_athletes]

    db = get_db()

    print(f"Starting seed: {len(athletes)} athlete(s) from {SEED_FILE.name}")
    print("-" * 60)
    summary = ingest_athletes(db, athletes)
    print("-" * 60)

    print("=== Seed Run Summary ===")
    print(f"Athletes created:              {summary.athletes_created}")
    print(f"Athletes matched existing:     {summary.athletes_matched_existing}")
    print(f"Orgs created:                  {summary.orgs_created}")
    print(f"Orgs merged (dedup hit):       {summary.orgs_merged}")
    print(f"Relationships created:         {summary.relationships_created}")
    print(f"Relationships already existed: {summary.relationships_already_existed}")
    if summary.warnings:
        print("\nWarnings:")
        for w in summary.warnings:
            print(f"  - {w}")

    print("\n--- Resolved organisations ---")
    for org in db.organisations.find():
        aliases = [k["name"] for k in org.get("known_names", [])]
        print(f"  {org['canonical_name']}  (entity_kind={org['entity_kind']})  known_names={aliases}")


if __name__ == "__main__":
    main()
