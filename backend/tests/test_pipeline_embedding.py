from app.resolution.pipeline import resolve_organisation


def test_high_embedding_similarity_auto_merges(db, monkeypatch):
    """Simulates the 'SAI' vs 'Sports Authority of India' case: no exact or
    normalized overlap, but embeddings say they're semantically the same."""
    monkeypatch.setattr("app.resolution.pipeline.get_embedding", lambda *a, **k: [1.0])

    org_id_1, info_1 = resolve_organisation(
        db, "Sports Authority of India", entity_kind_hint="association"
    )
    assert info_1["decision"] == "new_org"

    existing_org = db.organisations.find_one({"_id": org_id_1})

    def fake_best_match(db_arg, normalized_input):
        return existing_org, 0.93  # above EMBEDDING_AUTO_MERGE_THRESHOLD (0.88)

    monkeypatch.setattr("app.resolution.pipeline.find_best_embedding_match", fake_best_match)

    org_id_2, info_2 = resolve_organisation(db, "SAI", entity_kind_hint="training")

    assert info_2["method"] == "embedding"
    assert info_2["decision"] == "merged"
    assert org_id_2 == org_id_1
    assert db.organisations.count_documents({}) == 1

    updated_org = db.organisations.find_one({"_id": org_id_1})
    known_names = [k["name"] for k in updated_org["known_names"]]
    assert "sai" in known_names


def test_low_embedding_similarity_creates_new_org(db, monkeypatch):
    monkeypatch.setattr("app.resolution.pipeline.get_embedding", lambda *a, **k: [1.0])

    org_id_1, _ = resolve_organisation(db, "Nike", entity_kind_hint="brand")
    existing_org = db.organisations.find_one({"_id": org_id_1})

    def fake_low_match(db_arg, normalized_input):
        return existing_org, 0.2  # well below ambiguous floor (0.75)

    monkeypatch.setattr("app.resolution.pipeline.find_best_embedding_match", fake_low_match)

    org_id_2, info_2 = resolve_organisation(db, "Adidas", entity_kind_hint="brand")

    assert info_2["decision"] == "new_org"
    assert org_id_2 != org_id_1
    assert db.organisations.count_documents({}) == 2
