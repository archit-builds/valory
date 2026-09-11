from app.resolution.pipeline import resolve_organisation


def _seed_one_org(db, monkeypatch, name="Gopichand Academy"):
    monkeypatch.setattr("app.resolution.pipeline.get_embedding", lambda *a, **k: [1.0])
    org_id, _ = resolve_organisation(db, name, entity_kind_hint="training")
    return org_id, db.organisations.find_one({"_id": org_id})


def test_ambiguous_band_calls_llm_and_merges_on_yes(db, monkeypatch):
    org_id_1, existing_org = _seed_one_org(db, monkeypatch)

    monkeypatch.setattr(
        "app.resolution.pipeline.find_best_embedding_match",
        lambda db_arg, normalized_input: (existing_org, 0.80),  # ambiguous band
    )
    monkeypatch.setattr(
        "app.resolution.pipeline.adjudicate_same_org",
        lambda existing_name, candidate_name: {"same": True, "reasoning": "Same academy, shorthand name."},
    )

    org_id_2, info = resolve_organisation(db, "Gopichand Badminton Academy", entity_kind_hint="training")

    assert info["method"] == "llm"
    assert info["decision"] == "merged"
    assert org_id_2 == org_id_1
    assert db.organisations.count_documents({}) == 1

    log = db.resolution_logs.find_one({"input_org_name": "Gopichand Badminton Academy"})
    assert log["llm_reasoning"] == "Same academy, shorthand name."


def test_ambiguous_band_creates_new_org_on_llm_no(db, monkeypatch):
    org_id_1, existing_org = _seed_one_org(db, monkeypatch, name="Nike")

    monkeypatch.setattr(
        "app.resolution.pipeline.find_best_embedding_match",
        lambda db_arg, normalized_input: (existing_org, 0.78),  # ambiguous band
    )
    monkeypatch.setattr(
        "app.resolution.pipeline.adjudicate_same_org",
        lambda existing_name, candidate_name: {"same": False, "reasoning": "Different brands entirely."},
    )

    org_id_2, info = resolve_organisation(db, "Nikkei Holdings", entity_kind_hint="brand")

    assert info["method"] == "llm"
    assert info["decision"] == "new_org"
    assert org_id_2 != org_id_1
    assert db.organisations.count_documents({}) == 2


def test_llm_failure_defaults_to_new_org_and_logs_failure(db, monkeypatch):
    org_id_1, existing_org = _seed_one_org(db, monkeypatch, name="Nike")

    monkeypatch.setattr(
        "app.resolution.pipeline.find_best_embedding_match",
        lambda db_arg, normalized_input: (existing_org, 0.80),
    )

    def boom(existing_name, candidate_name):
        raise RuntimeError("Groq API unavailable")

    monkeypatch.setattr("app.resolution.pipeline.adjudicate_same_org", boom)

    org_id_2, info = resolve_organisation(db, "Nikelodeon Sports", entity_kind_hint="brand")

    assert info["decision"] == "new_org"
    assert "Groq API unavailable" in info["llm_reasoning"]
