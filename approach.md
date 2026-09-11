# Valory Pipeline — Approach & Design Document

## What this project does in one line

It takes raw athlete data (with messy sponsor/organisation names like "Nike India",
"Nike", "NIKE") and automatically figures out that they all mean the same real-world
brand — so you end up with one clean "Nike" record, not three duplicates.

---

## The big picture

```
Raw athlete JSON
      ↓
Athlete deduplication   ← is this athlete already in the DB?
      ↓
For each organisation the athlete is linked to:
      ↓
  Layer 1: Normalize + Exact Match   ← free, instant
      ↓ (if no match)
  Layer 2: Gemini Embedding Match    ← embedding similarity (RETRIEVAL_DOCUMENT mode)
      ↓ (if score is in "unsure" range)
  Layer 3: Groq LLM Adjudication    ← ask an LLM to decide
      ↓
Store the athlete, the canonical org, and the relationship
Log every decision made (which layer, what score, what reasoning)
```

---

## The three MongoDB collections

### 1. `athletes`
Stores one document per real-world athlete.

```json
{
  "full_name": "PV Sindhu",
  "normalized_name": "pv sindhu",
  "dob": "1995-07-05",
  "disciplines": ["Badminton"],
  "events": ["Olympics 2016"],
  "primary_location": "Hyderabad",
  "state": "Telangana"
}
```

### 2. `organisations`
Stores one document per canonical (real-world unique) organisation.
All alternate names an org has been seen under are stored in `known_names`.

```json
{
  "canonical_name": "Nike",
  "normalized_name": "nike",
  "entity_kind": "brand",
  "known_names": [
    { "name": "nike",        "matched_via": "new",       "confidence": 1.0 },
    { "name": "nike india",  "matched_via": "llm",       "confidence": 0.85 }
  ],
  "embedding": [0.023, -0.14, ...]
}
```

### 3. `athlete_organisation` (the link/edge collection)
Connects athletes to organisations. One row per athlete-org-relationship.
The athlete document itself does NOT store org IDs.

```json
{
  "athlete_id":        "<ObjectId>",
  "org_id":            "<ObjectId>",
  "relation_type":     "brand",
  "label":             "Kit Sponsor",
  "source_name_raw":   "Nike India",
  "resolution_method": "llm",
  "confidence_score":  0.91
}
```

---

## How athlete deduplication works

**Goal:** Don't create the same athlete twice if the seed is re-run.

**Idempotency key:** `normalized_name` + `dob`

- If an athlete with the same normalized name AND same date of birth already
  exists → return the existing athlete's ID, don't insert a new one.
- If DOB is missing → fall back to normalized name only. This works most of
  the time but is flagged with a warning field `_dedup_warning` on the document
  because two different people could share the same name.

**What normalization does for athlete names:**
- Lowercase everything
- Remove punctuation
- Collapse multiple spaces
- Strip diacritics (accents) via Unicode NFKD

So `"P.V. Sindhu"` and `"PV Sindhu"` both normalize to `"pv sindhu"` → same athlete.

---

## Organisation Resolution — Layer 1: Normalize + Exact Match

**Goal:** Catch obvious duplicates for free without calling any external API.

**What the normalization does:**
1. Unicode normalize (NFKD) — strips accents, diacritics
2. Lowercase everything
3. Replace `&` with `and`
4. Remove all punctuation (replace with a space, so "Pvt. Ltd." → "pvt ltd", not "pvtltd")
5. Collapse multiple spaces, trim

**What it does NOT do (intentionally):**
- Does NOT remove words like "india", "sports", "pvt", "ltd" etc.
- Does NOT truncate the name
- Does NOT use a stopword list

**Why not remove words?**
Earlier the pipeline stripped words like "india", "pvt", "sports" from org names.
This caused data corruption — "Boxing Federation of India" became
"boxing federation of" and "Sports Authority of India" became "authority of".
Normalization should only standardize the surface form, not decide what's semantically
meaningful. That job belongs to Layer 2 and Layer 3.

**Examples:**
```
"NIKE India"              → "nike india"
"JSW Sports Pvt. Ltd."   → "jsw sports pvt ltd"
"Boxing Federation of India" → "boxing federation of india"
"Café & Sport"            → "cafe and sport"
"  Nike   India  "        → "nike india"
```

**How exact match works:**
After normalizing the incoming name, the pipeline searches the `organisations`
collection for any doc where either:
- `normalized_name` equals the normalized input, OR
- Any entry in `known_names` equals the normalized input

If found → **merged** with that org. Layer 2 and 3 are never called.
This is the cheapest possible match — a single DB query.

---

## Organisation Resolution — Layer 2: Gemini Embedding Match

**Goal:** Catch near-duplicates that exact matching can't — abbreviations,
missing/extra words, reordered words.

**How it works:**
1. Call the Gemini embedding API (`gemini-embedding-001`) on the normalized
   input name. This converts the text into a list of ~3000 numbers (a vector).
2. Compare this vector against the cached embedding of every existing org in the DB
   using **cosine similarity** (a number from 0.0 to 1.0, where 1.0 = identical).
3. Find the org with the highest similarity score.

**The embedding is cached on the org document** (`organisations.embedding`).
So each org's embedding is computed only once — when the org is first created.
Future lookups compare the incoming name's embedding to all cached ones.

**What task_type to use:**
The embedding API offers different task modes. We use `RETRIEVAL_DOCUMENT`
(not `SEMANTIC_SIMILARITY`). Why? `SEMANTIC_SIMILARITY` groups all
sportswear brands together — Nike and Adidas scored 0.91 similarity, causing
a false merge. `RETRIEVAL_DOCUMENT` is stricter about identity-level matching.

**Score thresholds:**

| Score range | What it means | Action |
|---|---|---|
| ≥ 0.94 | Very confident — same org | Auto-merge, no LLM call |
| 0.82 – 0.94 | Unsure — could go either way | Send to Layer 3 (LLM) |
| < 0.82 | Too different | Treat as a new org |

**Real-world scores observed (RETRIEVAL_DOCUMENT):**
```
"nike"  vs  "nike india"          → 0.91  (ambiguous band → LLM → same: true  → merged ✓)
"adidas" vs  "adidas india"       → 0.92  (ambiguous band → LLM → same: true  → merged ✓)
"nike"  vs  "adidas"              → 0.85  (ambiguous band → LLM → same: false → new org ✓)
"gopichand academy" vs "gopichand badminton academy" → 0.99 (above 0.94 → auto-merged ✓)
"sports authority of india" vs "sai" → 0.80 (below 0.82 floor → new org, no LLM call ✓)
```

**Edge case — what if Gemini API fails?**
The pipeline catches the exception, sets `method = "new_embedding_unavailable"`,
logs the error reason, and falls through to creating a new org. The org still
gets created correctly — it just won't be matchable via embedding until its
embedding is backfilled manually.

---

## Organisation Resolution — Layer 3: Groq LLM Adjudication

**Goal:** For the ambiguous score band (0.82–0.94), ask an LLM to make the
final call. The LLM has world knowledge — it knows that "Nike India" is Nike's
Indian subsidiary, or that "SAI" means "Sports Authority of India".

**How it works:**
The pipeline sends this prompt to Groq:

```
Organisation A: "Nike"
Organisation B: "Nike India"

Are these the same real-world organisation, accounting for regional
subsidiaries, abbreviations, and rebranding?
Reply with strict JSON only: {"same": true or false, "reasoning": "<one sentence>"}
```

The LLM returns `same: true` or `same: false` with a reason.
- `same: true` → merge the incoming org into the existing one, log reasoning
- `same: false` → create a new org, log reasoning

**Every LLM call is logged** in `resolution_logs` with the full reasoning text.
This creates a full audit trail of why every decision was made.

**Edge case — what if the LLM API fails?**
The pipeline catches the exception, defaults to creating a new org (safer than
guessing a merge), and logs the failure reason. This means if your Groq key
is invalid or the model name is wrong, everything silently becomes "new org"
with no crash — check `resolution_logs` to diagnose.

**Known model name pitfall:**
The Groq model `llama-3.1-8b-instant` was deprecated. All LLM calls silently
failed with 404 and every ambiguous org became a new org instead of merging.
Always verify the model name is available on your Groq account. Currently using
`groq/compound-mini`.

---

## The resolution_logs collection

Every single org resolution writes a log entry. This is the audit trail.

```json
{
  "input_org_name":         "Nike India",
  "normalized_input":       "nike india",
  "matched_org_id":         "<ObjectId>",
  "matched_canonical_name": "Nike",
  "method":                 "llm",
  "score":                  0.9114,
  "llm_reasoning":          "Nike India is the Indian subsidiary of Nike, Inc.",
  "decision":               "merged",
  "timestamp":              "2026-09-11T10:51:10Z"
}
```

**`method` values:**
- `exact` — matched via Layer 1 (exact normalized name)
- `embedding` — auto-merged by Layer 2 (score ≥ 0.94)
- `llm` — Layer 3 LLM made the decision (either merged or new)
- `new` — no match at all, created as new org
- `new_embedding_unavailable` — Gemini API failed, created new org as fallback

---

## Database indexes (idempotency enforcement)

The DB enforces uniqueness at the storage level, not just in code:

| Index | Collection | Purpose |
|---|---|---|
| `(normalized_name, dob)` UNIQUE | `athletes` | Prevents duplicate athletes on re-seed |
| `normalized_name` UNIQUE | `organisations` | Prevents two orgs with the same normalized name |
| `known_names.name` | `organisations` | Fast lookup for Layer 1 alias matching |
| `(athlete_id, org_id, relation_type)` UNIQUE | `athlete_organisation` | Prevents duplicate relationships |
| `timestamp` | `resolution_logs` | Fast pagination for the audit log API |

If a duplicate is attempted, a `DuplicateKeyError` is caught and counted as
"already existed" — no crash, no data corruption. This is what makes the seed
fully idempotent (safe to re-run).

---

## Entity kind inference

The `entity_kind` field on an org document is inferred from the relationship type,
not stored in the input JSON. Rules:

| Condition | entity_kind assigned |
|---|---|
| `is_person: true` in the link | `coach` |
| `relation_type = "training"` | `training` |
| `relation_type` is `brand`, `ambassador`, or `endorsement` | `brand` |
| anything else | `association` |

---

## Known edge cases and limitations

### 1. Org embeddings are never re-computed
When an org is first created, its embedding is calculated and stored. If you later
rename a canonical org's display name, the cached embedding becomes stale. Fix:
write a backfill script that re-calls `get_embedding(normalized_name)` for the
updated org and saves it.

### 2. Athlete dedup is name+DOB only
Org resolution uses three layers. Athlete resolution uses none — just normalized
name + DOB. If DOB is missing, two different people with the same name will collide.
A `_dedup_warning` flag is stored on the athlete document in this case.

### 3. No human review queue
Every ambiguous decision goes straight to the LLM and is auto-accepted. There is
no "hold for human review" step. If you want one, the natural hook is in
`pipeline.py` in the `ambiguous` branch — route those to a `pending_review`
collection instead of calling the LLM.

### 4. LLM failures silently create new orgs
If Groq is down, rate-limited, or the model name changes, the pipeline creates
a new org instead of merging. No crash, but duplicates may appear. Always check
`resolution_logs` for entries with `method: "llm"` and `decision: "new_org"` —
the `llm_reasoning` field will say whether it was a failure or a real LLM verdict.

### 5. The SEMANTIC_SIMILARITY embedding task type over-merges
If you switch back to `SEMANTIC_SIMILARITY`, short brand names (Nike, Adidas, Puma)
cluster together and will get false merges. Always use `RETRIEVAL_DOCUMENT` for
entity deduplication.

### 6. Extreme abbreviations score poorly in embeddings
The pipeline currently fails to merge `"sai"` and `"sports authority of india"`.
Because the strings look completely different, their embedding score is only `0.80`.
Since this is below our `0.82` floor, the pipeline treats them as different orgs
without ever asking the LLM (which would know they are the same).

**The trade-off:** We could lower the floor to `0.75` to catch this. But probing
shows that `"nike"` vs `"puma"` scores `0.81`. If we lower the floor to `0.75`,
SAI gets fixed, but Nike/Puma also gets sent to the LLM. The LLM will correctly
keep them separate, but you end up paying for many more LLM calls on obvious
negatives. For this project, we accept missing extreme abbreviations to save LLM cost.

### 7. Thresholds are data-dependent
The values `0.94` and `0.82` were calibrated against this specific dataset and
embedding model. If you change the model or use very different data, re-probe
the scores and recalibrate. Print cosine similarity for known true-positive pairs
(Nike/Nike India) and true-negative pairs (Nike/Adidas) to set the right boundaries.

### 7. Normalization migration needed after logic changes
If you ever change `normalize_org_name`, all existing `normalized_name` fields in
the `organisations` collection become stale. Run
`python -m scripts.migrate_normalized_names` to backfill them.

---

## API endpoints

| Method | Path | What it does |
|---|---|---|
| POST | `/athletes/seed` | Bulk ingest an array of athletes |
| POST | `/athletes` | Add a single athlete incrementally |
| GET | `/athletes` | List all athletes |
| GET | `/athletes/{id}` | Single athlete + all their org relationships joined in |
| GET | `/organisations` | All canonical orgs with known-name aliases |
| GET | `/resolution-logs?limit=50&skip=0` | Paginated audit trail |

---

## Configuration (`.env` file)

| Variable | Default | Purpose |
|---|---|---|
| `MONGO_URI` | `mongodb://localhost:27017` | MongoDB connection string |
| `MONGO_DB_NAME` | `valory` | Database name |
| `GEMINI_API_KEY` | — | Required. Get from https://aistudio.google.com/apikey |
| `GEMINI_EMBEDDING_MODEL` | `gemini-embedding-001` | Which embedding model to use |
| `GROQ_API_KEY` | — | Required. Get from https://console.groq.com/keys |
| `GROQ_MODEL` | `groq/compound-mini` | Which Groq model — verify it exists on your account |
| `EMBEDDING_AUTO_MERGE_THRESHOLD` | `0.94` | Score above this = auto-merge (no LLM call) |
| `EMBEDDING_AMBIGUOUS_FLOOR` | `0.82` | Score below this = new org (no LLM call) |
