"""
Layer 2 of the resolution pipeline: semantic similarity via Gemini embeddings.

Catches cases fuzzy/exact matching can't — abbreviations, semantic
equivalents (e.g. "SAI" vs "Sports Authority of India") — that share no
useful character overlap.

Org embeddings are cached on the org document itself (`embedding` field)
so we only call the Gemini API once per org, not on every lookup.
"""
import math
from typing import Optional

from google import genai
from google.genai import types
from pymongo.database import Database

from app.config import settings

_client: "genai.Client | None" = None


def _get_client() -> "genai.Client":
    global _client
    if _client is None:
        if not settings.GEMINI_API_KEY:
            raise RuntimeError(
                "GEMINI_API_KEY is not set. Add it to your .env file — "
                "see .env.example. Free key: https://aistudio.google.com/apikey"
            )
        _client = genai.Client(api_key=settings.GEMINI_API_KEY)
    return _client


def get_embedding(text: str) -> list[float]:
    """Calls the Gemini embedding API for a single string. Raises on failure
    so the caller (pipeline.py) can decide how to degrade gracefully."""
    client = _get_client()
    result = client.models.embed_content(
        model=settings.GEMINI_EMBEDDING_MODEL,
        contents=text,
        config=types.EmbedContentConfig(task_type="RETRIEVAL_DOCUMENT"),
    )
    return result.embeddings[0].values


def cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def find_best_embedding_match(
    db: Database, normalized_input: str
) -> tuple[Optional[dict], float]:
    """
    Compares the input name's embedding against every existing org's cached
    embedding. Returns (best_matching_org_doc_or_None, best_score).
    """
    input_embedding = get_embedding(normalized_input)

    best_org = None
    best_score = 0.0

    for org in db.organisations.find({"embedding": {"$exists": True}}):
        score = cosine_similarity(input_embedding, org["embedding"])
        if score > best_score:
            best_score = score
            best_org = org

    return best_org, best_score
