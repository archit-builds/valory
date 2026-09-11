# Valory Athlete–Organisation Resolution Pipeline

Ingests athlete JSON and automatically resolves sponsor/training organisation
names against existing organisations, so `"Nike"` and `"Nike India"` become
one canonical org instead of duplicates — with every decision logged.

## Architecture

```
Layer 1 — Normalize + exact match      (free, instant)
Layer 2 — Gemini embedding similarity  (semantic — catches SAI vs
                                         "Sports Authority of India")
Layer 3 — Groq LLM adjudication        (ambiguous band only — auto-accepts
                                         the verdict, no human review queue)
```

Every org name lookup writes a `resolution_logs` entry recording which
layer resolved it, the score, and (for Layer 3) the LLM's reasoning.

Full design rationale: see `valory-pipeline-spec.md` in this folder if
included, or ask for it again — it documents every threshold, schema field,
and edge case this code implements.

## Prerequisites

- Python 3.11+
- A running MongoDB instance (local `mongod`, Docker, or Atlas free tier)
- Free Gemini API key: https://aistudio.google.com/apikey
- Free Groq API key: https://console.groq.com/keys

## Setup

```bash
cd backend
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# edit .env: set MONGO_URI, GEMINI_API_KEY, GROQ_API_KEY
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
and prints a summary plus the final resolved org list with their known-name
aliases. **Safe to re-run** — fully idempotent across all three collections.

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

No build step — just open the file:

```bash
open frontend/index.html     # macOS
# or just double-click it, or serve it with `python -m http.server` from /frontend
```

It defaults to `http://127.0.0.1:8000` as the API base (editable in the
top-right input if your backend runs elsewhere). Three tabs: Athletes,
Organisations (with their known-name aliases), and the Resolution Log
(shows which layer resolved each org name and why).

## Tuning

Thresholds live in `.env`:
- `EMBEDDING_AUTO_MERGE_THRESHOLD` (default 0.88) — cosine similarity above
  this auto-merges without hitting the LLM
- `EMBEDDING_AMBIGUOUS_FLOOR` (default 0.75) — below this, treated as a new
  org with no LLM call; between the floor and the auto-merge threshold,
  Layer 3 (LLM) decides

The stopword list used for normalization (`india`, `pvt`, `ltd`, etc.) is
in `app/config.py` — extend it if your real data has other regional/legal
suffixes.

## Known limitations / things to revisit with real data

- Org embeddings are cached on first creation (`organisations.embedding`
  field) and never recomputed — if you rename a canonical org's display
  name after creation, re-embed it manually or add a backfill script.
- No human review queue exists (per project decision — full auto-accept).
  If you later want one, the natural hook is the ambiguous band in Layer 2
  (`app/resolution/pipeline.py`, the `ambiguous` branch) — route those to a
  `pending_review` collection instead of calling the LLM.
- Athlete dedup falls back to name-only matching when DOB is missing, and
  flags this with a warning in the seed summary — worth eyeballing those
  warnings after a real run in case two different people share a name.
