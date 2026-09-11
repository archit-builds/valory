from app.ingestion import ingest_athletes
from app.models.schemas import AthleteInput


def _sample_athletes():
    return [
        AthleteInput(
            full_name="PV Sindhu",
            dob="1995-07-05",
            disciplines=["Badminton"],
            organisations=[
                {"org_name": "Nike", "relation_type": "brand", "label": "Brand Ambassador"},
                {"org_name": "Gopichand Academy", "relation_type": "training", "label": "Trains at"},
            ],
        ),
        AthleteInput(
            full_name="Neeraj Chopra",
            dob="1997-12-24",
            disciplines=["Javelin Throw"],
            organisations=[
                {"org_name": "Nike India", "relation_type": "brand", "label": "Sponsored Athlete"},
            ],
        ),
    ]


def test_ingestion_dedups_org_across_athletes(db, monkeypatch):
    monkeypatch.setattr("app.resolution.pipeline.get_embedding", lambda *a, **k: [1.0])

    summary = ingest_athletes(db, _sample_athletes())

    assert summary.athletes_created == 2
    assert db.organisations.count_documents({}) == 2  # Nike (merged with Nike India) + Gopichand Academy
    assert summary.orgs_merged == 1  # Nike India merged into Nike
    assert summary.orgs_created == 2  # Nike, Gopichand Academy


def test_reingesting_same_data_is_idempotent(db, monkeypatch):
    monkeypatch.setattr("app.resolution.pipeline.get_embedding", lambda *a, **k: [1.0])

    ingest_athletes(db, _sample_athletes())
    athlete_count_after_first = db.athletes.count_documents({})
    org_count_after_first = db.organisations.count_documents({})
    relationship_count_after_first = db.athlete_organisation.count_documents({})

    second_summary = ingest_athletes(db, _sample_athletes())

    assert db.athletes.count_documents({}) == athlete_count_after_first
    assert db.organisations.count_documents({}) == org_count_after_first
    assert db.athlete_organisation.count_documents({}) == relationship_count_after_first
    assert second_summary.athletes_matched_existing == 2
    assert second_summary.relationships_already_existed == 3


def test_missing_dob_still_ingests_with_warning(db, monkeypatch):
    monkeypatch.setattr("app.resolution.pipeline.get_embedding", lambda *a, **k: [1.0])

    athlete = AthleteInput(full_name="Some Athlete", organisations=[])
    summary = ingest_athletes(db, [athlete])

    assert summary.athletes_created == 1
    assert len(summary.warnings) == 1
    assert "no DOB provided" in summary.warnings[0]
