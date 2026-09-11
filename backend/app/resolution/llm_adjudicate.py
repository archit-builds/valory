"""
Layer 3 of the resolution pipeline: LLM adjudication for the ambiguous band
only (embedding similarity between EMBEDDING_AMBIGUOUS_FLOOR and
EMBEDDING_AUTO_MERGE_THRESHOLD). This is the only layer that costs an
external call beyond embeddings, so it should fire rarely.

Per project decision: auto-accept the LLM's verdict, no human review queue.
Every call and its reasoning is still logged by pipeline.py for audit.
"""
import json

from groq import Groq

from app.config import settings

_client: Groq | None = None


def _get_client() -> Groq:
    global _client
    if _client is None:
        if not settings.GROQ_API_KEY:
            raise RuntimeError(
                "GROQ_API_KEY is not set. Add it to your .env file — "
                "see .env.example. Free key: https://console.groq.com/keys"
            )
        _client = Groq(api_key=settings.GROQ_API_KEY)
    return _client


def adjudicate_same_org(existing_canonical_name: str, candidate_name: str) -> dict:
    """
    Returns {"same": bool, "reasoning": str}. Raises on API failure so the
    caller can decide the fallback behavior (pipeline.py defaults to
    new_org + logs the failure rather than guessing).
    """
    client = _get_client()

    prompt = (
        f'Organisation A: "{existing_canonical_name}"\n'
        f'Organisation B: "{candidate_name}"\n\n'
        "Are these the same real-world organisation, accounting for regional "
        "subsidiaries, abbreviations, and rebranding? "
        'Reply with strict JSON only, no markdown fences: '
        '{"same": true or false, "reasoning": "<one sentence>"}'
    )

    response = client.chat.completions.create(
        model=settings.GROQ_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
        max_tokens=150,
    )

    raw = response.choices[0].message.content.strip()
    raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()

    try:
        parsed = json.loads(raw)
        return {
            "same": bool(parsed.get("same", False)),
            "reasoning": str(parsed.get("reasoning", "")),
        }
    except (json.JSONDecodeError, AttributeError):
        # LLM didn't return valid JSON — treat as inconclusive, caller logs this
        return {"same": False, "reasoning": f"LLM response not parseable: {raw[:200]}"}
