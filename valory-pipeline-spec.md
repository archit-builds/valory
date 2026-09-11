# Valory Athlete–Organisation Resolution Pipeline — Build Spec

## 1. Purpose

Build a backend system that ingests manually-authored athlete JSON records (~20 athletes) and populates three MongoDB collections (`athletes`, `organisations`, `athlete_organisation`), automatically detecting when a new organisation name refers to an already-known organisation (e.g. "Nike" vs "Nike India") to prevent duplicate org documents — without human review (auto-accept model). Every resolution decision must be logged for auditability. A minimal frontend exposes the athlete list, the org canonical list (with known-name history), and the resolution log.

## 2. Tech Stack

- **Backend**: Python 3.11+, FastAPI
- **Database**: MongoDB (local or Atlas)
- **Fuzzy string matching**: `rapidfuzz`
- **Embeddings**: Google Gemini Embedding API (`models/text-embedding-004`, free tier) via `google-generativeai` SDK
- **LLM fallback (ambiguous cases only)**: Groq API, Llama 3.1 8B (free tier)
- **Frontend**: Minimal React (Vite), just list views — no auth, no styling polish required
- **Env vars required**: `MONGO_URI`, `GEMINI_API_KEY`, `GROQ_API_KEY`

## 3. MongoDB Schema

### 3.1 `athletes`
```json
{
  "_id": ObjectId,
  "full_name": "PV Sindhu",
  "normalized_name": "pv sindhu",       // lowercase, punctuation stripped, for dedup key
  "dob": "1995-07-05",                  // nullable
  "disciplines": ["Badminton"],
  "events": ["Olympics 2016", "World Championships 2019"],
  "primary_location": "Hyderabad",       // nullable, not used in resolution logic
  "state": "Telangana",                  // nullable
  "created_at": ISODate,
  "updated_at": ISODate
}
```
**Idempotency key**: `normalized_name + dob` (if DOB missing, fall back to `normalized_name` alone and log a warning — flag as lower-confidence dedup).
**Index**: unique compound index on `(normalized_name, dob)`.

### 3.2 `organisations`
```json
{
  "_id": ObjectId,
  "canonical_name": "Nike",
  "normalized_name": "nike",             // stripped of legal/regional suffixes
  "entity_kind": "brand",                // brand | training | coach | association  (see 4.4)
  "known_names": [
    {
      "name": "nike",
      "matched_via": "seed",             // seed | exact | fuzzy | embedding | llm
      "confidence": 1.0,
      "added_at": ISODate
    }
  ],
  "created_at": ISODate,
  "updated_at": ISODate
}
```
**Idempotency key**: `normalized_name` (post-resolution — i.e. this is looked up via the resolution pipeline, not a raw exact key, since the whole point is fuzzy matches shouldn't create new docs).
**Index**: unique index on `normalized_name`, plus a text/searchable index across `known_names.name` for fast Layer 1 lookups.

### 3.3 `athlete_organisation`
```json
{
  "_id": ObjectId,
  "athlete_id": ObjectId,
  "org_id": ObjectId,
  "relation_type": "brand",              // brand | training | association | ambassador | endorsement (enum, validated)
  "label": "Brand Ambassador",           // free-text descriptor from input JSON
  "source_name_raw": "Nike India",       // the exact string as it appeared in input, pre-resolution
  "resolution_method": "fuzzy",          // seed | exact | fuzzy | embedding | llm
  "confidence_score": 0.94,
  "created_at": ISODate
}
```
**Idempotency key**: `athlete_id + org_id + relation_type` (compound unique index — prevents duplicate edges on re-seed).

### 3.4 `resolution_logs` (audit trail — separate collection, append-only)
```json
{
  "_id": ObjectId,
  "input_org_name": "Nike India",
  "normalized_input": "nike india",
  "matched_org_id": ObjectId,            // null if new org created
  "matched_canonical_name": "Nike",      // null if new org created
  "method": "fuzzy",                     // exact | fuzzy | embedding | llm | new
  "score": 0.94,
  "llm_reasoning": null,                 // populated only when method = llm
  "decision": "merged",                  // merged | new_org
  "timestamp": ISODate
}
```

## 4. Resolution Pipeline (core logic)

Runs once per organisation name encountered while processing an athlete's JSON record. Input: raw org name string. Output: `org_id` (existing or newly created) + logged decision.

### 4.1 Layer 1 — Normalize + Exact Match
1. Lowercase, strip punctuation.
2. Strip a configurable stopword list of legal/regional suffixes: `india`, `pvt`, `ltd`, `inc`, `corp`, `corporation`, `group`, `sports`, `co`, `limited`, `international`, `foundation`.
3. Collapse whitespace.
4. Look up `normalized_name` against `organisations.normalized_name` (exact) AND against every `known_names[].name` (exact) across all org docs.
5. If exact match found → `method=exact`, `confidence=1.0`, decision=`merged`. Stop here.

### 4.2 Layer 2 — Fuzzy String Match (rapidfuzz)
1. If no exact match, compute `token_sort_ratio` and `token_set_ratio` (rapidfuzz) between the normalized input and every existing org's `normalized_name` + `known_names[].name`.
2. Take the best score across both metrics and all candidates.
3. If best score ≥ **92** → `method=fuzzy`, decision=`merged`, append to matched org's `known_names[]` with `matched_via: fuzzy`.
4. If score is between **75–91** → do NOT decide yet, pass to Layer 3 carrying the best candidate found so far.
5. If score < 75 → pass to Layer 3 with no strong candidate.

### 4.3 Layer 3 — Embedding Similarity (Gemini)
1. Generate embedding for the input org name via Gemini `text-embedding-004`.
2. Compare (cosine similarity) against pre-computed embeddings of all existing orgs' canonical names (cache these — recompute only when a new org is created, don't re-embed on every lookup).
3. If cosine similarity ≥ **0.88** → `method=embedding`, decision=`merged`, append to `known_names[]`.
4. If similarity is between **0.75–0.87**, OR Layer 2 flagged a 75–91 fuzzy candidate → pass to Layer 4 (ambiguous band).
5. If similarity < 0.75 and no fuzzy candidate either → decision=`new_org`, create new org doc, `method=new`.

### 4.4 Layer 4 — LLM Adjudication (Groq Llama 3.1 8B) — ambiguous band only
1. Prompt: *"Organisation A: '{existing_canonical_name}'. Organisation B: '{input_name}'. Are these the same real-world organisation (accounting for regional subsidiaries, abbreviations, and rebranding)? Reply with strict JSON: {"same": true|false, "reasoning": "<one sentence>"}."*
2. If `same: true` → `method=llm`, decision=`merged`, append to `known_names[]` with the LLM's stated confidence (or default 0.85 if not returned), log `llm_reasoning`.
3. If `same: false` → decision=`new_org`, create new org doc, `method=llm`, log reasoning.
4. **This is auto-accept per project decision — no human review queue.** All LLM decisions still get fully logged in `resolution_logs` for later audit.

### 4.5 Entity Kind Classification (`entity_kind`)
Read directly from input JSON's `relation_type` on first creation of the org — map: `brand`/`ambassador`/`endorsement` → `entity_kind: brand`; `training` → `entity_kind: training`; if the "org" is clearly a person's name acting as a coach (heuristic: input explicitly tags it, e.g. `"is_person": true` in JSON, or relation_type = `coaching`) → `entity_kind: coach`. This field is descriptive only — it does not gate resolution logic (an org can have athletes linking to it under multiple relation_types regardless of its stored `entity_kind`).

## 5. Athlete Dedup (separate, simpler check)

Before inserting an athlete doc:
1. Normalize `full_name` (lowercase, strip punctuation/periods — `"P.V. Sindhu"` → `"pv sindhu"`).
2. Look up `(normalized_name, dob)` exact match.
3. If DOB is missing on either side, fall back to `normalized_name` alone, but log a `low_confidence_dedup` warning — do not silently auto-skip.
4. If found → treat as existing athlete, attach new org relations to that athlete_id instead of creating a duplicate.

## 6. API Endpoints

- `POST /athletes/seed` — accepts full 20-athlete JSON array, runs the full pipeline (athlete dedup → org resolution per org mentioned → relationship edge creation), returns a summary report (created vs merged counts).
- `POST /athletes` — single-athlete version of the above, for future incremental additions.
- `GET /organisations` — list all orgs with canonical name + known_names.
- `GET /athletes` — list all athletes.
- `GET /athletes/{id}` — single athlete with resolved org relationships joined in.
- `GET /resolution-logs` — paginated audit log.

## 7. Seed Input JSON Shape (example)

```json
[
  {
    "full_name": "PV Sindhu",
    "dob": "1995-07-05",
    "disciplines": ["Badminton"],
    "events": ["Olympics 2016", "World Championships 2019"],
    "primary_location": "Hyderabad",
    "state": "Telangana",
    "organisations": [
      { "org_name": "Nike", "relation_type": "brand", "label": "Brand Ambassador" },
      { "org_name": "Gopichand Academy", "relation_type": "training", "label": "Trains at" }
    ]
  },
  {
    "full_name": "Neeraj Chopra",
    "dob": "1997-12-24",
    "disciplines": ["Javelin Throw"],
    "events": ["Olympics 2020"],
    "primary_location": "Panipat",
    "state": "Haryana",
    "organisations": [
      { "org_name": "Nike India", "relation_type": "brand", "label": "Sponsored Athlete" }
    ]
  }
]
```
Note: the 20-athlete seed set must deliberately include several intentional near-duplicate org names (e.g. "Nike" / "Nike India") to exercise all four resolution layers, plus at least one coach-as-org case and one org shared across two different relation_types (e.g. SAI as both training and association for two different athletes).

## 8. Edge Cases to Handle Defensively

1. Missing/null fields (DOB, location, state) — insert what's present, log what's missing, never crash.
2. Re-running the seed script must be fully idempotent across all three collections and `resolution_logs` should not duplicate identical prior decisions on unchanged input (optional: skip re-logging if input hash matches a prior log entry).
3. Org shared across relation_types for different athletes — one org doc, multiple edges, no special-casing needed beyond what's in 4.5.
4. Personal coaches stored as `organisations` docs with `entity_kind: coach`.
5. Gemini/Groq API failures — wrap in try/except, fall back gracefully (e.g. if Gemini embedding call fails, skip to Layer 4 LLM directly with a logged fallback reason; if Groq fails, default to `new_org` and log the failure explicitly rather than guessing).

## 9. Project Structure (suggested)

```
/backend
  /app
    main.py                 # FastAPI app, route registration
    db.py                   # Mongo client, index setup
    models/
      athlete.py
      organisation.py
      relationship.py
    resolution/
      normalize.py          # Layer 1
      fuzzy_match.py        # Layer 2
      embedding_match.py    # Layer 3 (Gemini)
      llm_adjudicate.py     # Layer 4 (Groq)
      pipeline.py           # orchestrates layers 1-4, returns org_id + log entry
    routes/
      athletes.py
      organisations.py
      logs.py
    seed/
      athletes_seed.json
      seed_runner.py
  requirements.txt
  .env.example
/frontend
  (minimal React/Vite app — athlete list, org list w/ known_names, resolution log viewer)
```

## 10. Success Criteria

- Running the seed script once on the 20-athlete JSON populates all 3 collections correctly with zero manual DB edits.
- Running the seed script a second time produces zero new duplicate documents in any collection.
- The intentional Nike/Nike India (and similar) test cases resolve to a single org document.
- `resolution_logs` shows a clear, inspectable decision trail for every org name processed, including which layer resolved it and why.
