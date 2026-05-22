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
        "open_questions": None,
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


from stage1 import render_breadth_map, format_stage1_for_notes, newsletter_payload


def test_render_breadth_map_empty():
    assert render_breadth_map(None) == ""
    assert render_breadth_map(
        {"value": None, "falling_short": None, "ideas": None,
         "involvement": None, "time_minutes": 30, "no_time_limit": False,
         "newsletter": None}
    ) == ""


def test_render_breadth_map_includes_only_present_fields():
    bm = render_breadth_map(
        {"value": "the people", "falling_short": None, "ideas": "a book club",
         "involvement": None, "time_minutes": None, "no_time_limit": False,
         "newsletter": {"email": "a@b.com", "frequency": None, "interested_in": None}}
    )
    assert bm.startswith("<stage1_breadth_map>")
    assert bm.rstrip().endswith("</stage1_breadth_map>")
    assert "the people" in bm
    assert "a book club" in bm
    assert "falling short" not in bm.lower()  # skipped field omitted
    assert "newsletter" in bm.lower()          # tells stage 2 not to re-ask it


def test_format_stage1_for_notes_plain_block():
    s = format_stage1_for_notes(
        {"value": "x", "falling_short": "y", "ideas": None,
         "involvement": "maybe events", "time_minutes": 20,
         "no_time_limit": False, "newsletter": {"email": "a@b.com",
         "frequency": "weekly", "interested_in": None}}
    )
    assert "# Stage 1 form" in s
    assert "x" in s and "y" in s and "maybe events" in s
    assert format_stage1_for_notes(None) == ""


def test_newsletter_payload():
    assert newsletter_payload(None) is None
    assert newsletter_payload({"newsletter": None}) is None
    assert newsletter_payload(
        {"newsletter": {"email": "a@b.com", "frequency": "weekly", "interested_in": None}}
    ) == {
        "email": "a@b.com",
        "frequency": "weekly",
        "interested_in": None,
        "source": "stage1_form",
    }


def test_normalize_open_questions_populated():
    out = normalize_stage1(
        {"open_questions": {
            "membership": "  vouching  ", "growth": "stay small",
            "roles": "a rotating crew", "action": "ship weekly"}}
    )
    assert out is not None
    assert out["open_questions"] == {
        "membership": "vouching", "growth": "stay small",
        "roles": "a rotating crew", "action": "ship weekly"}


def test_normalize_open_questions_partial():
    out = normalize_stage1(
        {"open_questions": {"membership": "vouching", "growth": "  ",
                            "roles": "", "action": None}}
    )
    assert out["open_questions"] == {
        "membership": "vouching", "growth": None, "roles": None, "action": None}


def test_normalize_open_questions_all_blank_is_none():
    out = normalize_stage1(
        {"value": "x", "open_questions": {"membership": " ", "growth": "", "roles": None}}
    )
    assert out["open_questions"] is None


def test_normalize_open_questions_non_dict_is_none():
    out = normalize_stage1({"value": "x", "open_questions": "not a dict"})
    assert out["open_questions"] is None
    # a non-dict open_questions with nothing else is still an empty payload
    assert normalize_stage1({"open_questions": "not a dict"}) is None


def test_normalize_open_questions_alone_is_not_empty():
    out = normalize_stage1({"open_questions": {"roles": "rotating committee"}})
    assert out is not None
    assert out["open_questions"] == {
        "membership": None, "growth": None,
        "roles": "rotating committee", "action": None}


def test_render_breadth_map_includes_open_questions():
    bm = render_breadth_map(
        {"value": "the people", "falling_short": None, "ideas": None,
         "involvement": None, "time_minutes": None, "no_time_limit": False,
         "newsletter": None,
         "open_questions": {"membership": None, "growth": None,
                            "roles": "a rotating committee", "action": None}}
    )
    assert "a rotating committee" in bm
    assert "roles" in bm.lower()
    assert "do NOT surface them cold" in bm


def test_render_breadth_map_open_questions_alone_still_renders():
    bm = render_breadth_map(
        {"value": None, "falling_short": None, "ideas": None,
         "involvement": None, "time_minutes": 20, "no_time_limit": False,
         "newsletter": None,
         "open_questions": {"membership": "vouching", "growth": None,
                            "roles": None, "action": None}}
    )
    assert bm.startswith("<stage1_breadth_map>")
    assert "vouching" in bm


def test_render_breadth_map_multiple_open_questions():
    bm = render_breadth_map(
        {"value": None, "falling_short": None, "ideas": None,
         "involvement": None, "time_minutes": None, "no_time_limit": False,
         "newsletter": None,
         "open_questions": {"membership": "invite by personal vouching",
                            "growth": None,
                            "roles": "a rotating stewardship crew",
                            "action": "ship one small thing every week"}}
    )
    # all three answered braindumps surface
    assert "invite by personal vouching" in bm
    assert "a rotating stewardship crew" in bm
    assert "ship one small thing every week" in bm
    # the shared instruction/header line appears exactly once
    assert bm.count("do NOT surface them cold") == 1
    # each answered question renders as its own indented line
    assert bm.count("\n  - ") == 3
    # rendered order follows the canonical OPEN_QUESTIONS order
    assert (bm.index("invite by personal vouching")
            < bm.index("a rotating stewardship crew")
            < bm.index("ship one small thing every week"))
