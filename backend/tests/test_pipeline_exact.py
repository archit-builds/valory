from app.resolution.pipeline import resolve_organisation


def test_first_time_org_is_created_without_calling_embedding(db, monkeypatch):
    """A brand-new org with nothing in the DB yet should still work even if
    the embedding call is unavailable — new_org path just skips the cache."""
    def boom(*args, **kwargs):
        raise RuntimeError("Gemini API not available in this test")

    monkeypatch.setattr("app.resolution.pipeline.get_embedding", boom)

    org_id, info = resolve_organisation(db, "Nike", entity_kind_hint="brand")

    assert info["decision"] == "new_org"
    org = db.organisations.find_one({"_id": org_id})
    assert org["canonical_name"] == "Nike"
    assert org["normalized_name"] == "nike"


def test_exact_normalized_match_short_circuits_before_embedding(db, monkeypatch):
    """'Nike India' normalizes to the same string as 'Nike' -> Layer 1
    exact match should resolve this WITHOUT ever calling the embedding API."""
    monkeypatch.setattr("app.resolution.pipeline.get_embedding", lambda *a, **k: [1.0])

    org_id_1, info_1 = resolve_organisation(db, "Nike", entity_kind_hint="brand")
    assert info_1["decision"] == "new_org"

    def boom(*args, **kwargs):
        raise AssertionError("embedding API should NOT be called for an exact match")

    monkeypatch.setattr("app.resolution.pipeline.find_best_embedding_match", boom)

    org_id_2, info_2 = resolve_organisation(db, "Nike India", entity_kind_hint="brand")

    assert info_2["method"] == "exact"
    assert info_2["decision"] == "merged"
    assert org_id_2 == org_id_1
    assert db.organisations.count_documents({}) == 1
