from grading import grade_letter


def test_top_score_is_a() -> None:
    assert grade_letter(95) == "A"


def test_failing_score_is_f() -> None:
    assert grade_letter(50) == "F"
