from app.resolution.normalize import normalize_org_name, normalize_athlete_name


def test_strips_legal_suffixes():
    assert normalize_org_name("Nike India") == "nike"
    assert normalize_org_name("Nike Sports Pvt Ltd") == "nike"
    assert normalize_org_name("NIKE") == "nike"


def test_handles_punctuation_and_case():
    assert normalize_org_name("Gopichand's Academy!") == "gopichand s academy"


def test_fallback_when_stopwords_empty_the_string():
    # "India Sports Group" is entirely stopwords -> falls back rather than
    # returning an empty string
    result = normalize_org_name("India Sports Group")
    assert result != ""


def test_athlete_name_normalization():
    assert normalize_athlete_name("P.V. Sindhu") == "pv sindhu"
    assert normalize_athlete_name("  Neeraj   Chopra ") == "neeraj chopra"
