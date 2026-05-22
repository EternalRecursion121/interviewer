from stage1 import normalize_stage1, time_choice_to_budget_seconds


def test_normalize_empty_returns_none():
    assert normalize_stage1(None) is None
    assert normalize_stage1({}) is None
    assert normalize_stage1(
        {"value": "  ", "falling_short": "", "ideas": None, "involvement": "\n"}
    ) is None


def test_normalize_strips_and_keeps_present_fields():
    out = normalize_stage1(
        {
            "value": "  the people  ",
            "falling_short": "too much talk",
            "ideas": "",
            "involvement": None,
            "time_minutes": 20,
            "no_time_limit": False,
            "newsletter": {"email": "a@b.com", "frequency": "weekly", "interested_in": "  "},
        }
    )
    assert out == {
        "value": "the people",
        "falling_short": "too much talk",
        "ideas": None,
        "involvement": None,
        "time_minutes": 20,
        "no_time_limit": False,
        "newsletter": {"email": "a@b.com", "frequency": "weekly", "interested_in": None},
    }


def test_normalize_no_time_limit_alone_is_not_empty():
    out = normalize_stage1({"no_time_limit": True})
    assert out is not None
    assert out["no_time_limit"] is True
    assert out["time_minutes"] is None


def test_normalize_newsletter_without_email_is_dropped():
    out = normalize_stage1({"value": "x", "newsletter": {"email": "  ", "frequency": "weekly"}})
    assert out is not None
    assert out["newsletter"] is None


def test_normalize_bad_time_minutes_becomes_none():
    assert normalize_stage1({"value": "x", "time_minutes": "abc"})["time_minutes"] is None
    assert normalize_stage1({"value": "x", "time_minutes": -5})["time_minutes"] is None
    assert normalize_stage1({"value": "x", "time_minutes": 0})["time_minutes"] is None


def test_time_choice_to_budget_seconds():
    assert time_choice_to_budget_seconds(None) is None
    assert time_choice_to_budget_seconds({"time_minutes": None, "no_time_limit": True}) is None
    assert time_choice_to_budget_seconds({"time_minutes": None, "no_time_limit": False}) is None
    assert time_choice_to_budget_seconds({"time_minutes": 20, "no_time_limit": False}) == 1200
