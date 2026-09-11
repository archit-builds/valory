"""
Orchestrates the 3-layer org resolution pipeline:

  Layer 1 — Normalize + exact match (free, instant)
  Layer 2 — Gemini embedding similarity (semantic)
  Layer 3 — Groq LLM adjudication (ambiguous band only)

Entry point: resolve_organisation(db, raw_org_name, entity_kind_hint)
Returns: (org_id: ObjectId, resolution_info: dict)
"""
from datetime import datetime, timezone

from bson import ObjectId
from pymongo.database import Database

from app.config import settings
from app.resolution.normalize import normalize_org_name
from app.resolution.embedding_match import get_embedding, find_best_embedding_match
from app.resolution.llm_adjudicate import adjudicate_same_org


def _log_decision(db: Database, **fields) -> None:
    db.resolution_logs.insert_one({**fields, "timestamp": datetime.now(timezone.utc)})


def _create_new_org(
    db: Database, raw_name: str, normalized_name: str, entity_kind: str, matched_via: str
) -> ObjectId:
    now = datetime.now(timezone.utc)
    doc = {
        "canonical_name": raw_name,
        "normalized_name": normalized_name,
        "entity_kind": entity_kind,
        "known_names": [
            {
                "name": normalized_name,
                "matched_via": matched_via,
                "confidence": 1.0,
                "added_at": now,
            }
        ],
        "created_at": now,
        "updated_at": now,
    }
    # Cache the embedding at creation time so future lookups don't need to
    # re-embed this org's canonical name.
    try:
        doc["embedding"] = get_embedding(normalized_name)
    except Exception:
        # If Gemini is unavailable at creation time, org is still created
        # without a cached embedding — it just won't be matchable via
        # Layer 2 until backfilled. Exact/fuzzy-equivalent lookups still work.
        pass

    result = db.organisations.insert_one(doc)
    return result.inserted_id


def _append_known_name(
    db: Database, org_id: ObjectId, normalized_name: str, matched_via: str, confidence: float
) -> None:
    db.organisations.update_one(
        {"_id": org_id},
        {
            "$push": {
                "known_names": {
                    "name": normalized_name,
                    "matched_via": matched_via,
                    "confidence": confidence,
                    "added_at": datetime.now(timezone.utc),
                }
            },
            "$set": {"updated_at": datetime.now(timezone.utc)},
        },
    )


def resolve_organisation(
    db: Database, raw_org_name: str, entity_kind_hint: str = "brand"
) -> tuple[ObjectId, dict]:
    normalized_input = normalize_org_name(raw_org_name)

    # ---------- Layer 1: exact match ----------
    exact_match = db.organisations.find_one(
        {
            "$or": [
                {"normalized_name": normalized_input},
                {"known_names.name": normalized_input},
            ]
        }
    )
    if exact_match:
        info = {
            "input_org_name": raw_org_name,
            "normalized_input": normalized_input,
            "matched_org_id": exact_match["_id"],
            "matched_canonical_name": exact_match["canonical_name"],
            "method": "exact",
            "score": 1.0,
            "llm_reasoning": None,
            "decision": "merged",
        }
        _log_decision(db, **info)
        return exact_match["_id"], info

    # ---------- Layer 2: embedding similarity ----------
    embedding_error = None
    best_org, best_score = None, 0.0
    try:
        best_org, best_score = find_best_embedding_match(db, normalized_input)
    except Exception as exc:
        embedding_error = str(exc)

    if best_org and best_score >= settings.EMBEDDING_AUTO_MERGE_THRESHOLD:
        _append_known_name(db, best_org["_id"], normalized_input, "embedding", best_score)
        info = {
            "input_org_name": raw_org_name,
            "normalized_input": normalized_input,
            "matched_org_id": best_org["_id"],
            "matched_canonical_name": best_org["canonical_name"],
            "method": "embedding",
            "score": best_score,
            "llm_reasoning": None,
            "decision": "merged",
        }
        _log_decision(db, **info)
        return best_org["_id"], info

    ambiguous = (
        best_org is not None and best_score >= settings.EMBEDDING_AMBIGUOUS_FLOOR
    )

    # ---------- Layer 3: LLM adjudication (ambiguous band only) ----------
    if ambiguous:
        try:
            verdict = adjudicate_same_org(best_org["canonical_name"], raw_org_name)
        except Exception as exc:
            # Groq failure on a genuinely ambiguous case: default to new_org
            # rather than guessing, and log exactly why.
            org_id = _create_new_org(
                db, raw_org_name, normalized_input, entity_kind_hint, "new"
            )
            info = {
                "input_org_name": raw_org_name,
                "normalized_input": normalized_input,
                "matched_org_id": None,
                "matched_canonical_name": None,
                "method": "llm",
                "score": best_score,
                "llm_reasoning": f"LLM call failed, defaulted to new_org: {exc}",
                "decision": "new_org",
            }
            _log_decision(db, **info)
            return org_id, info

        if verdict["same"]:
            _append_known_name(
                db, best_org["_id"], normalized_input, "llm", 0.85
            )
            info = {
                "input_org_name": raw_org_name,
                "normalized_input": normalized_input,
                "matched_org_id": best_org["_id"],
                "matched_canonical_name": best_org["canonical_name"],
                "method": "llm",
                "score": best_score,
                "llm_reasoning": verdict["reasoning"],
                "decision": "merged",
            }
            _log_decision(db, **info)
            return best_org["_id"], info
        else:
            org_id = _create_new_org(
                db, raw_org_name, normalized_input, entity_kind_hint, "new"
            )
            info = {
                "input_org_name": raw_org_name,
                "normalized_input": normalized_input,
                "matched_org_id": None,
                "matched_canonical_name": None,
                "method": "llm",
                "score": best_score,
                "llm_reasoning": verdict["reasoning"],
                "decision": "new_org",
            }
            _log_decision(db, **info)
            return org_id, info

    # ---------- No match at all: create new org ----------
    org_id = _create_new_org(db, raw_org_name, normalized_input, entity_kind_hint, "new")
    info = {
        "input_org_name": raw_org_name,
        "normalized_input": normalized_input,
        "matched_org_id": None,
        "matched_canonical_name": None,
        "method": "new" if not embedding_error else "new_embedding_unavailable",
        "score": best_score,
        "llm_reasoning": f"Embedding lookup failed: {embedding_error}" if embedding_error else None,
        "decision": "new_org",
    }
    _log_decision(db, **info)
    return org_id, info
