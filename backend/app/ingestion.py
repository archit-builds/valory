"""
Top-level ingestion service. This is what both /athletes/seed (bulk) and
/athletes (single) call. It's the thing that "automatically feeds the
collections" per the project brief:

  athlete JSON in -> athletes upsert -> per-org resolution -> relationship
  edges -> summary report out
"""
from datetime import datetime, timezone

from pymongo.database import Database
from pymongo.errors import DuplicateKeyError

from app.models.schemas import AthleteInput, SeedSummary
from app.resolution.athlete_dedup import resolve_athlete
from app.resolution.pipeline import resolve_organisation


# entity_kind is derived from relation_type / is_person, per spec §4.5
def _infer_entity_kind(link) -> str:
    if link.is_person:
        return "coach"
    if link.relation_type == "training":
        return "training"
    if link.relation_type in ("brand", "ambassador", "endorsement"):
        return "brand"
    return "association"


def ingest_athletes(
    db: Database,
    athletes: list[AthleteInput],
    verbose: bool = True,
) -> SeedSummary:
    athletes_created = 0
    athletes_matched_existing = 0
    orgs_created = 0
    orgs_merged = 0
    relationships_created = 0
    relationships_already_existed = 0
    warnings: list[str] = []

    total = len(athletes)

    for idx, athlete_input in enumerate(athletes, start=1):
        athlete_dict = athlete_input.model_dump()
        athlete_id, was_created = resolve_athlete(db, athlete_dict)

        if was_created:
            athletes_created += 1
            status = "CREATED"
        else:
            athletes_matched_existing += 1
            status = "EXISTS "

        if verbose:
            print(
                f"[{idx:>2}/{total}] {status}  athlete: {athlete_input.full_name}",
                flush=True,
            )

        if not athlete_input.dob:
            warnings.append(
                f"'{athlete_input.full_name}': no DOB provided, dedup used name only"
            )

        for link in athlete_input.organisations:
            entity_kind = _infer_entity_kind(link)
            org_id, resolution_info = resolve_organisation(
                db, link.org_name, entity_kind_hint=entity_kind
            )

            decision = resolution_info["decision"]
            method = resolution_info["method"]
            score = resolution_info["score"]
            canonical = resolution_info.get("matched_canonical_name") or "(new)"

            if decision == "merged":
                orgs_merged += 1
                if verbose:
                    print(
                        f"          ORG  MERGED  [{method}  score={score:.3f}]"
                        f"  {link.org_name!r} → {canonical!r}",
                        flush=True,
                    )
            else:
                orgs_created += 1
                if verbose:
                    print(
                        f"          ORG  NEW     [{method}]"
                        f"  {link.org_name!r}",
                        flush=True,
                    )

            now = datetime.now(timezone.utc)
            try:
                db.athlete_organisation.insert_one(
                    {
                        "athlete_id": athlete_id,
                        "org_id": org_id,
                        "relation_type": link.relation_type,
                        "label": link.label,
                        "source_name_raw": link.org_name,
                        "resolution_method": resolution_info["method"],
                        "confidence_score": resolution_info["score"],
                        "created_at": now,
                    }
                )
                relationships_created += 1
            except DuplicateKeyError:
                # Re-running the seed hits the same (athlete_id, org_id,
                # relation_type) compound key — expected and fine.
                relationships_already_existed += 1

    return SeedSummary(
        athletes_created=athletes_created,
        athletes_matched_existing=athletes_matched_existing,
        orgs_created=orgs_created,
        orgs_merged=orgs_merged,
        relationships_created=relationships_created,
        relationships_already_existed=relationships_already_existed,
        warnings=warnings,
    )

