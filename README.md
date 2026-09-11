# Valory Athlete–Organisation Resolution Pipeline

Ingests athlete JSON and automatically resolves sponsor/training organisation
names against existing organisations, so `"Nike"` and `"Nike India"` become
one canonical org instead of duplicates — with every decision logged.

## Architecture

```
Layer 1 — Normalize + exact match      (free, instant)
Layer 2 — Gemini embedding similarity  (RETRIEVAL_DOCUMENT mode — catches
                                         near-duplicates like "Nike India" vs "Nike")
Layer 3 — Groq LLM adjudication        (ambiguous band only — auto-accepts
                                         the verdict, no human review queue)
```

Every org name lookup writes a `resolution_logs` entry recording which
layer resolved it, the score, and (for Layer 3) the LLM's reasoning.

For full design rationale, edge cases, and architecture decisions see
[`approach.md`](./approach.md) in this repo.

## Prerequisites

- Python 3.11+
- A MongoDB instance — local `mongod`, Docker, or [Atlas free tier](https://cloud.mongodb.com)
- Free Gemini API key: https://aistudio.google.com/apikey
- Free Groq API key: https://console.groq.com/keys

## Setup

```bash
cd backend
python -m venv venv

# Activate (Windows):
venv\Scripts\activate

# Activate (macOS/Linux):
source venv/bin/activate

pip install -r requirements.txt

copy .env.example .env    # Windows
# cp .env.example .env    # macOS/Linux

# Edit .env and set:
#   MONGO_URI         — your MongoDB connection string
#   GEMINI_API_KEY    — from https://aistudio.google.com/apikey
#   GROQ_API_KEY      — from https://console.groq.com/keys
```

## Run the tests (no real DB or API keys needed — uses mongomock + mocks)

```bash
cd backend
pytest tests/ -v
```

All 14 tests should pass. These validate the resolution logic itself
(exact/embedding/LLM branching, idempotency, athlete dedup) without hitting
any real network service.

## Seed the database (requires real Mongo + Gemini + Groq credentials)

```bash
cd backend
python -m app.seed.seed_runner
```

This loads `app/seed/athletes_seed.json` (20 athletes with deliberate
near-duplicate org names — Nike/Nike India, Yonex/Yonex Sports India,
Gopichand Academy/Gopichand Badminton Academy, SAI/Sports Authority of
India, a shared coach across 3 athletes, and several exact-duplicate orgs)
and prints live progress per athlete + a final summary with the resolved
org list. **Safe to re-run** — fully idempotent across all three collections.

## Run the API

```bash
cd backend
uvicorn app.main:app --reload --port 8000
```

Interactive API docs: http://127.0.0.1:8000/docs

Endpoints:
- `POST /athletes/seed` — bulk ingest (same as the seed script, via HTTP)
- `POST /athletes` — add one athlete incrementally after the initial seed
- `GET /athletes` — list all athletes
- `GET /athletes/{id}` — single athlete with resolved org relationships joined in
- `GET /organisations` — canonical org list with known-name aliases
- `GET /resolution-logs?limit=50&skip=0` — paginated audit trail

## Run the frontend

No build step needed. Serve it with Python's built-in server:

```bash
cd frontend
python -m http.server 3000
```

Then open: http://127.0.0.1:3000

Three tabs: Athletes, Organisations (with known-name aliases), and the
Resolution Log (shows which layer resolved each org name and why).

## Tuning

Thresholds live in `.env`:
- `EMBEDDING_AUTO_MERGE_THRESHOLD` (default `0.94`) — cosine similarity above
  this auto-merges without hitting the LLM
- `EMBEDDING_AMBIGUOUS_FLOOR` (default `0.82`) — below this, treated as a new
  org with no LLM call; between the floor and the auto-merge threshold,
  Layer 3 (LLM) decides

These values were calibrated against actual embedding scores from the seed
dataset using `RETRIEVAL_DOCUMENT` task mode. If you change the embedding
model, re-probe the scores and recalibrate. See `approach.md` for details.

## Normalization

Organisation names are normalized before matching: lowercase, strip diacritics,
replace `&` → `and`, remove punctuation, collapse whitespace. No words are
removed — normalization is identity-preserving. Semantic deduplication is
handled by embeddings (Layer 2) and the LLM (Layer 3), not by normalization.

If you change the normalization logic, backfill existing records:
```bash
cd backend
python -m scripts.migrate_normalized_names
```

## Known limitations / things to revisit with real data

- Org embeddings are cached on first creation (`organisations.embedding`
  field) and never recomputed — if you rename a canonical org's display
  name after creation, re-embed it manually or add a backfill script.
- No human review queue exists (per project decision — full auto-accept).
  If you later want one, the natural hook is the ambiguous band in Layer 2
  (`app/resolution/pipeline.py`, the `ambiguous` branch) — route those to a
  `pending_review` collection instead of calling the LLM.
- Athlete dedup falls back to name-only matching when DOB is missing, and
  flags the athlete document with `_dedup_warning` — worth checking those
  after a real run in case two different people share a name.
- The Groq model name (`GROQ_MODEL` in `.env`) can be deprecated without
  notice. If Layer 3 silently creates new orgs instead of merging, check
  `resolution_logs` for `method: "llm"` + `decision: "new_org"` entries —
  the `llm_reasoning` field will show the actual error.
