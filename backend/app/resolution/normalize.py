import re
import unicodedata


def normalize_org_name(raw_name: str) -> str:
    """
    Deterministic, identity-preserving normalization for organisation names.

    Steps (in order):
      1. Unicode-normalize (NFKD) and strip combining diacritics.
      2. Lowercase.
      3. Replace '&' with 'and'.
      4. Remove punctuation — replace with a space so adjacent words don't merge
         (e.g. "Pvt. Ltd." → "Pvt  Ltd " → "pvt ltd", not "pvtltd").
      5. Collapse multiple spaces and trim.

    Intentionally does NOT remove any words. Normalization is only responsible
    for making the same string compare equal to itself in different surface
    forms (case, accents, punctuation). Semantic deduplication is handled by
    Layer 2 (embeddings) and Layer 3 (LLM).

    Examples:
      "Boxing Federation of India"   → "boxing federation of india"
      "NIKE India"                   → "nike india"
      "JSW Sports Pvt. Ltd."         → "jsw sports pvt ltd"
      "  Boxing   Federation  "      → "boxing federation"
      "Café & Sport"                 → "cafe and sport"
    """
    if not raw_name:
        return ""

    # 1. Unicode NFKD → strip combining characters (accents/diacritics)
    name = unicodedata.normalize("NFKD", raw_name)
    name = "".join(ch for ch in name if not unicodedata.combining(ch))

    # 2. Lowercase
    name = name.lower()

    # 3. Replace ampersand with 'and'
    name = name.replace("&", "and")

    # 4. Replace any non-alphanumeric, non-space character with a space
    #    (handles dots, commas, hyphens, parentheses, etc.)
    name = re.sub(r"[^\w\s]", " ", name)

    # 5. Collapse whitespace and trim
    name = re.sub(r"\s+", " ", name).strip()

    return name


def normalize_athlete_name(raw_name: str) -> str:
    """Lowercase, strip periods/punctuation, collapse whitespace."""
    if not raw_name:
        return ""
    name = unicodedata.normalize("NFKD", raw_name)
    name = "".join(ch for ch in name if not unicodedata.combining(ch))
    name = name.lower().strip()
    name = re.sub(r"[^\w\s]", "", name)  # drop punctuation entirely for names
    return re.sub(r"\s+", " ", name).strip()
