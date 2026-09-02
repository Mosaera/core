"""The read-only backlog audit — which EXISTING items intake would question.

The launch gate already refuses an item with an open clarification (ADR-0080 §1). But the detectors
run at decompose and re-curate time, so an item written before they existed carries no ask and
therefore no lock: it launches with acceptance criteria nothing can check, and the engine burns a
run discovering that.

These use the shape of a real legacy backlog — items written by a person for a person, before any
of this existed — not text engineered to trip a detector.
"""

from __future__ import annotations

from mosaera_core.backlog_audit import audit_backlog, render_audit

# A plausible legacy backlog. Only the last two are genuinely checkable.
LEGACY = [
    {
        "id": 1,
        "title": "Make the dashboard faster",
        "acceptance": "It should feel snappy.",
        "status": "todo",
    },
    {
        "id": 2,
        "title": "Improve error handling",
        "acceptance": "Errors are handled properly.",
        "status": "todo",
    },
    {"id": 3, "title": "Add CSV export", "acceptance": "", "status": "todo"},
    {
        "id": 4,
        "title": "Rate limit the API",
        "acceptance": "`POST /api/login` returns 429 after 5 failed attempts from one IP "
        "within 60 seconds, and 200 again after the window passes.",
        "status": "todo",
    },
    {
        "id": 5,
        "title": "Fix the off-by-one in pagination",
        "acceptance": "`page(2, per_page=10)` returns items 11-20 inclusive; `page(1)` returns "
        "items 1-10.",
        "status": "done",
    },
]


def test_the_vague_legacy_items_are_flagged_and_the_checkable_ones_are_not() -> None:
    report = audit_backlog(LEGACY)
    flagged = {r.item_id for r in report.rows}
    assert 1 in flagged and 2 in flagged, "vague acceptance must be caught"
    assert 4 not in flagged and 5 not in flagged, (
        "an item whose acceptance binds a real check must NOT be flagged — over-firing here locks "
        "an operator's real work, which is the failure mode this tool must not have"
    )


def test_an_item_with_no_acceptance_at_all_is_flagged() -> None:
    """The commonest legacy shape: a title, and nothing else."""
    assert 3 in {r.item_id for r in audit_backlog(LEGACY).rows}


def test_an_item_that_already_has_an_open_question_is_not_counted_as_a_new_find() -> None:
    """The launch gate already refuses it today, so locking it changes nothing. Counting it as a
    new find would inflate the number the operator uses to decide whether this is worth doing."""
    report = audit_backlog(LEGACY, open_asks={1: {"claim_text": "already asked"}})
    row = next(r for r in report.rows if r.item_id == 1)
    assert row.already_asked is True
    assert row.would_lock is False
    assert 1 not in {r.item_id for r in report.would_lock}
    assert 1 in {r.item_id for r in report.already_locked}


def test_every_flagged_row_carries_the_evidence_for_it() -> None:
    """A bare id and a verdict is a nag. An operator deciding whether to repair an item needs the
    claim that cannot be bound and why — which is also what the repair itself needs."""
    for row in audit_backlog(LEGACY).rows:
        assert row.title, row
        assert row.axis in ("checkability", "decidability"), row
        assert row.claim_text or row.why, f"#{row.item_id} flagged with no evidence"


def test_the_audit_changes_nothing() -> None:
    """Read-only is the whole design: the first thing pointed at a real backlog must not be able
    to lock it. Asserted structurally — the module exposes no write path and the input is not
    mutated."""
    import mosaera_core.backlog_audit as mod

    before = [dict(i) for i in LEGACY]
    audit_backlog(LEGACY)
    assert LEGACY == before, "the audit mutated its input"
    writers = [n for n in dir(mod) if n.startswith(("set_", "lock_", "save_", "update_", "write_"))]
    assert not writers, f"the audit module exposes a write path: {writers}"


def test_the_report_states_the_denominator() -> None:
    """ "9 flagged" and "9 of 400 flagged" are different situations. A sweep that lists only
    problems gives no sense of proportion."""
    text = render_audit(audit_backlog(LEGACY), total_items=len(LEGACY))
    assert "5 item(s) examined" in text
    assert "Nothing was changed" in text


def test_a_clean_backlog_says_so_plainly() -> None:
    clean = [i for i in LEGACY if i["id"] in (4, 5)]
    report = audit_backlog(clean)
    assert report.rows == ()
    assert "Nothing flagged" in render_audit(report, total_items=len(clean))


# --- The CLI's failure surface ------------------------------------------------------------------
#
# Found by running it against a real server: a wrong password answered with ~80 lines of SQLAlchemy
# traceback. An operator tool that cannot explain its own failure satisfies ADR-0035
# ("infrastructure failure is loud") in the letter and misses it in the spirit — loud is not
# the same as clear.


def test_the_reason_names_the_root_cause_not_the_wrapper() -> None:
    from mosaera_core.backlog_audit_cli import _why

    root = OSError('connection failed: FATAL:  password authentication failed for user "mosaera"')
    wrapper = RuntimeError("(psycopg.OperationalError) ... https://sqlalche.me/e/20/e3q8")
    wrapper.__cause__ = root

    why = _why(wrapper)
    assert "password authentication failed" in why
    assert "sqlalche.me" not in why, "the docs link is not information"
    assert why.startswith("OSError"), "names the driver's error, not the ORM wrapper"


def test_the_per_address_retry_log_is_dropped() -> None:
    """psycopg restates one failure once per resolved address (127.0.0.1, then ::1). The first
    clause is the answer; the rest pushes it off the operator's screen."""
    from mosaera_core.backlog_audit_cli import _why

    noisy = OSError(
        'connection failed: FATAL:  password authentication failed for user "mosaera" '
        "Multiple connection attempts failed. All failures were: - host: 'localhost', "
        "port: 5432, hostaddr: '::1': connection failed: ..."
    )
    why = _why(noisy)
    assert "password authentication failed" in why
    assert "Multiple connection attempts" not in why
    assert len(why) < 200


def test_the_reason_is_a_single_line() -> None:
    """A multi-line reason wrecks a terminal report that is meant to be scanned."""
    from mosaera_core.backlog_audit_cli import _why

    assert "\n" not in _why(OSError("connection\n  refused\n\n  on port 5432"))


def test_the_cli_honors_dot_env_like_every_other_entrypoint(tmp_path, monkeypatch, capsys) -> None:
    """`Settings.from_env()` reads `os.environ` and does NOT load `.env` itself — every entrypoint
    calls `load_env()` explicitly (`mosaera-api`, the `mosaera` CLI, `scripts/db_migrate.py`).

    This CLI forgot to, and reported an operator's configured database as "No database configured"
    ONE COMMAND after `make db-migrate` succeeded against the very same `.env`. Found on the first
    real run against a live server.
    """
    from mosaera_core.backlog_audit_cli import main

    (tmp_path / ".env").write_text(
        "MOSAERA_DB_URL=postgresql://u:p@127.0.0.1:15999/nope\n", encoding="utf-8"
    )
    monkeypatch.delenv("MOSAERA_DB_URL", raising=False)
    monkeypatch.chdir(tmp_path)

    rc = main([])
    out = capsys.readouterr().out
    assert "No database configured" not in out, "the .env was ignored"
    # It got as far as TRYING to connect, which is the proof the URL was read.
    assert "could not read the database" in out
    assert rc == 1
