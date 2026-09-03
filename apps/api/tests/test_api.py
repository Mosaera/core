"""Endpoint tests driven by a fake graph — no Ollama, Docker, or DB required.

The fake graph reproduces the real shape: it emits node updates and one
approval-gate interrupt, then finishes with an approved/denied final state
depending on the resumed decision.
"""

from __future__ import annotations

import json
import threading
import time
from typing import Any, TypedDict

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt
from mosaera_api.app import RunSubmit, create_app


class _State(TypedDict, total=False):
    task: str
    plan: str
    diff: str
    iteration: int
    tests_passed: bool | None
    review: str
    reviews: list[str]  # per-iteration reviewer outputs (deny-loop tests)
    findings: list[dict[str, Any]]
    feedback: list[str]
    # Gate-evidence signals a test can inject (dropped if undeclared — LangGraph filters input
    # to the state schema). The fake gate_node reads them with all-clear defaults.
    oracle_verified: bool
    validation_strength: str
    # Receipt signals (ADR-0078 capture tests): ride the gate interrupt payload like the
    # real gate_node's, so the runner's resilient stash can be exercised end-to-end.
    claims: list[dict[str, Any]]
    claim_dispositions: list[dict[str, Any]]
    oracle_vouched_by: str
    oracle_residual: str
    tests_mutation_caught: bool | None
    gate_decision: dict[str, Any]
    approved: bool
    report_path: str
    commit_sha: str


def _build_fake_graph(max_iterations: int = 3, checkpointer: Any = None) -> Any:
    """Minimal plan→gate→deliver graph that exercises the REAL gate policy:
    the gate runs parse_reviewer_verdict + evaluate_gate and interrupts with a
    gate_decision, mirroring the production gate_node. Signals default to
    all-clear so tests that don't care keep their legacy behavior."""
    from mosaera_agents.reviewer import parse_reviewer_verdict
    from mosaera_policies import evaluate_gate

    def plan_node(state: _State) -> dict[str, Any]:
        return {"plan": f"1. do: {state['task']}", "iteration": state.get("iteration", 0) + 1}

    def gate_node(state: _State) -> dict[str, Any]:
        iteration = state.get("iteration", 0)
        reviews = state.get("reviews") or []
        review = (
            reviews[min(iteration - 1, len(reviews) - 1)]
            if reviews
            else state.get("review", "VERDICT: APPROVE\nok")
        )
        gd = evaluate_gate(
            tests_passed=state.get("tests_passed", True),
            reviewer_verdict=parse_reviewer_verdict(review),
            findings_count=len(state.get("findings") or []),
            iteration=iteration,
            max_iterations=max_iterations,
            # Mirror the real gate node: the LanguagePack declares what a green run is worth
            # (ADR-0034). Default "suite" so all-clear tests keep their legacy behavior; a test
            # can pass validation_strength="shallow" to exercise the silence-parks-on-a-syntax-
            # check rule.
            validation_strength=str(state.get("validation_strength") or "suite"),
            # Mirror gate_node's oracle_verified (ADR-0044): default True (a run WITH an independent
            # oracle — the normal case) so all-clear tests deliver; a test can pass
            # oracle_verified=False to exercise the oracle_unverified park.
            oracle_verified=bool(state.get("oracle_verified", True)),
        )
        raw = interrupt(
            {
                "action": "deliver",
                "summary": "approve delivery?",
                "review": review,
                "tests_passed": state.get("tests_passed", True),
                # Non-empty by default so all-clear autonomous runs auto-approve; a
                # test can pass diff="" to exercise the empty-delivery park guard.
                "diff": state.get("diff", "--- a\n+++ b\n+change\n"),
                "gate_decision": gd.as_dict(),
                # Mirror the real gate payload's receipt fields (empty defaults keep
                # every legacy test byte-identical).
                "claims": state.get("claims") or [],
                "claim_dispositions": state.get("claim_dispositions") or [],
                "oracle_vouched_by": state.get("oracle_vouched_by", ""),
                "oracle_residual": state.get("oracle_residual", ""),
            }
        )
        approved = bool(raw.get("approve")) if isinstance(raw, dict) else False
        # Mirror the real gate node (ADR-0034): only a person answering THIS gate is a human
        # override. The runner stamps actor="autonomous" on its auto-approve, so an autonomous
        # silence-ship is no longer branded as a human decision.
        actor = str(raw.get("actor", "unknown")) if isinstance(raw, dict) else "unknown"
        gate_state = {
            **gd.as_dict(),
            "human_override": bool(approved and gd.reasons and actor == "human"),
        }
        out: dict[str, Any] = {"approved": approved, "gate_decision": gate_state}
        if not approved:
            fb = raw.get("feedback", "") if isinstance(raw, dict) else ""
            out["feedback"] = [*state.get("feedback", []), fb or "denied"]
        return out

    def route(state: _State) -> str:
        if state.get("approved") or state.get("iteration", 0) >= max_iterations:
            return "deliver"
        return "plan"

    def deliver_node(state: _State) -> dict[str, Any]:
        return {
            "report_path": "/tmp/report.md",  # noqa: S108 — fake path string, not a real temp file
            "commit_sha": "deadbeef" if state.get("approved") else "",
        }

    builder: StateGraph = StateGraph(_State)
    builder.add_node("plan", plan_node)
    builder.add_node("gate", gate_node)
    builder.add_node("deliver", deliver_node)
    builder.add_edge(START, "plan")
    builder.add_edge("plan", "gate")
    builder.add_conditional_edges("gate", route, {"deliver": "deliver", "plan": "plan"})
    builder.add_edge("deliver", END)
    return builder.compile(checkpointer=checkpointer or InMemorySaver())


def _fake_factory(req: RunSubmit, run_id: str) -> tuple[Any, dict[str, Any], dict[str, Any], None]:
    # max_iterations=1: a single deny finalizes (endpoint tests visit the gate
    # once per decision); loop behavior is exercised via _session tests.
    graph = _build_fake_graph(max_iterations=1)
    config = {"configurable": {"thread_id": run_id}}
    return graph, config, {"task": req.task}, None


def _build_fix_graph(tests_sequence: list[bool], max_iterations: int = 3) -> Any:
    """plan→implement→test→(fix→implement | gate)→deliver — mirrors the production
    test-fix loop with a fake coder. ``tests_sequence[iteration-1]`` drives each
    attempt's pass/fail so the self-heal + budget-park paths can be exercised."""
    from mosaera_agents.reviewer import parse_reviewer_verdict
    from mosaera_policies import evaluate_gate

    def plan_node(state: _State) -> dict[str, Any]:
        return {"plan": "p", "iteration": state.get("iteration", 0) + 1}

    def implement_node(state: _State) -> dict[str, Any]:
        return {}

    def test_node(state: _State) -> dict[str, Any]:
        i = state.get("iteration", 1)
        passed = tests_sequence[min(i - 1, len(tests_sequence) - 1)]
        return {"tests_passed": passed, "test_output": "" if passed else "boom"}

    def fix_node(state: _State) -> dict[str, Any]:
        # Mirrors production fix_node: shares the iteration budget.
        return {"iteration": state.get("iteration", 0) + 1}

    def route_after_test(state: _State) -> str:
        if state.get("tests_passed") is False and state.get("iteration", 0) < max_iterations:
            return "fix"
        return "gate"

    def gate_node(state: _State) -> dict[str, Any]:
        iteration = state.get("iteration", 0)
        gd = evaluate_gate(
            tests_passed=state.get("tests_passed", True),
            reviewer_verdict=parse_reviewer_verdict("VERDICT: APPROVE\nok"),
            findings_count=0,
            iteration=iteration,
            max_iterations=max_iterations,
            oracle_verified=bool(state.get("oracle_verified", True)),  # a run WITH an oracle
        )
        raw = interrupt(
            {
                "action": "deliver",
                "diff": state.get("diff", "+change\n"),
                "gate_decision": gd.as_dict(),
            }
        )
        approved = bool(raw.get("approve")) if isinstance(raw, dict) else False
        return {"approved": approved, "gate_decision": {**gd.as_dict()}}

    def route_after_gate(state: _State) -> str:
        if state.get("approved") or state.get("iteration", 0) >= max_iterations:
            return "deliver"
        return "plan"

    def deliver_node(state: _State) -> dict[str, Any]:
        return {"report_path": "/tmp/r.md", "commit_sha": "beef" if state.get("approved") else ""}  # noqa: S108

    b: StateGraph = StateGraph(_State)
    for name, fn in (
        ("plan", plan_node),
        ("implement", implement_node),
        ("test", test_node),
        ("fix", fix_node),
        ("gate", gate_node),
        ("deliver", deliver_node),
    ):
        b.add_node(name, fn)
    b.add_edge(START, "plan")
    b.add_edge("plan", "implement")
    b.add_edge("implement", "test")
    b.add_conditional_edges("test", route_after_test, {"fix": "fix", "gate": "gate"})
    b.add_edge("fix", "implement")
    b.add_conditional_edges("gate", route_after_gate, {"deliver": "deliver", "plan": "plan"})
    b.add_edge("deliver", END)
    return b.compile(checkpointer=InMemorySaver())


def _fix_session(run_id: str, tests_sequence: list[bool], max_iterations: int = 3) -> Any:
    from mosaera_api.runner import RunSession

    return RunSession(
        run_id,
        _build_fix_graph(tests_sequence, max_iterations=max_iterations),
        {"configurable": {"thread_id": run_id}},
        {"task": "x"},
        auto_approve=True,
    )


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(graph_factory=_fake_factory))


def _wait_for(client: TestClient, run_id: str, status: str, tries: int = 100) -> dict[str, Any]:
    for _ in range(tries):
        snap = client.get(f"/api/runs/{run_id}").json()
        if snap["status"] == status:
            return snap
        time.sleep(0.02)
    raise AssertionError(f"run did not reach {status}; last={snap}")


class _FakeMemory:
    """Duck-typed stand-in for MemoryStore's read methods (offline history tests)."""

    def list_runs(self, limit: int = 50) -> list[dict[str, Any]]:
        return [{"id": "r1", "task": "fix it", "status": "APPROVED", "created_at": "2026-07-03"}]

    def run_detail(self, run_id: str) -> dict[str, Any] | None:
        if run_id == "r1":
            return {"id": "r1", "task": "fix it", "decisions": [{"kind": "plan", "content": "1."}]}
        return None


class _FakeMemoryWithDiff:
    def __init__(self, source: str = "https://gitlab.rengifo.me/mosaera/core.git") -> None:
        self.source = source

    def get_project_api_token(self, pid: str) -> str | None:
        return None  # part of the store interface (ADR-0103); override to opt in

    def list_runs(self, limit: int = 50) -> list[dict[str, Any]]:
        return []

    def run_detail(self, run_id: str) -> dict[str, Any] | None:
        if run_id != "r1":
            return None
        return {
            "id": "r1",
            "task": "add doc",
            "status": "APPROVED",
            "commit_sha": "abc123",
            "source": self.source,
            "branch": "mosaera/r1",
            "tests_passed": True,
            "validation_status": "pass",
            "iterations": 1,
            "decisions": [{"kind": "summary", "content": "did it"}],
            "repo_changes": [
                {
                    "diff": "diff --git a/X.md b/X.md\n--- /dev/null\n+++ b/X.md\n@@ -0,0 +1 @@\n+hi\n",  # noqa: E501
                    "commit_sha": "abc123",
                }
            ],
            "test_results": [{"passed": True, "output": "1 passed"}],
            "approvals": [],
        }

    def add_approval(self, *a: Any, **k: Any) -> None: ...
    def add_audit_event(self, *a: Any, **k: Any) -> None: ...


def _client_with(mem: Any) -> TestClient:
    return TestClient(create_app(graph_factory=_fake_factory, memory=mem))  # type: ignore[arg-type]


def test_patch_and_files_download() -> None:
    c = _client_with(_FakeMemoryWithDiff())
    patch = c.get("/api/runs/r1/patch")
    assert patch.status_code == 200
    assert "attachment" in patch.headers["content-disposition"]
    assert "diff --git" in patch.text
    assert c.get("/api/runs/r1/files").json() == {"files": ["X.md"]}


class _FakeMemoryCancelled(_FakeMemoryWithDiff):
    """A cancelled run: the row exists, but `persist_run` never ran so there are no repo_changes."""

    def run_detail(self, run_id: str) -> dict[str, Any] | None:
        detail = super().run_detail(run_id)
        if detail is not None:
            detail = {**detail, "status": "CANCELLED", "commit_sha": None, "repo_changes": []}
        return detail


def _seed_workspace(root: Any, run_id: str) -> Any:
    """A committed clone with one uncommitted edit — a cancelled run's workspace on disk."""
    from git import Repo

    ws = root / "workspaces" / run_id
    ws.mkdir(parents=True)
    repo = Repo.init(ws)
    repo.config_writer().set_value("user", "email", "t@t").release()
    repo.config_writer().set_value("user", "name", "t").release()
    (ws / "kept.md").write_text("base\n", encoding="utf-8")
    repo.git.add("-A")
    repo.git.commit("-m", "base")
    (ws / "added.py").write_text("print('new')\n", encoding="utf-8")
    return ws


def test_patch_recovers_a_cancelled_runs_work_from_its_workspace(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """`repo_changes` is only written by deliver, so a cancelled run has no row — but its
    workspace is never cleaned. Without the fallback the product offered a download-patch
    control that could not work and claimed to keep work it did not surface."""
    monkeypatch.setenv("MOSAERA_HOME", str(tmp_path))
    ws = _seed_workspace(tmp_path, "r1")
    index_before = (ws / ".git" / "index").read_bytes()

    c = _client_with(_FakeMemoryCancelled())  # run row exists; repo_changes is empty
    patch = c.get("/api/runs/r1/patch")
    assert patch.status_code == 200
    assert "added.py" in patch.text and "diff --git" in patch.text
    # The listing routes through the same call, so it recovers too.
    assert c.get("/api/runs/r1/files").json() == {"files": ["added.py"]}
    # A GET must not stage the tree: the workspace's own index is byte-identical.
    assert (ws / ".git" / "index").read_bytes() == index_before


def test_patch_still_404s_when_the_workspace_is_gone(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """Recovery must not turn a genuinely absent workspace into a misleading empty patch."""
    monkeypatch.setenv("MOSAERA_HOME", str(tmp_path))
    (tmp_path / "workspaces").mkdir()
    assert _client_with(_FakeMemoryCancelled()).get("/api/runs/r1/patch").status_code == 404


def test_file_download_404_when_workspace_absent() -> None:
    # No .mosaera/workspaces/r1 in the test env → 404, not a 500 or path escape.
    assert _client_with(_FakeMemoryWithDiff()).get("/api/runs/r1/files/X.md").status_code == 404


def test_download_file_rejects_traversal_run_id(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    # ADR-0038: `%2e%2e` reaches the handler as run_id ".." (a literal ".." is collapsed
    # client-side; the encoded form is the live vector). Un-guarded, the containment root
    # would anchor at MOSAERA_HOME (workspaces_dir/..) and the path check would then PASS for
    # settings.json — streaming the unmasked PAT. The boundary guard must reject it 400.
    monkeypatch.setenv("MOSAERA_HOME", str(tmp_path))
    (tmp_path / "workspaces").mkdir()
    (tmp_path / "settings.json").write_text('{"gitlab_token": "glpat-SECRET"}', encoding="utf-8")
    r = _client_with(_FakeProjectMemory()).get("/api/runs/%2e%2e/files/settings.json")
    assert r.status_code == 400
    assert "glpat-SECRET" not in r.text  # the secret never leaves the box


def test_delete_run_rejects_traversal_run_id(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    # ADR-0038: DELETE /runs/%2e%2e would otherwise rmtree(workspaces_dir/..) == MOSAERA_HOME,
    # wiping settings.json (secrets) and every run. The boundary guard rejects it before rmtree.
    monkeypatch.setenv("MOSAERA_HOME", str(tmp_path))
    (tmp_path / "workspaces").mkdir()
    secrets = tmp_path / "settings.json"
    secrets.write_text('{"gitlab_token": "glpat-SECRET"}', encoding="utf-8")
    r = _client_with(_FakeProjectMemory()).delete("/api/runs/%2e%2e")
    assert r.status_code == 400
    assert secrets.exists()  # MOSAERA_HOME (and its secrets) survived intact


def test_project_file_routes_reject_traversal_project_id(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    # ADR-0038 parity/hardening: these project routes built their containment root FROM the raw
    # `project_id` — the same anti-pattern the run download had. Exploitability here was LIMITED
    # (the `/repo` suffix + a pre-existing is_relative_to check bounded a single-`..` id to a
    # 404, not a secret read), so this is defence-in-depth parity, not closing a live leak. All
    # four now validate the id at the boundary (contained_path / safe_segment) → clean 400.
    monkeypatch.setenv("MOSAERA_HOME", str(tmp_path))
    (tmp_path / "projects").mkdir()
    (tmp_path / "settings.json").write_text('{"gitlab_token": "glpat-SECRET"}', encoding="utf-8")
    c = _client_with(_FakeProjectMemory())
    for url in (
        "/api/projects/%2e%2e/files/settings.json",  # project_file (contained_path)
        "/api/projects/%2e%2e/files",  # project_files (_project_ws → safe_segment)
        "/api/projects/%2e%2e/patch",  # project_patch (_project_ws → safe_segment)
        "/api/projects/%2e%2e/diff",  # project_accumulated_diff (safe_segment) — finding A2
    ):
        r = c.get(url)
        assert r.status_code == 400, url
        assert "glpat-SECRET" not in r.text


def test_run_report_served_from_reports_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    monkeypatch.setenv("MOSAERA_HOME", str(tmp_path))
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "run-r1.md").write_text("# Run report\n\nAll good.", encoding="utf-8")
    c = TestClient(create_app(graph_factory=_fake_factory))
    body = c.get("/api/runs/r1/report").json()
    assert body == {"markdown": "# Run report\n\nAll good."}


def test_run_report_404_when_missing(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    monkeypatch.setenv("MOSAERA_HOME", str(tmp_path))
    c = TestClient(create_app(graph_factory=_fake_factory))
    r = c.get("/api/runs/never-ran/report")
    assert r.status_code == 404
    assert "no report recorded" in r.json()["detail"]


def test_config_reflects_gitlab_token(monkeypatch: pytest.MonkeyPatch) -> None:
    import mosaera_core

    monkeypatch.delenv("MOSAERA_GITLAB_TOKEN", raising=False)
    monkeypatch.delenv("MOSAERA_ADMIN_TOKEN", raising=False)
    assert TestClient(create_app(graph_factory=_fake_factory)).get("/api/config").json() == {
        # ADR-0055: /config carries the engine version so the UI self-identifies. Read the constant
        # (not a literal) so a version bump doesn't break this exact-shape assertion.
        "version": mosaera_core.__version__,
        # ADR-0088: the maturity channel rides alongside as a separate axis.
        "maturity": mosaera_core.__maturity__,
        "gitlab": False,
        "admin_required": False,
        "max_iterations_ceiling": 12,
    }


def test_openapi_version_tracks_the_engine_version() -> None:
    """ADR-0055: one source of truth.

    The FastAPI ``version=`` argument was a hand-maintained literal and sat at 0.1.0 through both
    the 0.5.0 and 0.6.0 releases, so `/docs` advertised a version the engine had not been for
    months. Reading the constant is the fix; this keeps a literal from creeping back.
    """
    import mosaera_core

    schema = TestClient(create_app(graph_factory=_fake_factory)).get("/openapi.json").json()
    assert schema["info"]["version"] == mosaera_core.__version__


def test_api_token_gate_enforced_when_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOSAERA_API_TOKEN", "s3cret")
    c = TestClient(create_app(graph_factory=_fake_factory))
    # Liveness stays open; the whole /api surface requires the bearer token.
    assert c.get("/healthz").status_code == 200
    assert c.get("/api/runs").status_code == 401
    assert c.get("/api/runs", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert c.get("/api/runs", headers={"Authorization": "Bearer s3cret"}).status_code == 200
    # Header-less transports (SSE, <img>) pass the token as a `?token=` query param.
    assert c.get("/api/runs?token=s3cret").status_code == 200
    assert c.get("/api/runs?token=wrong").status_code == 401


def test_api_open_when_no_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MOSAERA_API_TOKEN", raising=False)
    # Loopback default: no token configured → no gate (the bundled UI works).
    assert TestClient(create_app(graph_factory=_fake_factory)).get("/api/runs").status_code == 200


def test_create_app_enforces_bind_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    # The guard runs at construction too, so a --factory/gunicorn entrypoint that
    # skips main() can't skip it. Host comes from MOSAERA_API_HOST.
    monkeypatch.setenv("MOSAERA_API_HOST", "0.0.0.0")  # noqa: S104
    monkeypatch.delenv("MOSAERA_API_TOKEN", raising=False)
    monkeypatch.delenv("MOSAERA_SANDBOX", raising=False)  # → docker default
    monkeypatch.setenv(
        "MOSAERA_SECRET_KEY", Fernet.generate_key().decode()
    )  # #123/#124 satisfied — this test
    monkeypatch.setenv("MOSAERA_COOKIE_SECURE", "0")  # is about the factory bypass
    with pytest.raises(SystemExit):
        create_app(graph_factory=_fake_factory)  # public + no token → refuse
    monkeypatch.setenv("MOSAERA_API_TOKEN", "tok")
    create_app(graph_factory=_fake_factory)  # public + token + docker → builds
    monkeypatch.setenv("MOSAERA_SANDBOX", "subprocess")
    with pytest.raises(SystemExit):
        create_app(graph_factory=_fake_factory)  # public + subprocess → refuse


def test_cli_bind_host_closes_the_factory_bypass(monkeypatch: pytest.MonkeyPatch) -> None:
    # TM-0002 residual closed: `uvicorn app:create_app --factory --host 0.0.0.0` with NO
    # MOSAERA_API_HOST used to sail past the guard (it saw the 127.0.0.1 default) while binding
    # all interfaces. create_app now reads the real bind from the server's own --host/--bind argv.
    # `bind_guard`, not `app`: the guard and its bind-host helpers moved there when the
    # #123/#124 clauses took `app.py` past the 500-line ceiling (ADR-0126). Same functions.
    from mosaera_api.bind_guard import _cli_bind_host, _host_from_bind

    monkeypatch.delenv("MOSAERA_API_HOST", raising=False)
    monkeypatch.delenv("MOSAERA_API_TOKEN", raising=False)
    monkeypatch.delenv("MOSAERA_SANDBOX", raising=False)  # → docker default

    argv = ["uvicorn", "app:create_app", "--factory", "--host", "0.0.0.0"]  # noqa: S104
    monkeypatch.setattr("sys.argv", argv)
    assert _cli_bind_host() == "0.0.0.0"  # noqa: S104
    with pytest.raises(SystemExit):
        create_app(graph_factory=_fake_factory)  # real bind public + no token → refuse

    monkeypatch.setattr("sys.argv", ["gunicorn", "-b", "0.0.0.0:8000", "app:create_app()"])
    assert _cli_bind_host() == "0.0.0.0"  # noqa: S104
    with pytest.raises(SystemExit):
        create_app(graph_factory=_fake_factory)

    # UVICORN_HOST env (uvicorn auto-envvar) — the standard container pattern, no --host in argv.
    monkeypatch.setattr("sys.argv", ["uvicorn", "app:create_app", "--factory"])
    monkeypatch.setenv("UVICORN_HOST", "0.0.0.0")  # noqa: S104
    assert _cli_bind_host() == "0.0.0.0"  # noqa: S104
    with pytest.raises(SystemExit):
        create_app(graph_factory=_fake_factory)  # env-declared public bind + no token → refuse
    monkeypatch.delenv("UVICORN_HOST", raising=False)

    # A loopback --host must NOT mask a second, exposed -b: pick the most-exposed.
    monkeypatch.setattr(
        "sys.argv", ["gunicorn", "-b", "127.0.0.1:8000", "-b", "0.0.0.0:8001", "app:create_app()"]
    )
    assert _cli_bind_host() == "0.0.0.0"  # noqa: S104
    with pytest.raises(SystemExit):
        create_app(graph_factory=_fake_factory)

    # The official mosaera-api entrypoint binds programmatically (no server flag/env) → the
    # guard falls back to the loopback default and the app builds unchanged.
    monkeypatch.setattr("sys.argv", ["mosaera-api"])
    assert _cli_bind_host() is None
    create_app(graph_factory=_fake_factory)

    # A loopback-only --host stays loopback (not falsely refused).
    monkeypatch.setattr(
        "sys.argv", ["uvicorn", "app:create_app", "--factory", "--host", "127.0.0.1"]
    )
    assert _cli_bind_host() == "127.0.0.1"
    create_app(graph_factory=_fake_factory)  # loopback → builds

    # Host extraction from the various --host / --bind shapes.
    assert _host_from_bind("[::]:8000") == "::"
    assert _host_from_bind("unix:/run/m.sock") == "127.0.0.1"
    assert _host_from_bind("0.0.0.0:8000") == "0.0.0.0"  # noqa: S104


def test_project_token_write_is_localhost_gated(monkeypatch: pytest.MonkeyPatch) -> None:
    # A project GitLab PAT is a secret write → same localhost gate as /gitlab/config.
    # TestClient's peer isn't localhost, so the gate fires before any project lookup.
    monkeypatch.delenv("MOSAERA_ALLOW_REMOTE_CONFIG", raising=False)
    c = TestClient(create_app(graph_factory=_fake_factory))
    assert c.post("/api/projects/p1/token", json={"token": "glpat-x"}).status_code == 403
    # With the explicit override it passes the gate (then 400s — no store here).
    monkeypatch.setenv("MOSAERA_ALLOW_REMOTE_CONFIG", "1")
    assert c.post("/api/projects/p1/token", json={"token": "glpat-x"}).status_code == 400


def test_open_mr_requires_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MOSAERA_GITLAB_TOKEN", raising=False)
    r = _client_with(_FakeMemoryWithDiff()).post("/api/runs/r1/open-mr")
    assert r.status_code == 400 and "GitLab not configured" in r.json()["detail"]


def test_open_mr_rejects_non_gitlab_source(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOSAERA_GITLAB_TOKEN", "tok")
    r = _client_with(_FakeMemoryWithDiff("https://github.com/x/y.git")).post("/api/runs/r1/open-mr")
    assert r.status_code == 400 and "not on the configured GitLab" in r.json()["detail"]


def test_open_mr_409_when_workspace_gone(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOSAERA_GITLAB_TOKEN", "tok")
    r = _client_with(_FakeMemoryWithDiff()).post("/api/runs/r1/open-mr")
    assert r.status_code == 409  # gitlab source + commit, but no local workspace to push


def test_gitlab_status_unconfigured(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    monkeypatch.delenv("MOSAERA_GITLAB_TOKEN", raising=False)
    monkeypatch.setenv("MOSAERA_HOME", str(tmp_path))  # isolate from any real settings file
    c = TestClient(create_app(graph_factory=_fake_factory))
    assert c.get("/api/gitlab/status").json()["configured"] is False


def test_gitlab_config_localhost_guard(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    monkeypatch.delenv("MOSAERA_ALLOW_REMOTE_CONFIG", raising=False)
    monkeypatch.setenv("MOSAERA_HOME", str(tmp_path))
    c = TestClient(create_app(graph_factory=_fake_factory))
    # TestClient's host is not localhost → rejected without the override flag.
    assert c.post("/api/gitlab/config", json={"url": "https://gl", "token": "t"}).status_code == 403


def test_gitlab_config_writes_masked_never_echoes_token(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    monkeypatch.setenv("MOSAERA_ALLOW_REMOTE_CONFIG", "1")
    monkeypatch.setenv("MOSAERA_HOME", str(tmp_path))
    from mosaera_connectors import gitlab_client as glc

    monkeypatch.setattr(
        glc, "get_user", lambda *a: ({"username": "u", "name": "U", "is_admin": False}, None)
    )
    monkeypatch.setattr(
        glc, "get_token_info", lambda *a: ({"scopes": ["api"], "expires_at": None}, None)
    )

    c = TestClient(create_app(graph_factory=_fake_factory))
    resp = c.post(
        "/api/gitlab/config", json={"url": "https://gl.example", "token": "glpat-SECRET1234"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["configured"] is True and body["ok"] is True
    assert body["token_masked"] == "…1234"
    assert "glpat-SECRET1234" not in resp.text  # the raw token is never returned

    # Persisted to the settings file, and status still masks it.
    from mosaera_core.settings_store import read_settings

    assert read_settings(tmp_path)["gitlab_token"] == "glpat-SECRET1234"
    assert "glpat-SECRET1234" not in c.get("/api/gitlab/status").text


def test_gitlab_config_encrypts_global_token_at_rest(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    # ADR-0039: with MOSAERA_SECRET_KEY set, the GLOBAL PAT is stored ENCRYPTED (not just the
    # per-project token + provider keys), and from_env decrypts it back — so a stray settings.json
    # copy leaks no live push credential. Masked hint is still the real plaintext last-4.
    from cryptography.fernet import Fernet
    from mosaera_core.config import Settings
    from mosaera_core.settings_store import read_settings

    monkeypatch.setenv("MOSAERA_ALLOW_REMOTE_CONFIG", "1")
    monkeypatch.setenv("MOSAERA_HOME", str(tmp_path))
    monkeypatch.setenv("MOSAERA_SECRET_KEY", Fernet.generate_key().decode())
    from mosaera_connectors import gitlab_client as glc

    monkeypatch.setattr(
        glc, "get_user", lambda *a: ({"username": "u", "name": "U", "is_admin": False}, None)
    )
    monkeypatch.setattr(
        glc, "get_token_info", lambda *a: ({"scopes": ["api"], "expires_at": None}, None)
    )
    c = TestClient(create_app(graph_factory=_fake_factory))
    resp = c.post(
        "/api/gitlab/config", json={"url": "https://gl.example", "token": "glpat-SECRET1234"}
    )
    assert resp.status_code == 200
    stored = read_settings(tmp_path)["gitlab_token"]
    assert stored.startswith("enc:v1:") and "glpat-SECRET1234" not in stored  # encrypted at rest
    assert Settings.from_env().gitlab_token == "glpat-SECRET1234"  # from_env decrypts it back
    assert resp.json()["token_masked"] == "…1234"  # plaintext hint, not a ciphertext tail


def test_gitlab_resolve_non_gitlab_source(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    monkeypatch.setenv("MOSAERA_HOME", str(tmp_path))
    monkeypatch.setenv("MOSAERA_GITLAB_TOKEN", "tok")
    c = TestClient(create_app(graph_factory=_fake_factory))
    assert c.get("/api/gitlab/resolve", params={"source": "https://github.com/x/y.git"}).json() == {
        "gitlab": False
    }


class _FakeProjectMemory:
    def __init__(self) -> None:
        self.clauses: list[dict[str, Any]] = []
        self.projects: dict[str, dict[str, Any]] = {}
        self.items: dict[int, dict[str, Any]] = {}
        self.deleted_runs: list[str] = []
        self.cancelled_runs: list[str] = []
        self.messages: dict[str, list[dict[str, Any]]] = {}
        self.attachments: dict[str, dict[str, Any]] = {}
        self.message_links: dict[int, list[str]] = {}
        self.derivatives: dict[str, list[dict[str, Any]]] = {}
        self.context_items: dict[tuple[str, str, str], dict[str, Any]] = {}
        self.context_sources: dict[int, list[dict[str, Any]]] = {}
        self.approvals: list[tuple[str, str, bool, str]] = []
        self.audits: list[tuple[str, str, str]] = []
        self.diagnoses: dict[str, dict[str, Any]] = {}
        self.errored_runs: list[str] = []
        self.decisions: list[tuple[str, str, str]] = []
        self.run_claims: dict[str, list[dict[str, Any]]] = {}
        self._deps: dict[int, list[int]] = {}  # item_id -> depends_on ids
        self._next = 1

    def mark_run_error(self, run_id: str) -> None:
        self.errored_runs.append(run_id)

    def project_cost(self, project_id: str, since: Any = None) -> dict[str, Any]:
        # budget_status now always sums spend (capless projects report it too); this
        # fake has no metered runs, so it reports honest zeros.
        return {"usd": 0.0, "total_tokens": 0, "input_tokens": 0, "output_tokens": 0, "calls": 0}

    def add_decision(self, run_id: str, kind: str, content: str) -> None:
        self.decisions.append((run_id, kind, content))

    def add_run_claims(self, run_id: str, rows: list[dict[str, Any]]) -> None:
        self.run_claims.setdefault(run_id, []).extend(rows)

    def stamp_run_receipt(self, run_id: str, *, engine_version: str, receipt_id: str) -> None:
        self.receipt_stamps: dict[str, tuple[str, str]]
        if not hasattr(self, "receipt_stamps"):
            self.receipt_stamps = {}
        self.receipt_stamps.setdefault(run_id, (engine_version, receipt_id))

    def list_run_claims(self, run_id: str) -> list[dict[str, Any]]:
        return list(self.run_claims.get(run_id, []))

    def add_approval(self, run_id: str, action: str, approved: bool, feedback: str = "") -> None:
        self.approvals.append((run_id, action, approved, feedback))

    def add_audit_event(self, run_id: str, event: str, detail: str = "") -> None:
        self.audits.append((run_id, event, detail))

    def record_run_diagnosis(self, run_id: str, diagnosis: dict[str, Any]) -> None:
        self.diagnoses[run_id] = diagnosis

    # --- clauses (ADR-0082): the store surface `mosaera_core.clauses` needs ---
    def clause_insert(self, clause_id: str, **kw: Any) -> dict[str, Any]:
        row = {"id": clause_id, **kw}
        self.clauses = [
            c
            for c in self.clauses
            if (c["project_id"], c["standard_id"], c["binds"])
            != (kw["project_id"], kw["standard_id"], kw["binds"])
        ]
        self.clauses.append(row)
        return row

    def clause_list(
        self, project_id: str | None = None, *, include_superseded: bool = False
    ) -> list[dict[str, Any]]:
        return [c for c in self.clauses if c["project_id"] in (None, project_id)]

    def create_project(
        self,
        pid: str,
        name: str,
        source_repo: str,
        goal: str = "",
        gitlab_token: str = "",
        autonomous: bool = False,
    ) -> None:
        self.projects[pid] = {
            "id": pid,
            "name": name,
            "source_repo": source_repo,
            "goal": goal,
            "brief": "",
            "status": "draft",
            "branch": "",
            "autonomous": autonomous,
            "gitlab_token": gitlab_token,  # raw, server-side only (never surfaced)
            "error": "",
            "created_at": "t",
        }

    def project_detail(self, pid: str) -> dict[str, Any] | None:
        import copy

        p = self.projects.get(pid)
        if p is None:
            return None
        detail = copy.deepcopy(p)
        raw = detail.pop("gitlab_token", "")  # never leak the raw token
        api_raw = detail.pop("gitlab_api_token", "")
        detail["has_gitlab_token"] = bool(raw)
        detail["gitlab_token_masked"] = f"…{raw[-4:]}" if len(raw) > 4 else ("…" if raw else "")
        detail["has_gitlab_api_token"] = bool(api_raw)  # presence only (ADR-0103)
        detail["backlog"] = self.list_backlog_items(pid)
        detail["runs"] = []
        return detail

    def get_project_token(self, pid: str) -> str | None:
        p = self.projects.get(pid)
        return (p.get("gitlab_token") or None) if p else None

    def get_project_api_token(self, pid: str) -> str | None:
        p = self.projects.get(pid)
        return (p.get("gitlab_api_token") or None) if p else None

    def get_repo_overview(self, pid: str) -> str:
        p = self.projects.get(pid)
        return (p.get("repo_overview") or "") if p else ""

    def list_projects(self, limit: int = 100) -> list[dict[str, Any]]:
        return [self.project_detail(pid) for pid in self.projects]  # type: ignore[misc]

    def update_project(self, pid: str, **kw: Any) -> None:
        p = self.projects.get(pid)
        if p:
            p.update({k: v for k, v in kw.items() if v is not None})

    # backlog
    def add_backlog_item(
        self, pid: str, title: str, description: str = "", acceptance: str = "", position: int = 0
    ) -> int:
        iid = self._next
        self._next += 1
        self.items[iid] = {
            "id": iid,
            "project_id": pid,
            "title": title,
            "description": description,
            "acceptance": acceptance,
            "status": "todo",
            "position": position,
            "iteration": None,
            "locked": False,
            "lock_reason": "",
            "branch": "",
            "mr_url": "",
            "created_at": "t",
        }
        return iid

    def reorder_backlog(self, pid: str, ordered_ids: list[int]) -> None:
        ours = {i for i, v in self.items.items() if v["project_id"] == pid}
        if set(ordered_ids) != ours:
            raise ValueError("reorder must list exactly the project's item ids")
        for pos, iid in enumerate(ordered_ids):
            self.items[iid]["position"] = pos

    def set_item_lock(self, iid: int, locked: bool, reason: str = "") -> None:
        self.items[iid]["locked"] = bool(locked)
        self.items[iid]["lock_reason"] = reason if locked else ""

    def is_item_locked(self, iid: int) -> tuple[bool, str]:
        it = self.items.get(iid) or {}
        return (bool(it.get("locked")), str(it.get("lock_reason", "")))

    def set_item_clarification(
        self,
        iid: int,
        *,
        claim_text: str,
        why_unbindable: str,
        proposals: list[str],
        axis: str,
        proposal_kind: str,
    ) -> None:
        # mirrors the real store's validate-at-boundary contract, INCLUDING the required
        # discriminator (ADR-0091) — a fake that accepts what the store refuses is not a mirror
        props = [str(x).strip() for x in (proposals or []) if str(x).strip()][:3]
        if proposal_kind not in ("acceptance", "direction"):
            raise ValueError(f"clarification: unknown proposal_kind {proposal_kind!r}")
        if not str(claim_text).strip():
            raise ValueError("clarification: empty claim_text")
        if not props:
            raise ValueError("clarification: at least one proposal is required")
        it = self.items.get(iid)
        if it is None:
            raise ValueError(f"clarification: unknown item {iid}")
        it["clarification"] = {
            "claim_text": str(claim_text).strip(),
            "why_unbindable": str(why_unbindable).strip(),
            "proposals": props,
            "axis": str(axis),
            "proposal_kind": proposal_kind,
            "status": "open",
            "asked_at": "2026-08-03T00:00:00",
        }

    def resolve_item_clarification(
        self, iid: int, *, status: str = "resolved", resolution: str = ""
    ) -> None:
        # mirrors the real store: retain the exchange, never delete (#63 ledger)
        if status not in ("resolved", "dismissed", "affirmed"):
            raise ValueError(f"clarification: unknown status {status!r}")
        it = self.items.get(iid)
        if it is not None and isinstance(it.get("clarification"), dict):
            it["clarification"] = {
                **it["clarification"],
                "status": status,
                "resolution": resolution,
                "resolved_at": "2026-08-03T00:01:00",
            }

    def item_clarification(self, iid: int) -> dict | None:
        it = self.items.get(iid) or {}
        c = it.get("clarification")
        return dict(c) if isinstance(c, dict) and c.get("status") == "open" else None

    # Simplified structural ops — the real DAG rewiring is verified in test_store.py; here
    # they just need to mutate the in-memory board so the apply-endpoint dispatch is tested.
    def delete_backlog_item(self, iid: int) -> None:
        self.items.pop(iid, None)
        self._deps.pop(iid, None)

    def split_backlog_item(self, iid: int, parts: list[dict[str, str]]) -> list[int]:
        pid = self.items[iid]["project_id"]
        pos = self.items[iid]["position"]
        del self.items[iid]
        return [
            self.add_backlog_item(
                pid, p["title"], p.get("description", ""), p.get("acceptance", ""), pos
            )
            for p in parts
        ]

    def merge_backlog_items(
        self,
        target: int,
        sources: list[int],
        *,
        title: str | None = None,
        description: str | None = None,
        acceptance: str | None = None,
    ) -> None:
        for sid in sources:
            self.items.pop(sid, None)
            self._deps.pop(sid, None)
        if title is not None:
            self.items[target]["title"] = title
        if description is not None:
            self.items[target]["description"] = description
        if acceptance is not None:
            self.items[target]["acceptance"] = acceptance

    def _with_deps(self, item: dict[str, Any]) -> dict[str, Any]:
        deps = self._deps.get(item["id"], [])
        delivered = {"in_review", "done"}
        out = dict(item)
        out["depends_on"] = sorted(deps)
        out["blocked_by"] = sorted(
            d for d in deps if (self.items.get(d) or {}).get("status") not in delivered
        )
        # mirrors _backlog_summary: `clarification` is the OPEN ask only; the retained
        # exchange rides `clarification_record` regardless of status (#63 ledger)
        raw = item.get("clarification")
        out["clarification"] = (
            dict(raw) if isinstance(raw, dict) and raw.get("status") == "open" else None
        )
        out["clarification_record"] = dict(raw) if isinstance(raw, dict) else None
        return out

    def list_backlog_items(self, pid: str) -> list[dict[str, Any]]:
        return sorted(
            (self._with_deps(i) for i in self.items.values() if i["project_id"] == pid),
            key=lambda i: (i["position"], i["id"]),
        )

    def get_backlog_item(self, iid: int) -> dict[str, Any] | None:
        return self._with_deps(self.items[iid]) if iid in self.items else None

    def set_item_dependencies(self, iid: int, depends_on: list[int]) -> None:
        if iid in depends_on:
            raise ValueError("an item cannot depend on itself")
        self._deps[iid] = list(dict.fromkeys(depends_on))

    def blocking_dependencies(self, iid: int) -> list[int]:
        delivered = {"in_review", "done"}
        return sorted(
            d
            for d in self._deps.get(iid, [])
            if (self.items.get(d) or {}).get("status") not in delivered
        )

    def update_backlog_item(self, iid: int, **kw: Any) -> None:
        if iid in self.items:
            self.items[iid].update({k: v for k, v in kw.items() if v is not None})

    def clear_todo_backlog(self, pid: str) -> None:
        for iid in [
            i for i, it in self.items.items() if it["project_id"] == pid and it["status"] == "todo"
        ]:
            del self.items[iid]

    # --- charter + map (#42 MR3) ---

    charters: dict[str, dict[str, Any]]
    map_dims: dict[str, list[dict[str, Any]]]

    def get_charter(self, pid: str) -> dict[str, Any] | None:
        return getattr(self, "charters", {}).get(pid)

    def upsert_charter(self, pid: str, **kw: Any) -> dict[str, Any]:
        # Mirrors the real store: None means LEAVE THAT FIELD ALONE on update (defaults on create).
        if (p := kw.get("posture")) is not None and p not in {"free", "business", "regulated"}:
            raise ValueError(f"unknown posture {p!r}")
        if not hasattr(self, "charters"):
            self.charters: dict[str, dict[str, Any]] = {}
        prior = self.charters.get(pid) or {}
        keep = {"goal": "", "constraints": "", "posture": "business"}
        row: dict[str, Any] = {"project_id": pid}
        for f, dflt in keep.items():
            row[f] = kw[f] if kw.get(f) is not None else prior.get(f, dflt)
        self.charters[pid] = row
        return row

    def list_map_dimensions(self, pid: str) -> list[dict[str, Any]]:
        return list(getattr(self, "map_dims", {}).get(pid, []))

    def delete_project(self, pid: str) -> None:
        self.projects.pop(pid, None)
        for iid in [i for i, it in self.items.items() if it["project_id"] == pid]:
            del self.items[iid]

    def delete_run(self, run_id: str) -> None:
        self.deleted_runs.append(run_id)

    def cancel_run(self, run_id: str) -> None:
        self.cancelled_runs.append(run_id)

    def finalize_orphans(self) -> int:
        return 0

    def ensure_default_pm_session(self, pid: str) -> str:
        return f"sess-{pid}"

    def add_message(self, pid: str, role: str, content: str, session_id: str | None = None) -> int:
        self._next += 1
        sid = session_id or self.ensure_default_pm_session(pid)
        self.messages.setdefault(pid, []).append(
            {
                "id": self._next,
                "role": role,
                "content": content,
                "created_at": "t",
                "session_id": sid,
            }
        )
        return self._next

    def list_messages(self, pid: str, session_id: str | None = None) -> list[dict[str, Any]]:
        out = []
        for m in self.messages.get(pid, []):
            if session_id is not None and m.get("session_id") != session_id:
                continue
            atts = [
                {
                    "id": a,
                    "filename": self.attachments[a]["filename"],
                    "scope": self.attachments[a]["scope"],
                    "size_bytes": self.attachments[a].get("size_bytes", 0),
                    "mime_type": self.attachments[a].get("mime_type", "text/plain"),
                }
                for a in self.message_links.get(m["id"], [])
                if a in self.attachments
            ]
            out.append(
                {
                    "role": m["role"],
                    "content": m["content"],
                    "created_at": m["created_at"],
                    "attachments": atts,
                    "context_sources": [dict(s) for s in self.context_sources.get(m["id"], [])],
                }
            )
        return out

    # attachments
    def add_attachment(self, attachment_id: str, pid: str, **kw: Any) -> None:
        self.attachments[attachment_id] = {
            "id": attachment_id,
            "project_id": pid,
            "error_message": "",
            "deleted_at": None,
            "created_at": "t",
            **kw,
        }

    def get_attachment(self, attachment_id: str) -> dict[str, Any] | None:
        a = self.attachments.get(attachment_id)
        return dict(a) if a else None

    def list_attachments(self, pid: str, include_deleted: bool = False) -> list[dict[str, Any]]:
        return [
            dict(a)
            for a in self.attachments.values()
            if a["project_id"] == pid and (include_deleted or a["deleted_at"] is None)
        ]

    def find_attachment_by_hash(self, pid: str, sha256: str) -> dict[str, Any] | None:
        for a in self.attachments.values():
            if a["project_id"] == pid and a.get("sha256") == sha256 and a["deleted_at"] is None:
                return dict(a)
        return None

    def soft_delete_attachment(self, attachment_id: str) -> None:
        if attachment_id in self.attachments:
            self.attachments[attachment_id]["deleted_at"] = "t"

    def update_attachment(self, attachment_id: str, **fields: Any) -> None:
        allowed = {"status", "error_message", "token_estimate", "scope"}
        a = self.attachments.get(attachment_id)
        if a is not None:
            a.update({k: v for k, v in fields.items() if k in allowed})

    def replace_derivatives(self, attachment_id: str, derivatives: list[dict[str, Any]]) -> None:
        rows = []
        for d in derivatives:
            self._next += 1
            rows.append(
                {
                    "id": self._next,
                    "attachment_id": attachment_id,
                    "content": "",
                    "storage_path": "",
                    "token_count": 0,
                    "chunk_index": 0,
                    "model": "",
                    **d,
                }
            )
        self.derivatives[attachment_id] = rows

    def list_derivatives(self, attachment_id: str, kind: str | None = None) -> list[dict[str, Any]]:
        rows = self.derivatives.get(attachment_id, [])
        return [dict(r) for r in rows if kind is None or r["kind"] == kind]

    def upsert_project_context_item(
        self,
        project_id: str,
        source_id: str,
        *,
        title: str,
        summary: str,
        token_count: int,
        source_type: str = "attachment",
    ) -> None:
        key = (project_id, source_type, source_id)
        self.context_items[key] = {
            "project_id": project_id,
            "source_type": source_type,
            "source_id": source_id,
            "title": title,
            "summary": summary,
            "token_count": token_count,
            "priority": 0,
            "disabled": False,
        }

    def disable_project_context_item(
        self, project_id: str, source_id: str, source_type: str = "attachment"
    ) -> None:
        key = (project_id, source_type, source_id)
        if key in self.context_items:
            self.context_items[key]["disabled"] = True

    def list_project_context_items(self, project_id: str) -> list[dict[str, Any]]:
        return [
            dict(i)
            for i in self.context_items.values()
            if i["project_id"] == project_id and not i["disabled"]
        ]

    def link_message_attachments(self, message_id: int, attachment_ids: list[str]) -> None:
        self.message_links.setdefault(message_id, []).extend(attachment_ids)

    def add_message_context_sources(self, message_id: int, sources: list[dict[str, Any]]) -> None:
        self.context_sources[message_id] = [dict(s) for s in sources]

    def attachments_for_message(self, message_id: int) -> list[dict[str, Any]]:
        return [
            dict(self.attachments[a])
            for a in self.message_links.get(message_id, [])
            if a in self.attachments
        ]

    # no-ops used by RunSession when a real store is absent (approvals/audits
    # are recorded by the methods near __init__ so gate tests can assert them)
    def ensure_run(self, *a: Any, **k: Any) -> None: ...
    def tag_run(self, *a: Any, **k: Any) -> None: ...


def test_create_project_starts_intake(monkeypatch: pytest.MonkeyPatch) -> None:
    started: list[str] = []
    monkeypatch.setattr(
        "mosaera_api.routes.projects.start_intake", lambda mem, pid, *a: started.append(pid)
    )
    mem = _FakeProjectMemory()
    c = _client_with(mem)
    r = c.post(
        "/api/projects", json={"name": "My Proj", "source_repo": "https://gl/x.git", "goal": "g"}
    )
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "draft" and body["id"].startswith("proj-my-proj-")
    assert started == [body["id"]]  # background intake kicked off
    assert c.get("/api/projects").json()["projects"][0]["id"] == body["id"]
    assert c.get(f"/api/projects/{body['id']}").json()["name"] == "My Proj"
    assert c.get("/api/projects/nope").status_code == 404


def test_project_brief_and_approve(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("mosaera_api.routes.projects.start_intake", lambda *a, **k: None)
    mem = _FakeProjectMemory()
    c = _client_with(mem)
    pid = c.post("/api/projects", json={"name": "P", "source_repo": "s", "goal": "g"}).json()["id"]
    # Can't approve until the brief is ready.
    assert c.post(f"/api/projects/{pid}/approve").status_code == 409
    assert c.put(f"/api/projects/{pid}/brief", json={"brief": "## Goals\nx"}).json()["brief"] == (
        "## Goals\nx"
    )
    mem.update_project(pid, status="ready")
    assert c.post(f"/api/projects/{pid}/approve").json()["status"] == "active"


def test_projects_need_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MOSAERA_DB_URL", raising=False)
    c = TestClient(create_app(graph_factory=_fake_factory))
    assert c.post("/api/projects", json={"name": "P", "source_repo": "s"}).status_code == 400


def test_backlog_add_list_patch() -> None:
    mem = _FakeProjectMemory()
    mem.create_project("p1", "P", "src")
    c = _client_with(mem)
    r = c.post(
        "/api/projects/p1/backlog", json={"title": "do X", "description": "d", "acceptance": "a"}
    )
    assert r.status_code == 201 and r.json()["status"] == "todo"
    iid = r.json()["id"]
    assert [i["title"] for i in c.get("/api/projects/p1/backlog").json()["backlog"]] == ["do X"]
    patched = c.patch(f"/api/projects/p1/backlog/{iid}", json={"status": "done", "title": "do Y"})
    assert patched.json()["status"] == "done" and patched.json()["title"] == "do Y"
    assert c.post("/api/projects/nope/backlog", json={"title": "x"}).status_code == 404


def test_backlog_get_carries_checkability_and_claims() -> None:
    # ADR-0079/0080 Wave 3 stage 1: the backlog GET surfaces the per-item Checkability
    # verdict + derived claims (additive fields; pure derivation, no schema change).
    mem = _FakeProjectMemory()
    mem.create_project("p1", "P", "src")
    c = _client_with(mem)
    ok = c.post(
        "/api/projects/p1/backlog",
        json={"title": "search", "description": "", "acceptance": "prints every matching note"},
    ).json()["id"]
    vague = c.post(
        "/api/projects/p1/backlog",
        json={"title": "wiring", "description": "", "acceptance": "everything is wired up nicely"},
    ).json()["id"]
    rows = {i["id"]: i for i in c.get("/api/projects/p1/backlog").json()["backlog"]}
    assert rows[ok]["checkability"] == "CHECKABLE"
    assert rows[ok]["claims"][0]["oracle_kind"] == "acceptance_test"
    assert rows[ok]["claims"][0]["provenance"] == "ENTAILED"
    assert rows[vague]["checkability"] == "UNDER_SPECIFIED"
    # Decidability rides the same row on its own axis, and both items are decidable: neither
    # names an output scale it then leaves uncomposed.
    assert rows[ok]["decidability"] == "DECIDABLE"
    assert rows[vague]["decidability"] == "DECIDABLE"


def test_backlog_get_separates_bindable_from_decidable() -> None:
    # The dangerous cell, and the reason decidability is a sibling verdict rather than a
    # widening of checkability: this item BINDS (a test can assert on printed output) and is
    # still undecidable (nothing in the text says how the score is composed), so a green run
    # would prove only that some invented model was implemented consistently. Observed live —
    # the greenfield demo brief shipped 48 passing tests over exactly this shape.
    mem = _FakeProjectMemory()
    mem.create_project("p1", "P", "src")
    c = _client_with(mem)
    iid = c.post(
        "/api/projects/p1/backlog",
        json={
            "title": "strength",
            "description": "",
            "acceptance": "prints a strength score 0-4 for the password",
        },
    ).json()["id"]
    row = {i["id"]: i for i in c.get("/api/projects/p1/backlog").json()["backlog"]}[iid]
    assert row["checkability"] == "CHECKABLE"
    assert row["decidability"] == "UNDECIDABLE"


def test_compliance_diagnoses_settled_work_the_verdicts_cannot_see() -> None:
    # The backfill. checkability/decidability judge `todo` items only, so an item authored
    # before those checks existed and long since delivered has never been looked at by them.
    # The diagnosis is status-blind, derived at read, and stores nothing.
    mem = _FakeProjectMemory()
    mem.create_project("p1", "P", "src")
    old = mem.add_backlog_item("p1", "Scorer", "d", "prints a strength score 0-4", 0)
    good = mem.add_backlog_item(
        "p1", "Stock", "d", "raises ValueError when the quantity exceeds the stock on hand", 1
    )
    mem.update_backlog_item(old, status="done")
    mem.update_backlog_item(good, status="done")
    c = _client_with(mem)

    rows = {i["id"]: i for i in c.get("/api/projects/p1/backlog").json()["backlog"]}
    assert rows[old]["checkability"] is None  # settled: the run-path verdicts stay silent
    assert rows[old]["compliant"] is False  # the diagnosis still reaches it
    assert rows[good]["compliant"] is True

    report = c.get("/api/projects/p1/compliance").json()
    assert report["total"] == 2
    assert report["non_compliant"] == 1
    assert report["by_status"]["done"] == {"total": 2, "non_compliant": 1}
    flagged = next(r for r in report["items"] if r["id"] == old)
    assert flagged["status"] == "done"  # reported as it is, never rewritten to todo
    assert flagged["reasons"] == ["the text names a value it never states a rule for"]
    # The payload states what a flag does NOT mean — the over-claim this whole pass invites.
    assert "not a claim that the delivered code is wrong" in report["note"]


def test_a_statement_clause_does_not_decide_a_scoring_ambiguity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A clause settles the parameter it binds — and nothing else.

    The first cut hardcoded `structural.body_statements` at this site, so ANY ratified
    statement-count clause would have marked a SCORING ambiguity decided. No number settles "how
    is the score composed" (that is the greenfield failure), and marking it decided would hide the
    one case that most needs an operator. Now the parameter is derived from the item's own finding.
    """
    from mosaera_core.clauses import ratify_clause

    mem = _FakeProjectMemory()
    mem.create_project("p1", "P", "src")
    statements = mem.add_backlog_item(
        "p1",
        "Refactor",
        "d",
        "`checkout_total` should read as a short orchestrator (a handful of statements).",
        0,
    )
    scoring = mem.add_backlog_item("p1", "Scorer", "d", "prints a strength score 0-4", 1)
    ratify_clause(
        mem,
        standard_id="standards/house-style",
        binds="structural.body_statements",
        value_kind="number",
        value_num=5,
        project_id="p1",
        because="correctness over line count",
    )

    monkeypatch.setenv("MOSAERA_CLAUSES", "1")
    rows = {i["id"]: i for i in _client_with(mem).get("/api/projects/p1/backlog").json()["backlog"]}

    assert rows[statements]["decidability"] == "DECIDABLE"  # settled by the clause
    assert rows[statements]["decided_by"]
    assert rows[scoring]["decidability"] == "UNDECIDABLE"  # NOT settled — no number reaches it
    assert rows[scoring]["decided_by"] is None


def test_run_backlog_item_serializes_per_project() -> None:
    mem = _FakeProjectMemory()
    mem.create_project("p1", "P", "src")
    iid = mem.add_backlog_item("p1", "do X", "desc", "acc", 0)
    c = _client_with(mem)
    assert c.post(f"/api/projects/p1/backlog/{iid}/run").status_code == 201
    assert _status(mem, iid) == "in_progress"  # type: ignore[index]
    # A second run on the same project's clone is rejected while one is active.
    iid2 = mem.add_backlog_item("p1", "do Y", position=1)
    assert c.post(f"/api/projects/p1/backlog/{iid2}/run").status_code == 409


def test_run_backlog_item_blocked_by_dependency_returns_409_then_unblocks() -> None:
    mem = _FakeProjectMemory()
    mem.create_project("p1", "P", "src")
    a = mem.add_backlog_item("p1", "A foundation", position=0)
    b = mem.add_backlog_item("p1", "B dependent", position=1)
    mem.set_item_dependencies(b, [a])
    c = _client_with(mem)
    # B depends on A (still todo) → blocked → 409 with an honest reason.
    r = c.post(f"/api/projects/p1/backlog/{b}/run")
    assert r.status_code == 409 and "unfinished dependencies" in r.json()["detail"]
    # Deliver A (in_review) → B unblocks and runs.
    mem.update_backlog_item(a, status="in_review")
    assert c.post(f"/api/projects/p1/backlog/{b}/run").status_code == 201


def test_set_item_dependencies_endpoint_sets_and_validates() -> None:
    mem = _FakeProjectMemory()
    mem.create_project("p1", "P", "src")
    a = mem.add_backlog_item("p1", "A", position=0)
    b = mem.add_backlog_item("p1", "B", position=1)
    c = _client_with(mem)
    r = c.put(f"/api/projects/p1/backlog/{b}/dependencies", json={"depends_on": [a]})
    assert r.status_code == 200
    assert r.json()["depends_on"] == [a] and r.json()["blocked_by"] == [a]
    # A self-dependency is rejected (400); an unknown item is 404.
    assert (
        c.put(f"/api/projects/p1/backlog/{a}/dependencies", json={"depends_on": [a]}).status_code
        == 400
    )
    assert (
        c.put("/api/projects/p1/backlog/999/dependencies", json={"depends_on": []}).status_code
        == 404
    )


def test_soft_lock_gates_run_and_override_bypasses() -> None:
    mem = _FakeProjectMemory()
    mem.create_project("p1", "P", "src")
    iid = mem.add_backlog_item("p1", "risky", position=0)
    c = _client_with(mem)
    r = c.put(
        f"/api/projects/p1/backlog/{iid}/lock",
        json={"locked": True, "reason": "wait for the schema item"},
    )
    assert r.status_code == 200 and r.json()["locked"] is True
    # A normal run is refused (409) and surfaces the caveat.
    r = c.post(f"/api/projects/p1/backlog/{iid}/run")
    assert r.status_code == 409 and "wait for the schema item" in r.json()["detail"]
    # The user's override runs it anyway (per-run bypass).
    assert c.post(f"/api/projects/p1/backlog/{iid}/run", json={"override": True}).status_code == 201


def test_reorder_backlog_endpoint() -> None:
    mem = _FakeProjectMemory()
    mem.create_project("p1", "P", "src")
    a = mem.add_backlog_item("p1", "A", position=0)
    b = mem.add_backlog_item("p1", "B", position=1)
    c = _client_with(mem)
    r = c.put("/api/projects/p1/backlog/reorder", json={"ordered_ids": [b, a]})
    assert r.status_code == 200
    assert [i["id"] for i in r.json()["backlog"]] == [b, a]
    # An incomplete set is rejected.
    assert c.put("/api/projects/p1/backlog/reorder", json={"ordered_ids": [a]}).status_code == 400


def test_changeset_normalises_a_list_acceptance_on_every_write_path() -> None:
    """A list-shaped acceptance is joined, never stored as a Python repr — add/enhance/split/merge.

    ``memory`` is a dependency-free leaf and cannot import the normaliser, so the changeset
    applier is the boundary that owns this for the store.
    """
    mem = _FakeProjectMemory()
    mem.create_project("p1", "P", "src")
    a = mem.add_backlog_item("p1", "A", position=0)
    b = mem.add_backlog_item("p1", "B", position=1)
    c = _client_with(mem)
    two = ["first is done", "second is done"]
    r = c.post(
        "/api/projects/p1/backlog/curate/apply",
        json={
            "changeset": [
                {"op": "enhance", "id": a, "acceptance": two},
                {"op": "add", "title": "New", "acceptance": two},
            ]
        },
    )
    assert r.status_code == 200
    for item in r.json()["backlog"]:
        assert "['" not in item["acceptance"]
        if item["acceptance"]:
            assert item["acceptance"] == "first is done\nsecond is done"

    # split carries acceptance on each PART, which is a separate code path from the op itself.
    r = c.post(
        "/api/projects/p1/backlog/curate/apply",
        json={
            "changeset": [{"op": "split", "id": b, "parts": [{"title": "B1", "acceptance": two}]}]
        },
    )
    assert r.status_code == 200
    assert all("['" not in i["acceptance"] for i in r.json()["backlog"])


def test_changeset_rejects_an_acceptance_that_is_neither_string_nor_list() -> None:
    """The validator is where a malformed op dies; coercing here would store its repr."""
    mem = _FakeProjectMemory()
    mem.create_project("p1", "P", "src")
    a = mem.add_backlog_item("p1", "A", position=0)
    c = _client_with(mem)
    r = c.post(
        "/api/projects/p1/backlog/curate/apply",
        json={"changeset": [{"op": "enhance", "id": a, "acceptance": {"criteria": ["x"]}}]},
    )
    assert r.status_code == 400


def test_apply_changeset_endpoint_applies_and_validates() -> None:
    mem = _FakeProjectMemory()
    mem.create_project("p1", "P", "src")
    a = mem.add_backlog_item("p1", "A", position=0)
    b = mem.add_backlog_item("p1", "B", position=1)
    c = _client_with(mem)
    changeset = [
        {"op": "reorder", "ordered_ids": [b, a]},
        {"op": "lock", "id": a, "reason": "wait for B"},
        {"op": "enhance", "id": b, "title": "B improved"},
    ]
    r = c.post("/api/projects/p1/backlog/curate/apply", json={"changeset": changeset})
    assert r.status_code == 200
    items = {i["id"]: i for i in r.json()["backlog"]}
    assert [i["id"] for i in r.json()["backlog"]] == [b, a]  # reordered
    assert items[a]["locked"] is True and items[a]["lock_reason"] == "wait for B"
    assert items[b]["title"] == "B improved"
    # An op referencing an unknown item rejects the WHOLE set (400).
    bad = c.post(
        "/api/projects/p1/backlog/curate/apply",
        json={"changeset": [{"op": "lock", "id": 999, "reason": "x"}]},
    )
    assert bad.status_code == 400
    # ...including an unknown id in a set_dependencies TARGET list. That field was unvalidated:
    # the store rejects it, but at APPLY time, and each op is its own transaction — so the raise
    # landed after earlier ops were already written, leaving the changeset partly applied.
    partial = c.post(
        "/api/projects/p1/backlog/curate/apply",
        json={
            "changeset": [
                {"op": "enhance", "id": a, "title": "should not be written"},
                {"op": "set_dependencies", "id": a, "depends_on": [999]},
            ]
        },
    )
    assert partial.status_code == 400
    after = {i["id"]: i for i in c.get("/api/projects/p1").json()["backlog"]}
    assert after[a]["title"] != "should not be written"  # nothing was written


def test_apply_changeset_add_op_appends_after_reorder() -> None:
    # The unified changeset (Quincy-in-chat) carries `add` ops too; new items
    # append at the end, so a same-changeset reorder still sees the pre-add ids.
    mem = _FakeProjectMemory()
    mem.create_project("p1", "P", "src")
    a = mem.add_backlog_item("p1", "A", position=0)
    b = mem.add_backlog_item("p1", "B", position=1)
    c = _client_with(mem)
    changeset = [
        {"op": "reorder", "ordered_ids": [b, a], "why": "b first"},
        {"op": "add", "title": "C", "description": "new", "why": "needed"},
    ]
    r = c.post("/api/projects/p1/backlog/curate/apply", json={"changeset": changeset})
    assert r.status_code == 200
    board = r.json()["backlog"]
    assert [i["title"] for i in board] == ["B", "A", "C"]  # reorder held, add appended last
    # An add with a blank title rejects the whole set (400).
    bad = c.post(
        "/api/projects/p1/backlog/curate/apply",
        json={"changeset": [{"op": "add", "title": "  ", "why": "x"}]},
    )
    assert bad.status_code == 400


def test_apply_changeset_structural_ops_and_no_mixing() -> None:
    mem = _FakeProjectMemory()
    mem.create_project("p1", "P", "src")
    a = mem.add_backlog_item("p1", "big auth", position=0)
    b = mem.add_backlog_item("p1", "dup setup A", position=1)
    d = mem.add_backlog_item("p1", "obsolete", position=2)
    cc = mem.add_backlog_item("p1", "dup setup B", position=3)
    c = _client_with(mem)
    changeset = [
        {"op": "split", "id": a, "parts": [{"title": "login"}, {"title": "logout"}], "why": "x"},
        {"op": "merge", "target": b, "sources": [cc], "title": "setup", "why": "dupes"},
        {"op": "delete", "id": d, "why": "obsolete"},
    ]
    r = c.post("/api/projects/p1/backlog/curate/apply", json={"changeset": changeset})
    assert r.status_code == 200
    titles = {i["title"] for i in r.json()["backlog"]}
    assert {"login", "logout"} <= titles  # split children
    assert "setup" in titles and "dup setup B" not in titles  # merge (source gone, target retitled)
    assert "obsolete" not in titles  # delete
    # Mixing a structural op with reorder is rejected (stale id snapshot).
    mixed = [
        {"op": "delete", "id": b, "why": "x"},
        {"op": "reorder", "ordered_ids": [b], "why": "y"},
    ]
    assert (
        c.post("/api/projects/p1/backlog/curate/apply", json={"changeset": mixed}).status_code
        == 400
    )


def test_approve_triggers_decompose_when_backlog_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[str] = []
    monkeypatch.setattr("mosaera_api.routes.projects.start_intake", lambda *a, **k: None)
    monkeypatch.setattr(
        "mosaera_api.routes.projects.start_decompose", lambda mem, pid: called.append(pid)
    )
    mem = _FakeProjectMemory()
    c = _client_with(mem)
    pid = c.post("/api/projects", json={"name": "P", "source_repo": "s", "goal": "g"}).json()["id"]
    mem.update_project(pid, status="ready")
    c.post(f"/api/projects/{pid}/approve")
    assert called == [pid]


def test_project_diff_404_when_no_clone() -> None:
    mem = _FakeProjectMemory()
    mem.create_project("p1", "P", "src")
    assert _client_with(mem).get("/api/projects/p1/diff").status_code == 404


def test_project_diff_includes_numstat_stats(monkeypatch: pytest.MonkeyPatch) -> None:
    import mosaera_api.routes.projects as appmod

    monkeypatch.setattr(appmod, "open_project_workspace", lambda *a: object())
    monkeypatch.setattr(
        appmod, "project_diff", lambda ws: ("main", "diff --git a/N.md b/N.md\n+x\n")
    )
    monkeypatch.setattr(
        appmod,
        "project_diff_stats",
        lambda ws: [{"path": "N.md", "additions": 1, "deletions": 0}],
    )
    mem = _FakeProjectMemory()
    mem.create_project("p1", "P", "src")
    body = _client_with(mem).get("/api/projects/p1/diff").json()
    assert body["base"] == "main" and body["has_changes"] is True
    assert body["stats"] == [{"path": "N.md", "additions": 1, "deletions": 0}]


def test_project_diff_stats_failure_degrades_to_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    import mosaera_api.routes.projects as appmod

    monkeypatch.setattr(appmod, "open_project_workspace", lambda *a: object())
    monkeypatch.setattr(appmod, "project_diff", lambda ws: ("main", ""))
    monkeypatch.setattr(
        appmod, "project_diff_stats", lambda ws: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    mem = _FakeProjectMemory()
    mem.create_project("p1", "P", "src")
    body = _client_with(mem).get("/api/projects/p1/diff").json()
    assert body["stats"] == [] and body["has_changes"] is False


def test_merge_requires_gitlab(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    monkeypatch.delenv("MOSAERA_GITLAB_TOKEN", raising=False)
    monkeypatch.setenv("MOSAERA_HOME", str(tmp_path))
    mem = _FakeProjectMemory()
    mem.create_project("p1", "P", "https://gitlab.rengifo.me/mosaera/core.git")
    assert _client_with(mem).post("/api/projects/p1/merge").status_code == 400


def test_merge_rejects_non_gitlab_source(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    monkeypatch.setenv("MOSAERA_GITLAB_TOKEN", "tok")
    monkeypatch.setenv("MOSAERA_HOME", str(tmp_path))
    mem = _FakeProjectMemory()
    mem.create_project("p1", "P", "https://github.com/x/y.git")
    r = _client_with(mem).post("/api/projects/p1/merge")
    # ADR-0112/0114: still refused, still 400 — but a GitHub source is now told what is
    # actually missing instead of being sent to re-check a URL that was correct. With no App
    # configured on this instance, the honest answer is the instance-level gap.
    assert r.status_code == 400 and "no GitHub App configured" in r.json()["detail"]

    unknown = _FakeProjectMemory()
    unknown.create_project("p2", "P", "https://elsewhere.example/x/y.git")
    r2 = _client_with(unknown).post("/api/projects/p2/merge")
    assert r2.status_code == 400 and "not on the configured GitLab" in r2.json()["detail"]


class _MrWS:
    root = "x"
    branch = "mosaera/project-p1"


class _MrResult:
    opened = True
    url = "https://gitlab.rengifo.me/mosaera/core/-/merge_requests/1"
    error = ""


def _patch_delivery_open(monkeypatch: pytest.MonkeyPatch, captured: dict[str, Any]) -> None:
    """The MR-opening logic now lives in mosaera_api.delivery (ADR-0019, shared by the endpoint
    and the autonomous sweep); patch the connector THERE, not on the routes module."""
    import mosaera_api.delivery as dmod

    monkeypatch.setattr(dmod, "open_project_workspace", lambda *a: _MrWS())
    monkeypatch.setattr(dmod, "project_diff", lambda ws: ("main", "diff --git a/N b/N\n+x\n"))

    def fake_open_mr(_root: Any, _plan: Any, **k: Any) -> Any:
        captured.update(k)
        return _MrResult()

    monkeypatch.setattr(dmod, "open_merge_request", fake_open_mr)


def test_merge_happy_path_sets_in_review(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    monkeypatch.setenv("MOSAERA_GITLAB_TOKEN", "tok")
    monkeypatch.setenv("MOSAERA_HOME", str(tmp_path))
    captured: dict[str, Any] = {}
    _patch_delivery_open(monkeypatch, captured)

    mem = _FakeProjectMemory()
    mem.create_project(
        "p1", "P", "https://gitlab.rengifo.me/mosaera/core.git", gitlab_token="proj-tok"
    )
    r = _client_with(mem).post("/api/projects/p1/merge")
    assert r.status_code == 200 and r.json()["url"].endswith("/merge_requests/1")
    assert mem.projects["p1"]["status"] == "in_review"
    assert captured["token"] == "proj-tok"  # the project's own scoped token, not a global one


def test_merge_needs_project_token(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    monkeypatch.setenv("MOSAERA_HOME", str(tmp_path))
    mem = _FakeProjectMemory()
    mem.create_project("p1", "P", "https://gitlab.rengifo.me/mosaera/core.git")  # no token
    r = _client_with(mem).post("/api/projects/p1/merge")
    assert r.status_code == 400 and "no GitLab token" in r.json()["detail"]


# --- Autonomous MR last-mile (ADR-0019) ---------------------------------------
_GL = "https://gitlab.rengifo.me/mosaera/core.git"


def test_open_project_mr_uses_scoped_token(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    monkeypatch.setenv("MOSAERA_HOME", str(tmp_path))
    from mosaera_api.delivery import open_project_mr
    from mosaera_core.config import Settings

    captured: dict[str, Any] = {}
    _patch_delivery_open(monkeypatch, captured)
    mem = _FakeProjectMemory()
    mem.create_project("p1", "P", _GL, gitlab_token="proj-tok")
    out = open_project_mr(mem, Settings.from_env(), "p1")  # type: ignore[arg-type]
    assert out.opened and (out.url or "").endswith("/merge_requests/1")
    assert captured["token"] == "proj-tok"  # scoped, never a global token
    assert mem.projects["p1"]["status"] == "in_review"


def test_open_project_mr_skip_reasons(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    monkeypatch.setenv("MOSAERA_HOME", str(tmp_path))
    import mosaera_api.delivery as dmod
    from mosaera_api.delivery import open_project_mr
    from mosaera_core.config import Settings

    s = Settings.from_env()
    non_gl = _FakeProjectMemory()
    non_gl.create_project("g", "G", "https://github.com/x/y.git", gitlab_token="t")
    # ADR-0112 splits this skip by detected provider; ADR-0114 splits the GitHub half again
    # by remedy. No App configured here → the instance-level reason. All still refuse.
    assert open_project_mr(non_gl, s, "g").skip == "github_app_unconfigured"  # type: ignore[arg-type]

    unknown_host = _FakeProjectMemory()
    unknown_host.create_project("u", "U", "https://elsewhere.example/x/y.git", gitlab_token="t")
    assert open_project_mr(unknown_host, s, "u").skip == "not_gitlab"  # type: ignore[arg-type]

    no_tok = _FakeProjectMemory()
    no_tok.create_project("n", "N", _GL)  # no token
    assert open_project_mr(no_tok, s, "n").skip == "no_token"  # type: ignore[arg-type]

    monkeypatch.setattr(dmod, "open_project_workspace", lambda *a: _MrWS())
    monkeypatch.setattr(dmod, "project_diff", lambda ws: ("main", "   "))  # empty
    empty = _FakeProjectMemory()
    empty.create_project("e", "E", _GL, gitlab_token="t")
    assert open_project_mr(empty, s, "e").skip == "empty_diff"  # type: ignore[arg-type]


def test_open_project_mr_honest_on_connector_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    monkeypatch.setenv("MOSAERA_HOME", str(tmp_path))
    import mosaera_api.delivery as dmod
    from mosaera_api.delivery import open_project_mr
    from mosaera_core.config import Settings

    class _Fail:
        opened = False
        url = ""
        error = "push rejected"

    monkeypatch.setattr(dmod, "open_project_workspace", lambda *a: _MrWS())
    monkeypatch.setattr(dmod, "project_diff", lambda ws: ("main", "diff\n+x\n"))
    monkeypatch.setattr(dmod, "open_merge_request", lambda *a, **k: _Fail())
    mem = _FakeProjectMemory()
    mem.create_project("p", "P", _GL, gitlab_token="t")
    out = open_project_mr(mem, Settings.from_env(), "p")  # type: ignore[arg-type]
    assert not out.opened and out.error == "push rejected" and out.skip is None


def _delivered_project(mem: Any, pid: str = "p1") -> dict[str, Any]:
    mem.create_project(pid, "P", _GL, gitlab_token="t", autonomous=True)
    a = mem.add_backlog_item(pid, "a")
    b = mem.add_backlog_item(pid, "b")
    mem.update_backlog_item(a, status="in_review")
    mem.update_backlog_item(b, status="done")
    detail = mem.project_detail(pid)
    assert detail is not None
    return detail


def _spy_opener(monkeypatch: pytest.MonkeyPatch, calls: list[str], *, opened: bool = True) -> None:
    from mosaera_api.delivery import MrOutcome

    def spy(mem: Any, settings: Any, pid: str) -> Any:
        calls.append(pid)
        return MrOutcome(True, url="u") if opened else MrOutcome(False, error="boom")

    monkeypatch.setattr("mosaera_api.app_context._delivery.open_project_mr", spy)


def test_sweep_opens_mr_when_backlog_complete(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    monkeypatch.setenv("MOSAERA_HOME", str(tmp_path))
    monkeypatch.setenv("MOSAERA_AUTO_OPEN_MR", "1")
    monkeypatch.setenv("MOSAERA_MR_GRANULARITY", "project")  # the whole-project opener
    from mosaera_api.routes.context import AppContext

    calls: list[str] = []
    _spy_opener(monkeypatch, calls)
    mem = _FakeProjectMemory()
    detail = _delivered_project(mem)
    AppContext(memory=mem)._maybe_open_project_mr("p1", detail)  # type: ignore[arg-type]
    assert calls == ["p1"]  # fired exactly once on a fully-delivered backlog


def test_sweep_no_mr_when_knob_off(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    monkeypatch.setenv("MOSAERA_HOME", str(tmp_path))
    monkeypatch.delenv("MOSAERA_AUTO_OPEN_MR", raising=False)  # default OFF
    from mosaera_api.routes.context import AppContext

    calls: list[str] = []
    _spy_opener(monkeypatch, calls)
    mem = _FakeProjectMemory()
    detail = _delivered_project(mem)
    AppContext(memory=mem)._maybe_open_project_mr("p1", detail)  # type: ignore[arg-type]
    assert calls == []  # opt-in OFF → never opens


def test_sweep_no_mr_when_incomplete_or_already_open(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    monkeypatch.setenv("MOSAERA_HOME", str(tmp_path))
    monkeypatch.setenv("MOSAERA_AUTO_OPEN_MR", "1")
    monkeypatch.setenv("MOSAERA_MR_GRANULARITY", "project")  # exercise the project opener's guards
    from mosaera_api.routes.context import AppContext

    calls: list[str] = []
    _spy_opener(monkeypatch, calls)
    ctx = AppContext(memory=_FakeProjectMemory())  # type: ignore[arg-type]

    # A backlog with an undelivered item is stuck, not complete → no MR.
    m1 = _FakeProjectMemory()
    m1.create_project("p1", "P", _GL, gitlab_token="t", autonomous=True)
    d1 = m1.add_backlog_item("p1", "a")
    m1.add_backlog_item("p1", "b")  # stays todo
    m1.update_backlog_item(d1, status="in_review")
    ctx._maybe_open_project_mr("p1", m1.project_detail("p1"))  # type: ignore[arg-type]

    # A complete backlog whose MR is already open → idempotent skip.
    m2 = _FakeProjectMemory()
    detail = _delivered_project(m2, "p2")
    detail["mr_url"] = "https://gitlab.rengifo.me/mosaera/core/-/merge_requests/9"
    ctx._maybe_open_project_mr("p2", detail)

    assert calls == []


def test_sweep_mr_failure_records_note_and_does_not_break(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    monkeypatch.setenv("MOSAERA_HOME", str(tmp_path))
    monkeypatch.setenv("MOSAERA_AUTO_OPEN_MR", "1")
    monkeypatch.setenv("MOSAERA_MR_GRANULARITY", "project")  # the whole-project opener
    from mosaera_api.routes.context import AppContext

    calls: list[str] = []
    _spy_opener(monkeypatch, calls, opened=False)  # connector fails
    mem = _FakeProjectMemory()
    detail = _delivered_project(mem)
    AppContext(memory=mem)._maybe_open_project_mr("p1", detail)  # type: ignore[arg-type]
    assert calls == ["p1"]
    assert "MR open failed" in mem.projects["p1"]["error"]


# --- Revertable per-item merge requests (ADR-0021) ----------------------------


def _patch_item_delivery(
    monkeypatch: pytest.MonkeyPatch, opened_calls: list[dict[str, Any]]
) -> None:
    """Patch the connector seams open_item_mr uses; record each MR's (branch, target)."""
    import mosaera_api.delivery as dmod

    monkeypatch.setattr(dmod, "open_project_workspace", lambda *a: _MrWS())
    monkeypatch.setattr(dmod, "project_base", lambda ws: "main")
    # Non-empty per-item diff so nothing skips on empty_diff.
    monkeypatch.setattr(dmod, "project_item_diff", lambda ws, target: "diff --git a/N b/N\n+x\n")

    def fake_open_mr(_root: Any, plan: Any, **k: Any) -> Any:
        opened_calls.append({"branch": plan.branch, "target": plan.base, **k})
        return _MrResult()

    monkeypatch.setattr(dmod, "open_merge_request", fake_open_mr)


def test_open_item_mr_stacks_on_predecessor_and_is_idempotent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    monkeypatch.setenv("MOSAERA_HOME", str(tmp_path))
    from mosaera_api.delivery import open_item_mr
    from mosaera_core.config import Settings

    calls: list[dict[str, Any]] = []
    _patch_item_delivery(monkeypatch, calls)
    mem = _FakeProjectMemory()
    mem.create_project("p1", "P", _GL, gitlab_token="proj-tok", autonomous=True)
    a = mem.add_backlog_item("p1", "item a", position=0)
    b = mem.add_backlog_item("p1", "item b", position=1)
    s = Settings.from_env()

    # First delivered item → MR targets the source base; branch + url recorded.
    out_a = open_item_mr(mem, s, "p1", a)  # type: ignore[arg-type]
    assert out_a.opened
    assert calls[0]["branch"] == f"mosaera/item-{a}" and calls[0]["target"] == "main"
    assert calls[0]["token"] == "proj-tok"  # scoped, never global
    assert calls[0]["remove_source_branch"] is False  # a later item stacks on this branch
    assert mem.items[a]["branch"] == f"mosaera/item-{a}"
    assert mem.items[a]["mr_url"].endswith("/merge_requests/1")

    # Second item → stacks on item a's branch (clean single-item diff).
    out_b = open_item_mr(mem, s, "p1", b)  # type: ignore[arg-type]
    assert out_b.opened and calls[1]["target"] == f"mosaera/item-{a}"

    # Re-opening a already has a branch → idempotent skip, no third connector call.
    assert open_item_mr(mem, s, "p1", a).skip == "already_open"  # type: ignore[arg-type]
    assert len(calls) == 2


def test_open_item_mr_skip_reasons(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    monkeypatch.setenv("MOSAERA_HOME", str(tmp_path))
    import mosaera_api.delivery as dmod
    from mosaera_api.delivery import open_item_mr
    from mosaera_core.config import Settings

    s = Settings.from_env()
    non_gl = _FakeProjectMemory()
    non_gl.create_project("g", "G", "https://github.com/x/y.git", gitlab_token="t")
    gi = non_gl.add_backlog_item("g", "x")
    # ADR-0112 splits this skip by detected provider; ADR-0114 splits the GitHub half again
    # by remedy. No App configured here → the instance-level reason. All still refuse.
    assert open_item_mr(non_gl, s, "g", gi).skip == "github_app_unconfigured"  # type: ignore[arg-type]

    unknown_host = _FakeProjectMemory()
    unknown_host.create_project("u", "U", "https://elsewhere.example/x/y.git", gitlab_token="t")
    ui = unknown_host.add_backlog_item("u", "x")
    assert open_item_mr(unknown_host, s, "u", ui).skip == "not_gitlab"  # type: ignore[arg-type]

    missing = _FakeProjectMemory()
    missing.create_project("p", "P", _GL, gitlab_token="t")
    assert open_item_mr(missing, s, "p", 999).skip == "no_item"  # type: ignore[arg-type]

    empty = _FakeProjectMemory()
    empty.create_project("e", "E", _GL, gitlab_token="t")
    ei = empty.add_backlog_item("e", "x")
    monkeypatch.setattr(dmod, "open_project_workspace", lambda *a: _MrWS())
    monkeypatch.setattr(dmod, "project_base", lambda ws: "main")
    monkeypatch.setattr(dmod, "project_item_diff", lambda ws, target: "   \n")
    assert open_item_mr(empty, s, "e", ei).skip == "empty_diff"  # type: ignore[arg-type]


def _spy_item_opener(monkeypatch: pytest.MonkeyPatch, calls: list[int]) -> None:
    from mosaera_api.delivery import MrOutcome

    def spy(mem: Any, settings: Any, pid: str, item_id: int) -> Any:
        calls.append(item_id)
        return MrOutcome(True, url="u")

    monkeypatch.setattr("mosaera_api.app_context._delivery.open_item_mr", spy)


def test_sweep_item_mr_fires_only_in_item_granularity(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    monkeypatch.setenv("MOSAERA_HOME", str(tmp_path))
    monkeypatch.setenv("MOSAERA_AUTO_OPEN_MR", "1")
    from mosaera_api.routes.context import AppContext

    calls: list[int] = []
    _spy_item_opener(monkeypatch, calls)
    ctx = AppContext(memory=_FakeProjectMemory())  # type: ignore[arg-type]

    # Default granularity is "item" → the per-item opener fires on clean delivery.
    ctx._maybe_open_item_mr("p1", 7, "run-7")
    assert calls == [7]

    # granularity="project" → per-item opener is inert (the whole-project hook handles it).
    monkeypatch.setenv("MOSAERA_MR_GRANULARITY", "project")
    ctx._maybe_open_item_mr("p1", 8, "run-8")
    assert calls == [7]

    # auto_open_mr OFF → nothing opens regardless of granularity.
    monkeypatch.setenv("MOSAERA_MR_GRANULARITY", "item")
    monkeypatch.delenv("MOSAERA_AUTO_OPEN_MR", raising=False)
    ctx._maybe_open_item_mr("p1", 9, "run-9")
    assert calls == [7]


def test_sweep_project_mr_suppressed_in_item_granularity(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    # The whole-project completion hook must NOT also fire in item mode (double MR).
    monkeypatch.setenv("MOSAERA_HOME", str(tmp_path))
    monkeypatch.setenv("MOSAERA_AUTO_OPEN_MR", "1")
    monkeypatch.setenv("MOSAERA_MR_GRANULARITY", "item")
    from mosaera_api.routes.context import AppContext

    calls: list[str] = []
    _spy_opener(monkeypatch, calls)
    mem = _FakeProjectMemory()
    detail = _delivered_project(mem)
    AppContext(memory=mem)._maybe_open_project_mr("p1", detail)  # type: ignore[arg-type]
    assert calls == []  # item mode → the project-level opener stays silent


# --- Live model escalation (ADR-0022) -----------------------------------------


class _FakeSession:
    def __init__(self, status: str, final: dict[str, Any] | None = None) -> None:
        self.status = status
        self.final = final or {}


def _esc_settings(**over: Any) -> Any:
    import dataclasses

    from mosaera_core.config import Settings

    fields = {"model_escalation_enabled": True, "max_model_escalations": 2, **over}
    return dataclasses.replace(Settings.from_env(env={}), **fields)


def test_try_model_escalation_fires_and_bounds(monkeypatch: pytest.MonkeyPatch) -> None:
    from mosaera_api.delivery import MrOutcome  # noqa: F401  (import parity w/ module)
    from mosaera_api.routes.context import AppContext
    from mosaera_core.bench.escalation import Escalation

    ctx = AppContext(memory=_FakeProjectMemory())  # type: ignore[arg-type]
    launched: list[dict[str, Any]] = []

    def _rec_launch(pid: str, it: Any, **k: Any) -> Any:
        launched.append(k)
        return _FakeSession("running")

    monkeypatch.setattr(ctx, "launch_item", _rec_launch)
    monkeypatch.setattr(
        "mosaera_api.app_context._model_escalation.diagnose_bottleneck", lambda final, s: "coder"
    )
    esc_settings = _esc_settings()
    monkeypatch.setattr(
        "mosaera_api.app_context._model_escalation.escalate_role",
        lambda s, role: Escalation(settings=esc_settings, role="coder", label="coder: a -> b"),
    )
    item = {"id": 5, "title": "t"}
    sess: Any = _FakeSession("incomplete", {"gate_decision": {"reasons": ["validation_failed"]}})

    # Fires: launches a re-run with the escalated settings + attempt+1, audits the path.
    fired = ctx._try_model_escalation(
        "p1", item, True, "autonomous", "run-0", sess, _esc_settings(), 0
    )
    assert fired is True
    assert launched and launched[0]["escalation_settings"] is esc_settings
    assert launched[0]["escalation_attempt"] == 1 and launched[0]["mode"] == "autonomous"
    assert any(a[1] == "escalation.coder" for a in getattr(ctx.history, "audits", []))

    # Bounded: at the max attempt, no further re-run.
    launched.clear()
    assert (
        ctx._try_model_escalation("p1", item, True, "autonomous", "r", sess, _esc_settings(), 2)
        is False
    )
    assert launched == []


def test_try_model_escalation_gating(monkeypatch: pytest.MonkeyPatch) -> None:
    from mosaera_api.routes.context import AppContext
    from mosaera_core.bench.escalation import Escalation

    ctx = AppContext(memory=_FakeProjectMemory())  # type: ignore[arg-type]
    launched: list[dict[str, Any]] = []
    monkeypatch.setattr(ctx, "launch_item", lambda *a, **k: launched.append(k))
    monkeypatch.setattr(
        "mosaera_api.app_context._model_escalation.diagnose_bottleneck", lambda final, s: "coder"
    )
    monkeypatch.setattr(
        "mosaera_api.app_context._model_escalation.escalate_role",
        lambda s, role: Escalation(_esc_settings(), "coder", "x"),
    )
    item = {"id": 1, "title": "t"}
    sess: Any = _FakeSession("incomplete", {})

    off = _esc_settings(model_escalation_enabled=False)  # separate opt-in, default OFF
    assert ctx._try_model_escalation("p", item, True, "autonomous", "r", sess, off, 0) is False
    # Not an autonomous run → never escalates (guided/HA/ad-hoc have their own gate).
    assert (
        ctx._try_model_escalation("p", item, True, "guided", "r", sess, _esc_settings(), 0) is False
    )
    assert launched == []


def test_try_model_escalation_not_diagnosable_or_ladder_exhausted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mosaera_api.routes.context import AppContext

    ctx = AppContext(memory=_FakeProjectMemory())  # type: ignore[arg-type]
    launched: list[Any] = []
    monkeypatch.setattr(ctx, "launch_item", lambda *a, **k: launched.append(k))
    item = {"id": 1, "title": "t"}
    sess: Any = _FakeSession("incomplete", {})

    # No attributable role → don't escalate blindly.
    monkeypatch.setattr(
        "mosaera_api.app_context._model_escalation.diagnose_bottleneck", lambda final, s: None
    )
    assert (
        ctx._try_model_escalation("p", item, True, "autonomous", "r", sess, _esc_settings(), 0)
        is False
    )

    # Diagnosed, but the role's ladder is exhausted (escalate_role → None) → park.
    monkeypatch.setattr(
        "mosaera_api.app_context._model_escalation.diagnose_bottleneck", lambda final, s: "coder"
    )
    monkeypatch.setattr(
        "mosaera_api.app_context._model_escalation.escalate_role", lambda s, role: None
    )
    assert (
        ctx._try_model_escalation("p", item, True, "autonomous", "r", sess, _esc_settings(), 0)
        is False
    )
    assert launched == []


def test_model_escalation_cloud_tier_gated_by_egress_consent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import dataclasses

    from mosaera_api.routes.context import AppContext
    from mosaera_core.bench.escalation import Escalation

    ctx = AppContext(memory=_FakeProjectMemory())  # type: ignore[arg-type]
    launched: list[Any] = []
    monkeypatch.setattr(ctx, "launch_item", lambda *a, **k: launched.append(k))
    monkeypatch.setattr(
        "mosaera_api.app_context._model_escalation.diagnose_bottleneck", lambda final, s: "coder"
    )
    # The escalated tier bumps coder to a CLOUD model (anthropic/claude-x).
    cloud = dataclasses.replace(
        _esc_settings(), role_providers={"coder": "anthropic"}, coder_model="claude-x"
    )
    monkeypatch.setattr(
        "mosaera_api.app_context._model_escalation.escalate_role",
        lambda s, role: Escalation(cloud, "coder", "coder: local -> claude-x"),
    )
    item = {"id": 1, "title": "t"}
    sess: Any = _FakeSession("incomplete", {})

    # No egress consent → the cloud escalation is refused (audited), no re-run launched.
    off = _esc_settings()  # allow_cloud_egress OFF, no prices
    assert ctx._try_model_escalation("p", item, True, "autonomous", "r", sess, off, 0) is False
    assert launched == []
    assert any(a[1] == "escalation.blocked" for a in getattr(ctx.history, "audits", []))

    # Consent + a price for the cloud model → the escalation proceeds.
    ok = _esc_settings(allow_cloud_egress=True, model_prices={"claude-x": (3.0, 15.0)})
    assert ctx._try_model_escalation("p", item, True, "autonomous", "r", sess, ok, 0) is True
    assert launched and launched[0]["escalation_settings"] is cloud


def test_autonomous_run_blocked_on_unconsented_cloud_binding(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    # Seam 3: an autonomous run whose coder binds a cloud model is blocked at submit with a
    # clear note — until egress is consented AND the model is priced. Guided is unaffected.
    monkeypatch.setenv("MOSAERA_HOME", str(tmp_path))
    monkeypatch.setenv("MOSAERA_PROVIDER_CODER", "anthropic")
    monkeypatch.setenv("MOSAERA_MODEL_CODER", "claude-x")
    mem = _FakeProjectMemory()
    mem.create_project("p1", "P", "src", autonomous=True)
    mem.add_backlog_item("p1", "one", position=0)
    c = TestClient(create_app(graph_factory=_mem_factory(mem), memory=mem))  # type: ignore[arg-type]

    assert c.post("/api/projects/p1/start").status_code == 202
    for _ in range(200):
        if "blocked" in mem.projects["p1"].get("error", ""):
            break
        time.sleep(0.02)
    err = mem.projects["p1"]["error"]
    assert "blocked" in err and "claude-x" in err  # clear, actionable, no run started
    assert all(i["status"] == "todo" for i in mem.list_backlog_items("p1"))  # nothing ran


def test_resolve_run_settings_override_short_circuits(tmp_path: Any) -> None:
    from mosaera_api.factory import resolve_run_settings

    req = RunSubmit(repo="r", task="t", cost_mode="thrifty", autonomous=True)
    # None → from_env + overlays (cost_mode applied).
    base = resolve_run_settings(req, None)
    assert base.active_cost_mode == "thrifty"
    # An escalated Settings is returned verbatim (no from_env / overlay re-derivation).
    esc = _esc_settings()
    assert resolve_run_settings(req, esc) is esc


# --- Resilient autonomous sweep (ADR-0023) ------------------------------------


def _defer_ctx(monkeypatch: pytest.MonkeyPatch, mem: Any) -> tuple[Any, list[str]]:
    """An AppContext over `mem` with advance_project spied (records project ids)."""
    from mosaera_api.routes.context import AppContext

    ctx = AppContext(memory=mem)  # type: ignore[arg-type]
    advanced: list[str] = []
    monkeypatch.setattr(ctx, "advance_project", lambda pid: advanced.append(pid))
    return ctx, advanced


def _status(mem: Any, iid: int) -> str:
    it = mem.get_backlog_item(iid)
    assert it is not None
    return str(it["status"])


def test_sweep_incomplete_defers_and_advances(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    monkeypatch.setenv("MOSAERA_HOME", str(tmp_path))  # resilient_sweep default ON
    mem = _FakeProjectMemory()
    mem.create_project("p1", "P", _GL, autonomous=True)
    iid = mem.add_backlog_item("p1", "stuck", position=0)
    ctx, advanced = _defer_ctx(monkeypatch, mem)
    sess: Any = _FakeSession("incomplete", {})
    sess.termination_reason = "validation kept failing"

    handled = ctx._try_recurate_or_defer(
        "p1", {"id": iid, "title": "stuck"}, "autonomous", "r", sess
    )
    assert handled is True
    assert _status(mem, iid) == "deferred"  # deferred, not left todo
    assert advanced == ["p1"]  # the sweep continues to the next runnable item
    assert any(a[1] == "sweep.deferred" for a in mem.audits)


def test_resilient_sweep_off_preserves_pause(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    monkeypatch.setenv("MOSAERA_HOME", str(tmp_path))
    monkeypatch.setenv("MOSAERA_RESILIENT_SWEEP", "0")  # opt out → today's halt behavior
    mem = _FakeProjectMemory()
    mem.create_project("p1", "P", _GL, autonomous=True)
    iid = mem.add_backlog_item("p1", "stuck")
    ctx, advanced = _defer_ctx(monkeypatch, mem)
    sess: Any = _FakeSession("incomplete", {})

    handled = ctx._try_recurate_or_defer(
        "p1", {"id": iid, "title": "stuck"}, "autonomous", "r", sess
    )
    assert handled is False  # _after falls through to its pause note
    assert _status(mem, iid) != "deferred"
    assert advanced == []


def test_deferred_item_excluded_from_picker(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    monkeypatch.setenv("MOSAERA_HOME", str(tmp_path))
    from mosaera_api.routes.context import AppContext

    mem = _FakeProjectMemory()
    mem.create_project("p1", "P", _GL, autonomous=True)
    deferred = mem.add_backlog_item("p1", "deferred one", position=0)
    todo = mem.add_backlog_item("p1", "todo two", position=1)
    mem.update_backlog_item(deferred, status="deferred")
    ctx = AppContext(memory=mem)  # type: ignore[arg-type]
    launched: list[int] = []
    monkeypatch.setattr(ctx, "launch_item", lambda pid, item, **k: launched.append(item["id"]))

    ctx.advance_project("p1")
    assert launched == [todo]  # the deferred item is skipped, no infinite re-select


def test_completion_summary_lists_deferred(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    monkeypatch.setenv("MOSAERA_HOME", str(tmp_path))
    from mosaera_api.routes.context import AppContext

    mem = _FakeProjectMemory()
    mem.create_project("p1", "P", _GL, autonomous=True)
    a = mem.add_backlog_item("p1", "shipped", position=0)
    b = mem.add_backlog_item("p1", "gave up", position=1)
    mem.update_backlog_item(a, status="in_review")
    mem.update_backlog_item(b, status="deferred")
    ctx = AppContext(memory=mem)  # type: ignore[arg-type]

    ctx.advance_project("p1")  # no runnable todo → idle branch writes the honest summary
    note = mem.projects["p1"]["error"]
    assert "delivered 1" in note and "deferred 1" in note and "gave up" in note


def test_recuration_off_by_default_defers_directly(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    monkeypatch.setenv("MOSAERA_HOME", str(tmp_path))  # resilient_recuration default OFF
    import mosaera_api.projects as pmod

    called: list[str] = []

    def _rec_curate(*a: Any, **k: Any) -> list[Any]:
        called.append("curate")
        return []

    monkeypatch.setattr(pmod, "curate_backlog", _rec_curate)
    mem = _FakeProjectMemory()
    mem.create_project("p1", "P", _GL, autonomous=True)
    iid = mem.add_backlog_item("p1", "stuck")
    ctx, _ = _defer_ctx(monkeypatch, mem)
    ctx._try_recurate_or_defer(
        "p1", {"id": iid, "title": "stuck"}, "autonomous", "r", _FakeSession("incomplete")
    )
    assert called == []  # Quincy not consulted when the opt-in is off
    assert _status(mem, iid) == "deferred"


def test_recuration_auto_applies_then_defers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    monkeypatch.setenv("MOSAERA_HOME", str(tmp_path))
    monkeypatch.setenv("MOSAERA_RESILIENT_RECURATION", "1")
    import mosaera_api.projects as pmod

    applied: list[Any] = []
    # Quincy re-scopes (enhance) the stuck item but its id stays → the changeset is auto-applied
    # AND the item is deferred (loop-safe: never retry the same id in-place).
    monkeypatch.setattr(
        pmod, "curate_backlog", lambda mem, pid, instruction="": [{"op": "enhance"}]
    )
    monkeypatch.setattr(pmod, "apply_backlog_changeset", lambda mem, pid, cs: applied.append(cs))
    mem = _FakeProjectMemory()
    mem.create_project("p1", "P", _GL, autonomous=True)
    iid = mem.add_backlog_item("p1", "stuck")  # stays (fake apply is a no-op)
    ctx, advanced = _defer_ctx(monkeypatch, mem)

    ctx._try_recurate_or_defer(
        "p1", {"id": iid, "title": "stuck"}, "autonomous", "r", _FakeSession("incomplete")
    )
    assert applied  # the changeset was auto-applied (autonomous)
    assert _status(mem, iid) == "deferred"  # loop-safe: deferred, not retried
    assert advanced == ["p1"]
    assert any(a[1] == "sweep.recurated" for a in mem.audits)


def test_recuration_removing_item_does_not_defer(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    monkeypatch.setenv("MOSAERA_HOME", str(tmp_path))
    monkeypatch.setenv("MOSAERA_RESILIENT_RECURATION", "1")
    import mosaera_api.projects as pmod

    mem = _FakeProjectMemory()
    mem.create_project("p1", "P", _GL, autonomous=True)
    iid = mem.add_backlog_item("p1", "stuck")
    # Quincy split/deleted the item — the id is gone after apply.
    monkeypatch.setattr(pmod, "curate_backlog", lambda mem, pid, instruction="": [{"op": "split"}])
    monkeypatch.setattr(
        pmod, "apply_backlog_changeset", lambda m, pid, cs: mem.delete_backlog_item(iid)
    )
    ctx, advanced = _defer_ctx(monkeypatch, mem)

    handled = ctx._try_recurate_or_defer(
        "p1", {"id": iid, "title": "stuck"}, "autonomous", "r", _FakeSession("incomplete")
    )
    assert handled is True
    assert mem.get_backlog_item(iid) is None  # gone, nothing to defer
    assert advanced == ["p1"]
    assert any(a[1] == "sweep.recurated-removed" for a in mem.audits)


def test_recuration_no_mix_valueerror_swallowed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    monkeypatch.setenv("MOSAERA_HOME", str(tmp_path))
    monkeypatch.setenv("MOSAERA_RESILIENT_RECURATION", "1")
    import mosaera_api.projects as pmod

    def _raise(mem: Any, pid: str, cs: Any) -> None:
        raise ValueError("cannot mix structural ops with reorder")

    monkeypatch.setattr(pmod, "curate_backlog", lambda mem, pid, instruction="": [{"op": "merge"}])
    monkeypatch.setattr(pmod, "apply_backlog_changeset", _raise)
    mem = _FakeProjectMemory()
    mem.create_project("p1", "P", _GL, autonomous=True)
    iid = mem.add_backlog_item("p1", "stuck")
    ctx, advanced = _defer_ctx(monkeypatch, mem)

    handled = ctx._try_recurate_or_defer(
        "p1", {"id": iid, "title": "stuck"}, "autonomous", "r", _FakeSession("incomplete")
    )
    assert handled is True  # the bad changeset is swallowed, not fatal
    assert _status(mem, iid) == "deferred"  # falls through to a plain defer
    assert advanced == ["p1"]


def test_resilient_sweep_defers_and_delivers_the_rest_e2e(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    # End-to-end: with resilient_sweep ON, a blocking delivery gate does NOT park-and-hold —
    # the run ends incomplete, the item is deferred, and the sweep keeps going. Here BOTH
    # items fail validation, so both defer and the project ends with an honest summary (no
    # run ever reaches awaiting_approval — the D3 park reroute).
    monkeypatch.setenv("MOSAERA_HOME", str(tmp_path))  # resilient_sweep default ON
    mem = _FakeProjectMemory()
    mem.create_project("p1", "P", "src", autonomous=True)
    mem.add_backlog_item("p1", "one", position=0)
    mem.add_backlog_item("p1", "two", position=1)
    c = TestClient(
        create_app(graph_factory=_mem_factory(mem, tests_passed=False), memory=mem)  # type: ignore[arg-type]
    )
    assert c.post("/api/projects/p1/start").status_code == 202

    for _ in range(400):
        statuses = [i["status"] for i in mem.list_backlog_items("p1")]
        if statuses and all(s == "deferred" for s in statuses):
            break
        # No run should ever park for a human in resilient mode.
        assert not any(
            r["status"] == "awaiting_approval" for r in c.get("/api/runs").json()["runs"]
        )
        time.sleep(0.02)
    assert [i["status"] for i in mem.list_backlog_items("p1")] == ["deferred", "deferred"]
    assert "deferred 2" in mem.projects["p1"]["error"]
    assert any(e[1] == "resilient-giveup" for e in mem.audits)


def test_resilient_giveup_persists_receipt_and_claims(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    # ADR-0078 capture: the resilient giveup breaks AT the gate interrupt, so deliver_node's
    # persist never runs — without the runner-side capture the receipt and claim ledger of a
    # never-resumed park silently vanish. The stash must carry the payload's receipt fields.
    monkeypatch.setenv("MOSAERA_HOME", str(tmp_path))  # resilient_sweep default ON
    mem = _FakeProjectMemory()
    mem.create_project("p1", "P", "src", autonomous=True)
    mem.add_backlog_item("p1", "one", position=0)
    claims = [{"id": "1-c1", "text": "keeps the public API"}]
    disps = [{"claim_id": "1-c1", "verdict": "satisfied", "oracle_ref": "extract_helper(a)"}]
    c = TestClient(
        create_app(
            graph_factory=_mem_factory(
                mem,
                tests_passed=False,
                claims=claims,
                claim_dispositions=disps,
                oracle_vouched_by="structural_claims:1-c1",
                oracle_residual="shape: proven · UNPROVEN: a mutation survives",
            ),
            memory=mem,  # type: ignore[arg-type]
        )
    )
    assert c.post("/api/projects/p1/start").status_code == 202
    for _ in range(400):
        if any(k == "receipt" for _, k, _ in mem.decisions):
            break
        time.sleep(0.02)
    receipt = json.loads(next(content for _, k, content in mem.decisions if k == "receipt"))
    assert receipt["action"] == "require_human"  # failed validation parks for a person
    assert "validation_failed" in receipt["reasons"]
    assert receipt["oracle_vouched_by"] == "structural_claims:1-c1"
    assert receipt["oracle_residual"].startswith("shape: proven")
    # The ledger rows landed exactly once (belt-and-braces dedupe), with the joined verdict.
    (rows,) = mem.run_claims.values()
    assert [(r["claim_id"], r["verdict"]) for r in rows] == [("1-c1", "satisfied")]
    # And the never-resumed park is SEALED (#63): version + deterministic receipt id.
    ((version, receipt_id),) = mem.receipt_stamps.values()
    import mosaera_core

    assert version == mosaera_core.__version__
    assert len(receipt_id) == 64


def test_resilient_giveup_still_escalates_before_deferring(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    # Regression (found live): the D3 resilient giveup breaks at the gate interrupt BEFORE the
    # gate node commits gate_decision to state, so the captured `final` had no gate_decision and
    # `diagnose_bottleneck` returned None → model escalation silently NO-OP'd on every gate-blocked
    # item. With the fix (stash + restore gate_decision), a blocked item is DIAGNOSED and escalated
    # (a local tier here) before it defers — so an `escalation.coder` event must appear.
    monkeypatch.setenv("MOSAERA_HOME", str(tmp_path))  # resilient_sweep default ON
    monkeypatch.setenv("MOSAERA_MODEL_ESCALATION", "1")
    monkeypatch.setenv("MOSAERA_MAX_MODEL_ESCALATIONS", "1")
    monkeypatch.setenv(
        "MOSAERA_ROLE_ESCALATION",
        '{"coder": [{"provider": "ollama", "model": "qwen2.5-coder:32b"}]}',
    )
    mem = _FakeProjectMemory()
    mem.create_project("p1", "P", "src", autonomous=True)
    mem.add_backlog_item("p1", "one", position=0)
    c = TestClient(
        create_app(graph_factory=_mem_factory(mem, tests_passed=False), memory=mem)  # type: ignore[arg-type]
    )
    assert c.post("/api/projects/p1/start").status_code == 202

    for _ in range(400):
        if mem.list_backlog_items("p1")[0]["status"] == "deferred":
            break
        time.sleep(0.02)
    # The item still ends deferred (escalation exhausted after 1 local bump), but it ESCALATED
    # first — proof that gate_decision was restored so diagnosis could attribute the bottleneck.
    assert mem.list_backlog_items("p1")[0]["status"] == "deferred"
    assert any(e[1] == "escalation.coder" for e in mem.audits), "escalation never fired"


def test_project_detail_never_leaks_raw_token() -> None:
    mem = _FakeProjectMemory()
    mem.create_project("p1", "P", "src", gitlab_token="glpat-secret1234")
    c = _client_with(mem)
    assert "glpat-secret1234" not in c.get("/api/projects/p1").text
    assert "glpat-secret1234" not in c.get("/api/projects").text  # list must not leak either
    detail = c.get("/api/projects/p1").json()
    assert detail["has_gitlab_token"] is True and detail["gitlab_token_masked"] == "…1234"


def test_set_project_token(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    monkeypatch.setenv("MOSAERA_HOME", str(tmp_path))
    # The PAT write is localhost-gated; TestClient isn't local, so allow it here.
    monkeypatch.setenv("MOSAERA_ALLOW_REMOTE_CONFIG", "1")
    # A non-GitLab source skips the live check, so this stays offline.
    mem = _FakeProjectMemory()
    mem.create_project("p1", "P", "https://github.com/x/y.git")
    r = _client_with(mem).post("/api/projects/p1/token", json={"token": "glpat-abcd"})
    assert r.status_code == 200 and r.json()["has_gitlab_token"] is True
    assert mem.get_project_token("p1") == "glpat-abcd"


def test_set_project_api_token_probes_scope(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    # ADR-0103: the optional api-scoped token is stored only if it ACTUALLY carries `api`
    # scope; a mis-scoped token is refused (honest UX, fail-fast).
    import mosaera_api.routes.projects as proj_mod

    monkeypatch.setenv("MOSAERA_HOME", str(tmp_path))
    monkeypatch.setenv("MOSAERA_ALLOW_REMOTE_CONFIG", "1")
    mem = _FakeProjectMemory()
    mem.create_project("p1", "P", "https://github.com/x/y.git")
    c = _client_with(mem)

    # A token whose scopes lack `api` is refused, and nothing is stored.
    monkeypatch.setattr(
        proj_mod.glc, "get_token_info", lambda *a: ({"scopes": ["write_repository"]}, None)
    )
    bad = c.post("/api/projects/p1/token", json={"token": "glpat-x", "api_token": "glpat-narrow"})
    assert bad.status_code == 400 and "api" in bad.json()["detail"]
    assert mem.get_project_api_token("p1") is None

    # A genuine api token is accepted and persisted; presence surfaces, value never does.
    monkeypatch.setattr(proj_mod.glc, "get_token_info", lambda *a: ({"scopes": ["api"]}, None))
    ok = c.post("/api/projects/p1/token", json={"token": "glpat-x", "api_token": "glpat-api"})
    assert ok.status_code == 200 and ok.json()["has_gitlab_api_token"] is True
    assert mem.get_project_api_token("p1") == "glpat-api"
    assert "gitlab_api_token" not in ok.json()  # the raw value never leaves the server


def test_delete_project(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    monkeypatch.setenv("MOSAERA_HOME", str(tmp_path))
    mem = _FakeProjectMemory()
    mem.create_project("p1", "P", "src")
    mem.add_backlog_item("p1", "x")
    c = _client_with(mem)
    assert c.delete("/api/projects/p1").json() == {"deleted": "p1"}
    assert "p1" not in mem.projects
    assert c.delete("/api/projects/p1").status_code == 404


def test_delete_run(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    monkeypatch.setenv("MOSAERA_HOME", str(tmp_path))
    mem = _FakeProjectMemory()
    assert _client_with(mem).delete("/api/runs/run-9").json() == {"deleted": "run-9"}
    assert mem.deleted_runs == ["run-9"]


def test_generate_backlog_clears_todo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("mosaera_api.routes.backlog.start_decompose", lambda *a: None)
    mem = _FakeProjectMemory()
    mem.create_project("p1", "P", "src")
    mem.add_backlog_item("p1", "stale todo")
    c = _client_with(mem)
    assert c.post("/api/projects/p1/backlog/generate").status_code == 202
    assert mem.list_backlog_items("p1") == []  # stale todo cleared before regen


def _decompose_lint_setup(
    monkeypatch: pytest.MonkeyPatch, acceptance: str
) -> tuple[_FakeProjectMemory, Any]:
    """A fake-memory project whose decompose emits one item with ``acceptance``."""
    import mosaera_api.projects as projects_mod

    mem = _FakeProjectMemory()
    mem.create_project("p1", "P", "src")
    mem.update_project("p1", repo_overview="an overview")
    monkeypatch.setattr(projects_mod, "get_chat_model", lambda *a, **k: object())
    monkeypatch.setattr(projects_mod.pm, "synthesize_understanding", lambda *a, **k: "the brief")
    items = [{"title": "Add module", "description": "d", "acceptance": acceptance}]
    monkeypatch.setattr(projects_mod.pm, "decompose_brief", lambda *a, **k: items)
    return mem, projects_mod


def test_a_ratified_clause_stops_the_question_being_asked_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The gap this whole arc exists to close, end to end.

    Measured 2026-08-04: stating "at most 5 statements" moved a paired benchmark from 0/6 to 5/6
    grader-clean — but the repair was authored by hand and nothing recorded it, so the next item
    asked the same question again. Here the decision is ratified once and the same finding is
    answered, so Quincy is never handed the instruction.

    Drives `_lint_and_recurate` directly rather than `run_decompose`, because decompose APPENDS a
    fresh backlog on every call — a second call would compare two identical items and fire
    `near_duplicate`, a finding no clause binds. That would have passed for the wrong reason.
    """
    import mosaera_api.projects as projects_mod
    from mosaera_core.clauses import ratify_clause

    monkeypatch.setenv("MOSAERA_CLAUSES", "1")
    mem = _FakeProjectMemory()
    mem.create_project("p1", "P", "src")
    mem.add_backlog_item(
        "p1",
        "Refactor checkout",
        "d",
        "`checkout_total` should read as a short orchestrator (a handful of statements) "
        "that delegates to helpers.",
        0,
    )
    called: list[str] = []

    def _asked(*a: Any, **k: Any) -> list[dict[str, Any]]:
        called.append("asked")
        return []

    monkeypatch.setattr(projects_mod, "curate_backlog", _asked)

    # Without a standing decision the undecidable claim reaches Quincy — today's behaviour.
    projects_mod._lint_and_recurate(mem, "p1")  # type: ignore[arg-type]
    assert called == ["asked"]

    # The operator settles it ONCE…
    clause = ratify_clause(
        mem,
        standard_id="standards/house-style",
        binds="structural.body_statements",
        value_kind="number",
        value_num=5,
        project_id="p1",
        because="correctness over line count",
    )

    # …and the same finding is now answered, so nothing is re-asked.
    called.clear()
    projects_mod._lint_and_recurate(mem, "p1")  # type: ignore[arg-type]
    assert called == [], "a ratified clause must settle the finding it binds"

    # And the operator can see WHY the board stopped flagging it — silent suppression would be
    # indistinguishable from the check breaking.
    row = {i["id"]: i for i in _client_with(mem).get("/api/projects/p1/backlog").json()["backlog"]}
    assert next(iter(row.values()))["decided_by"] == clause.id


def _undecidable_setup(monkeypatch: pytest.MonkeyPatch) -> tuple[Any, Any, int]:
    """A project with one item whose check BINDS and whose text never fixes the answer."""
    import mosaera_api.projects as projects_mod

    mem = _FakeProjectMemory()
    mem.create_project("p1", "P", "src")
    iid = mem.add_backlog_item(
        "p1", "Scorer", "d", "A CLI reads a password and prints a strength score 0-4.", 0
    )
    monkeypatch.setattr(
        projects_mod,
        "curate_backlog",
        lambda *a, **k: [
            {
                "op": "enhance",
                "id": iid,
                "acceptance": "prints a score equal to the number of these rules met: …",
                "why": "lint",
            }
        ],
    )
    return mem, projects_mod, iid


def test_an_undecidable_item_asks_the_operator_instead_of_being_rewritten(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The defect this arc closes.

    An undecidable claim is a question only the operator can answer, and the re-curate pass had
    Quincy answering it himself — inventing a rule and applying it silently, which is the same
    failure the detector exists to catch, one level up. He still authors the PROPOSAL; he no
    longer decides.
    """
    monkeypatch.setenv("MOSAERA_INTAKE_ASK_UNDECIDABLE", "1")
    mem, projects_mod, iid = _undecidable_setup(monkeypatch)
    before = mem.items[iid]["acceptance"]

    projects_mod._lint_and_recurate(mem, "p1")  # type: ignore[arg-type]

    assert mem.items[iid]["acceptance"] == before, "the rewrite must NOT be applied silently"
    ask = mem.items[iid]["clarification"]
    assert ask and ask["status"] == "open"
    assert "score 0-4" in ask["claim_text"]
    assert "no rule for how the value is composed" in ask["why_unbindable"]
    assert ask["proposals"] == ["prints a score equal to the number of these rules met: …"]


def test_with_the_knob_off_the_rewrite_is_applied_exactly_as_today(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The inertness proof at the API boundary — turning it off must actually turn it off."""
    mem, projects_mod, iid = _undecidable_setup(monkeypatch)
    projects_mod._lint_and_recurate(mem, "p1")  # type: ignore[arg-type]

    assert mem.items[iid]["acceptance"].startswith("prints a score equal to")
    assert not mem.items[iid].get("clarification")


def test_a_ratified_clause_prevents_the_ask_as_well_as_the_finding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Being asked to re-answer your own decision IS the fatigue hazard ADR-0080 names."""
    from mosaera_core.clauses import ratify_clause

    monkeypatch.setenv("MOSAERA_INTAKE_ASK_UNDECIDABLE", "1")
    monkeypatch.setenv("MOSAERA_CLAUSES", "1")
    import mosaera_api.projects as projects_mod

    mem = _FakeProjectMemory()
    mem.create_project("p1", "P", "src")
    iid = mem.add_backlog_item(
        "p1",
        "Refactor",
        "d",
        "`f` should read as a short orchestrator (a handful of statements).",
        0,
    )
    called: list[str] = []

    def _curate(*a: Any, **k: Any) -> list[dict[str, Any]]:
        called.append("asked")
        return []

    monkeypatch.setattr(projects_mod, "curate_backlog", _curate)
    ratify_clause(
        mem,
        standard_id="standards/house-style",
        binds="structural.body_statements",
        value_kind="number",
        value_num=5,
        project_id="p1",
        because="correctness over line count",
    )

    projects_mod._lint_and_recurate(mem, "p1")  # type: ignore[arg-type]
    assert called == [], "a settled question reaches neither Quincy nor the operator"
    assert not mem.items[iid].get("clarification")


def test_a_decidability_ask_blocks_the_launch_with_its_own_wording(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Asserted, not assumed.

    The plan claimed a decidability ask "blocks for free" because the launch gate keys on the
    PRESENCE of an open clarification rather than on the verdict. Free or not, an unasserted
    claim about a safety gate is worth nothing.
    """
    monkeypatch.setenv("MOSAERA_INTAKE_ASK_UNDECIDABLE", "1")
    mem, projects_mod, iid = _undecidable_setup(monkeypatch)
    projects_mod._lint_and_recurate(mem, "p1")  # type: ignore[arg-type]
    assert mem.items[iid]["clarification"]

    client = _client_with(mem)
    blocked = client.post(f"/api/projects/p1/backlog/{iid}/run")
    assert blocked.status_code == 409
    detail = blocked.json()["detail"]
    assert detail.startswith("open clarification: ")  # prefix is byte-stable
    assert "the text doesn't fix the answer" in detail  # …the tail is per-axis
    # The operator's escape hatch still works.
    assert (
        client.post(f"/api/projects/p1/backlog/{iid}/run", json={"override": True}).status_code
        == 201
    )


def test_decompose_spec_lint_recurates_once(monkeypatch: pytest.MonkeyPatch) -> None:
    # ADR-0073: the #53 exact-tuple acceptance is flagged deterministically, Quincy gets ONE
    # bounded re-curate pass (the findings are the instruction), and the enhance is applied
    # through the validated changeset applier.
    mem, projects_mod = _decompose_lint_setup(
        monkeypatch, "Calling `strength('short')` returns `(1, ['too short (len < 8)'])`."
    )
    calls: list[str] = []

    def fake_curate(
        model: Any, backlog: str, brief: str, instruction: str, doctrine: str, **kw: Any
    ) -> Any:
        calls.append(instruction)
        iid = mem.list_backlog_items("p1")[0]["id"]
        return [{"op": "enhance", "id": iid, "acceptance": "score is an int 0-4", "why": "lint"}]

    monkeypatch.setattr(projects_mod.pm, "curate_backlog", fake_curate)
    projects_mod.run_decompose(mem, "p1")
    items = mem.list_backlog_items("p1")
    assert items and items[0]["acceptance"] == "score is an int 0-4"  # lint fix applied
    assert len(calls) == 1  # one bounded pass, no loop
    assert "exact" in calls[0] and "propose nothing else" in calls[0]
    assert mem.projects["p1"]["error"] == ""  # advisory findings never write the error note


def test_decompose_spec_lint_rejected_changeset_keeps_backlog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A malformed re-curate changeset is rejected wholesale by the applier (ValueError) —
    # decompose keeps the as-authored backlog rather than failing.
    original = "Calling `strength('short')` returns `(1, ['too short (len < 8)'])`."
    mem, projects_mod = _decompose_lint_setup(monkeypatch, original)
    monkeypatch.setattr(
        projects_mod.pm,
        "curate_backlog",
        lambda *a, **k: [{"op": "enhance", "id": 999999, "why": "bad id"}],
    )
    projects_mod.run_decompose(mem, "p1")
    items = mem.list_backlog_items("p1")
    assert items and items[0]["acceptance"] == original  # unlinted backlog survives
    assert mem.projects["p1"]["error"] == ""  # and decompose did not report failure


def test_decompose_spec_lint_silent_when_clean(monkeypatch: pytest.MonkeyPatch) -> None:
    # Behavioural acceptance produces no findings → no curate call at all.
    # The sample used to name a "score 0-4"; that is CHECKABLE and UNDECIDABLE (the cell where a
    # checker binds over a value the text never fixes), so decidability now flags it correctly —
    # it is the greenfield brief's shape, written here as an example of clean. The assertion is
    # unchanged; only the sample moved to one that really is clean.
    mem, projects_mod = _decompose_lint_setup(
        monkeypatch, "strength(password) returns an int and a non-empty list of reasons"
    )
    called: list[int] = []

    def fake_curate(*a: Any, **k: Any) -> list[dict[str, Any]]:
        called.append(1)
        return []

    monkeypatch.setattr(projects_mod.pm, "curate_backlog", fake_curate)
    projects_mod.run_decompose(mem, "p1")
    assert called == []  # lint found nothing; the extra PM call never happens


def test_charter_get_returns_honest_defaults() -> None:
    mem = _FakeProjectMemory()
    mem.create_project("p1", "P", "src")
    c = _client_with(mem)
    body = c.get("/api/projects/p1/charter").json()
    assert body["posture"] == "business" and body["goal"] == ""
    assert c.get("/api/projects/nope/charter").status_code == 404


def test_charter_put_gates_POSTURE_not_intent(monkeypatch: pytest.MonkeyPatch) -> None:
    """ADR-0047 amendment: the gate is per FIELD. Intent is member-writable (gating it dead-ended
    the product's primary journey in a 403); posture stays an admin-only ADR-0046 declaration."""
    monkeypatch.delenv("MOSAERA_ALLOW_REMOTE_CONFIG", raising=False)
    mem = _FakeProjectMemory()
    mem.create_project("p1", "P", "src")
    c = _client_with(mem)
    # Intent alone: allowed with no admin authority, and it does NOT invent a posture.
    r = c.put("/api/projects/p1/charter", json={"goal": "g", "constraints": "stdlib"})
    assert r.status_code == 200 and r.json()["goal"] == "g"
    assert r.json()["posture"] == "business"
    # Changing posture is refused without admin authority.
    bad = c.put("/api/projects/p1/charter", json={"goal": "g", "posture": "free"})
    assert bad.status_code == 403
    # Re-sending the stored posture is not a governance act (the charter card does it every save).
    r2 = c.put("/api/projects/p1/charter", json={"goal": "g2", "posture": "business"})
    assert r2.status_code == 200
    monkeypatch.setenv("MOSAERA_ALLOW_REMOTE_CONFIG", "1")
    # Out-of-set posture → 400 (the ADR-0005 enum rule, deny-by-default in the store).
    r = c.put("/api/projects/p1/charter", json={"goal": "g", "posture": "yolo"})
    assert r.status_code == 400
    # A valid write round-trips (and normalizes case).
    r = c.put(
        "/api/projects/p1/charter",
        json={"goal": "ship it", "constraints": "stdlib", "posture": "Regulated"},
    )
    assert r.status_code == 200 and r.json()["posture"] == "regulated"
    assert c.get("/api/projects/p1/charter").json()["goal"] == "ship it"


def test_charter_postures_in_sync() -> None:
    # The agents-side literal (proposal validation) must equal the store enum — the
    # sync test that lets agents avoid importing the persistence layer.
    from mosaera_agents.pm._proposals import _POSTURES
    from mosaera_memory.models_charter import CHARTER_POSTURES

    assert _POSTURES == CHARTER_POSTURES


def test_pm_chat_surfaces_the_charter_proposal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "MOSAERA_PM_CHAT_TOOLS", "0"
    )  # pin the pre-ADR-0111 single-call arm this test mocks
    import mosaera_api.pm_turn as pm_turn_mod
    import mosaera_api.projects as projects_mod

    mem: Any = _FakeProjectMemory()
    mem.create_project("p1", "P", "src")
    monkeypatch.setattr(projects_mod, "get_chat_model", lambda *a, **k: object())
    proposal = {"goal": "ship", "constraints": "", "posture": "business"}
    monkeypatch.setattr(projects_mod.pm, "chat", lambda *a, **k: ("here", [], proposal, None))
    out = pm_turn_mod.pm_chat(mem, "p1", "hello")
    assert out["charter_proposal"] == proposal  # surfaced to the client; never auto-written
    assert mem.get_charter("p1") is None  # the trusted row untouched (ADR-0047 §1)


def test_pm_chat_stores_a_clarification_only_on_under_specified_items(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "MOSAERA_PM_CHAT_TOOLS", "0"
    )  # pin the pre-ADR-0111 single-call arm this test mocks
    # ADR-0080 §1: Quincy's clarify fence is stored ON THE ITEM (survives reload), and ONLY
    # when the item is genuinely UNDER_SPECIFIED right now — a checkable item can't be nagged.
    import mosaera_api.pm_turn as pm_turn_mod
    import mosaera_api.projects as projects_mod

    mem: Any = _FakeProjectMemory()
    mem.create_project("p1", "P", "src")
    vague = mem.add_backlog_item("p1", "wiring", "", "everything wired up nicely", 0)
    crisp = mem.add_backlog_item("p1", "search", "", "prints every matching note", 1)
    monkeypatch.setattr(projects_mod, "get_chat_model", lambda *a, **k: object())

    def chat_with(iid: int):
        clar = {
            "item_id": iid,
            "claim_text": "everything wired up nicely",
            "why": "no observable behaviour",
            "proposals": ["search prints every matching note in id order; exits 0 on no match"],
        }
        return lambda *a, **k: ("here", [], None, clar)

    monkeypatch.setattr(projects_mod.pm, "chat", chat_with(vague))
    out = pm_turn_mod.pm_chat(mem, "p1", "make item 1 checkable?")
    assert out["clarified_item"] is not None
    stored = mem.item_clarification(vague)
    assert stored is not None and stored["status"] == "open"
    assert stored["proposals"][0].startswith("search prints")

    # A clarify fence pointed at a CHECKABLE item is ignored (stored nothing).
    monkeypatch.setattr(projects_mod.pm, "chat", chat_with(crisp))
    out2 = pm_turn_mod.pm_chat(mem, "p1", "clarify the crisp one?")
    assert out2["clarified_item"] is None
    assert mem.item_clarification(crisp) is None


def test_clarification_resolve_accept_rewrites_acceptance_via_the_validated_path() -> None:
    mem: Any = _FakeProjectMemory()
    mem.create_project("p1", "P", "src")
    iid = mem.add_backlog_item("p1", "wiring", "", "everything wired up nicely", 0)
    mem.set_item_clarification(
        iid,
        claim_text="everything wired up nicely",
        why_unbindable="no observable behaviour",
        proposals=["prints every matching note in id order; exits 0 on no match"],
        axis="checkability",
        proposal_kind="acceptance",
    )
    c = _client_with(mem)
    r = c.post(
        f"/api/projects/p1/backlog/{iid}/clarification/resolve",
        json={"accepted_proposal_index": 0},
    )
    assert r.status_code == 200
    row = r.json()
    assert row["acceptance"].startswith("prints every matching note")
    assert row["clarification"] is None  # ask closed
    assert row["checkability"] == "CHECKABLE"  # the verdict flipped — the flow's whole point
    # The exchange is RETAINED for the ledger (#63): ask + the operator's recorded answer.
    record = row["clarification_record"]
    assert record["status"] == "resolved"
    assert record["resolution"].startswith("prints every matching note")
    assert record["claim_text"] == "everything wired up nicely"
    # resolving again: no open ask -> 409
    r2 = c.post(f"/api/projects/p1/backlog/{iid}/clarification/resolve", json={"rejected": True})
    assert r2.status_code == 409


def test_termination_reason_names_the_mutation_residual() -> None:
    # ADR-0071 amendment (#60/#62): a vouched-but-mutation-blocked park reads as a priced
    # residual, not a generic oracle line.
    from mosaera_api.runner._terminal import _termination_reason

    final = {
        "gate_decision": {
            "reasons": ["oracle_unverified"],
            "oracle_vouched_by": "structural_claims:14-c2",
        },
        "tests_mutation_caught": False,
    }
    assert "surviving mutation" in _termination_reason(final)
    # without the vouch, the generic line stands
    final2 = {"gate_decision": {"reasons": ["oracle_unverified"]}}
    assert "no independent oracle" in _termination_reason(final2)


def test_open_clarification_blocks_launch_and_override_passes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # ADR-0080 §1: the not-runnable gate at the single launch choke point; override remains
    # the operator's explicit escape hatch (the soft-lock posture).
    mem: Any = _FakeProjectMemory()
    mem.create_project("p1", "P", "src")
    iid = mem.add_backlog_item("p1", "wiring", "", "everything wired up nicely", 0)
    mem.set_item_clarification(
        iid,
        claim_text="everything wired up nicely",
        why_unbindable="",
        proposals=["p"],
        axis="checkability",
        proposal_kind="acceptance",
    )
    c = _client_with(mem)
    r = c.post(f"/api/projects/p1/backlog/{iid}/run", json={})
    assert r.status_code == 409 and "open clarification" in r.json()["detail"]
    # resolving unblocks (accept the proposal, then the run proceeds past THIS gate)
    c.post(f"/api/projects/p1/backlog/{iid}/clarification/resolve", json={"rejected": True})
    r2 = c.post(f"/api/projects/p1/backlog/{iid}/run", json={})
    assert r2.status_code != 409 or "clarification" not in r2.json().get("detail", "")


def test_clarification_resolve_reject_clears_without_touching_acceptance() -> None:
    mem: Any = _FakeProjectMemory()
    mem.create_project("p1", "P", "src")
    iid = mem.add_backlog_item("p1", "wiring", "", "everything wired up nicely", 0)
    mem.set_item_clarification(
        iid,
        claim_text="x",
        why_unbindable="",
        proposals=["some proposal text"],
        axis="checkability",
        proposal_kind="acceptance",
    )
    c = _client_with(mem)
    r = c.post(f"/api/projects/p1/backlog/{iid}/clarification/resolve", json={"rejected": True})
    assert r.status_code == 200
    assert r.json()["acceptance"] == "everything wired up nicely"  # untouched
    assert mem.item_clarification(iid) is None


def test_decompose_synthesis_gets_charter_and_map(monkeypatch: pytest.MonkeyPatch) -> None:
    # run_decompose renders the trusted charter + hardened map into the synthesis call.
    import mosaera_api.projects as projects_mod

    mem: Any = _FakeProjectMemory()
    mem.create_project("p1", "P", "src")
    mem.update_project("p1", repo_overview="an overview")
    mem.upsert_charter("p1", goal="ship the MVP", constraints="stdlib", posture="business")
    mem.map_dims = {
        "p1": [
            {
                "dimension": "tests",
                "status": "finding",
                "observations": [{"provenance": "pytest.ini", "text": "suite in tests/"}],
            }
        ]
    }
    monkeypatch.setattr(projects_mod, "get_chat_model", lambda *a, **k: object())
    seen: dict[str, str] = {}

    def fake_synth(
        model: Any, msgs: Any, overview: Any, caps: Any, doctrine: Any, **kw: Any
    ) -> str:
        seen.update(kw)
        return "the brief"

    monkeypatch.setattr(projects_mod.pm, "synthesize_understanding", fake_synth)
    monkeypatch.setattr(projects_mod.pm, "decompose_brief", lambda *a, **k: [])
    projects_mod.run_decompose(mem, "p1")
    assert "ship the MVP" in seen.get("charter_block", "")
    assert "Project map" in seen.get("map_block", "") and "tests" in seen["map_block"]


def test_run_session_exposes_phase_and_started_at() -> None:
    from mosaera_api.runner import RunSession

    graph = _build_fake_graph()
    s = RunSession(
        "ph-1", graph, {"configurable": {"thread_id": "ph-1"}}, {"task": "x"}, auto_approve=True
    )
    s.start()
    for _ in range(200):
        if s.status in ("completed", "error"):
            break
        time.sleep(0.02)
    snap = s.snapshot()
    assert snap["started_at"] is not None
    assert snap["phase"] in ("plan", "gate", "deliver")  # advanced through the graph


def test_active_runs_include_phase_and_timing(client: TestClient) -> None:
    rid = client.post("/api/runs", json={"repo": "x", "task": "t"}).json()["run_id"]
    _wait_for(client, rid, "awaiting_approval")  # parked at the gate → active
    run = next(r for r in client.get("/api/runs").json()["runs"] if r["run_id"] == rid)
    assert run["started_at"] is not None
    assert run["phase"] == "plan" and "project_id" in run


def _session(
    run_id: str,
    auto: bool,
    max_iterations: int = 3,
    max_seconds: float | None = None,
    high_assurance: bool = False,
    budget: dict[str, float] | None = None,
    hard_budget: dict[str, float] | None = None,
    memory: Any = None,
    **signals: Any,
) -> Any:
    """RunSession over the policy-aware fake graph with per-test signals."""
    from mosaera_api.runner import RunSession

    return RunSession(
        run_id,
        _build_fake_graph(max_iterations=max_iterations),
        {"configurable": {"thread_id": run_id}},
        {"task": "x", **signals},
        auto_approve=auto,
        max_seconds=max_seconds,
        high_assurance=high_assurance,
        budget=budget,
        hard_budget=hard_budget,
        memory=memory,
    )


class _RecordingMem:
    """Records cancel_run + add_decision (the durable terminal signals); no-ops
    every other memory call."""

    def __init__(self) -> None:
        self.cancelled: list[str] = []
        self.decisions: list[tuple[str, str, str]] = []

    def cancel_run(self, run_id: str) -> None:
        self.cancelled.append(run_id)

    def add_decision(self, run_id: str, kind: str, content: str) -> None:
        self.decisions.append((run_id, kind, content))

    def __getattr__(self, _name: str) -> Any:
        return lambda *a, **k: None


def _settle(s: Any, statuses: tuple[str, ...] = ("completed", "error")) -> None:
    for _ in range(300):
        if s.status in statuses:
            return
        time.sleep(0.02)
    raise AssertionError(f"session stuck in {s.status}")


def test_run_session_auto_approve_no_human() -> None:
    # All-clear evidence (defaults): autonomous mode still delivers unattended.
    s = _session("auto-1", auto=True)
    s.start()
    _settle(s)
    assert s.status == "completed"  # never parked on awaiting_approval
    assert bool((s.final or {}).get("approved")) is True  # gate auto-approved


def test_run_session_empty_delivery_parks_even_when_all_clear() -> None:
    # All-clear evidence BUT an empty committed diff — the coder shipped nothing
    # (silent failure or already-satisfied). Autonomous must NOT auto-approve and
    # chain a no-op as "delivered"; it parks for a human to confirm.
    s = _session("empty-1", auto=True, diff="")
    s.start()
    for _ in range(200):
        if s.status == "awaiting_approval":
            break
        time.sleep(0.02)
    assert s.status == "awaiting_approval"  # parked, not auto-approved
    assert bool((s.final or {}).get("approved")) is not True


def test_termination_reason_names_the_already_satisfied_case() -> None:
    # #44 (ADR-0052 redesign): an already-satisfied run PARKS on oracle_unverified (a green-pre-impl
    # suite is not an independent oracle), but the honest reason must say so — not the generic
    # "the passing tests are the coder's own", which is inaccurate here (they're the Proctor's).
    from mosaera_api.runner._terminal import _termination_reason

    already_sat = {
        "approved": False,
        "already_satisfied": True,
        "gate_decision": {"reasons": ["reviewer_unknown", "oracle_unverified"]},
    }
    assert "already satisfied" in _termination_reason(already_sat)
    # Without the signal, the same reasons fall through to the generic oracle_unverified message.
    coder_own = {"approved": False, "gate_decision": {"reasons": ["oracle_unverified"]}}
    assert "coder's own" in _termination_reason(coder_own)


def _build_escalation_graph(captured: dict[str, Any], checkpointer: Any = None) -> Any:
    """Minimal graph that raises ONE escalation interrupt (action='escalation'),
    records the runner's resume value, and ends — to exercise RunSession's mode-gated
    _resolve_escalation (ADR-0012) without the full engine."""

    def esc_node(state: _State) -> dict[str, Any]:
        resume = interrupt(
            {
                "action": "escalation",
                "kind": "blocked",
                "reason": "cannot rename files",
                "iteration": 1,
            }
        )
        captured["resume"] = resume
        return {"approved": True}  # finalize cleanly once the escalation is resolved

    builder: StateGraph = StateGraph(_State)
    builder.add_node("esc", esc_node)
    builder.add_edge(START, "esc")
    builder.add_edge("esc", END)
    return builder.compile(checkpointer=checkpointer or InMemorySaver())


def test_escalation_autonomous_rescopes_non_blocking() -> None:
    # ADR-0012: in autonomous mode an agent escalation is resolved by Quincy re-scoping,
    # recorded and NON-BLOCKING — the run never parks for a human.
    from mosaera_api.runner import RunSession

    captured: dict[str, Any] = {}
    s = RunSession(
        "esc-auto",
        _build_escalation_graph(captured),
        {"configurable": {"thread_id": "esc-auto"}},
        {"task": "rename old.py"},
        auto_approve=True,
        mode="autonomous",
    )
    s.start()
    _settle(s)
    assert s.status == "completed"  # never parked
    assert s.pending_interrupt is None
    assert captured["resume"]["resolution"] == "rescope"  # Quincy re-scopes
    assert any(  # and it is auditable in the transcript
        e["type"] == "escalation" and e["data"].get("resolution") == "rescope"
        for e in s.transcript_events()
    )


def test_escalation_guided_parks_for_human() -> None:
    # In guided mode the escalation parks for a human, exactly like the delivery gate;
    # the human's feedback flows back to the graph as the re-scope.
    from mosaera_api.runner import RunSession

    captured: dict[str, Any] = {}
    s = RunSession(
        "esc-guided",
        _build_escalation_graph(captured),
        {"configurable": {"thread_id": "esc-guided"}},
        {"task": "rename old.py"},
        auto_approve=False,
        mode="guided",
    )
    s.start()
    _settle(s, statuses=("awaiting_approval",))
    assert s.status == "awaiting_approval"
    assert (s.pending_interrupt or {}).get("value", {}).get("action") == "escalation"
    s.approve(True, "update the test to the new contract")
    _settle(s)
    assert s.status == "completed"
    assert captured["resume"]["resolution"] == "human"
    assert captured["resume"]["feedback"] == "update the test to the new contract"


def test_escalation_high_assurance_parks_despite_auto_approve() -> None:
    # High-Assurance sets auto_approve=True but MUST still defer an escalation to a
    # human (mirrors the delivery gate's HA rule).
    from mosaera_api.runner import RunSession

    captured: dict[str, Any] = {}
    s = RunSession(
        "esc-ha",
        _build_escalation_graph(captured),
        {"configurable": {"thread_id": "esc-ha"}},
        {"task": "rename old.py"},
        auto_approve=True,
        high_assurance=True,
        mode="high_assurance",
    )
    s.start()
    _settle(s, statuses=("awaiting_approval",))
    assert s.status == "awaiting_approval"  # parks despite auto_approve
    s.approve(True, "")
    _settle(s)
    assert s.status == "completed"


def test_stale_dist_warning(tmp_path: Any, capsys: Any) -> None:
    import os

    from mosaera_api.app import _warn_if_stale_dist

    dist = tmp_path / "dist"
    src = tmp_path / "src"  # sibling of dist, as in apps/web
    dist.mkdir()
    src.mkdir()
    index = dist / "index.html"
    index.write_text("x", encoding="utf-8")
    (src / "App.tsx").write_text("y", encoding="utf-8")

    # Source newer than the build → warns.
    os.utime(index, (1000, 1000))
    os.utime(src / "App.tsx", (2000, 2000))
    _warn_if_stale_dist(dist, index)
    assert "OLDER than apps/web/src" in capsys.readouterr().out

    # Rebuilt (index newer) → silent.
    os.utime(index, (3000, 3000))
    _warn_if_stale_dist(dist, index)
    assert "OLDER" not in capsys.readouterr().out

    # No source dir (deployed wheel) → silent.
    _warn_if_stale_dist(tmp_path / "nope" / "dist", index)
    assert capsys.readouterr().out == ""


def test_double_approve_rejected_and_not_leaked_to_next_park() -> None:
    # The approve() TOCTOU: two concurrent approves at one park must resolve it
    # exactly once — the loser is rejected, and its decision NEVER leaks into a
    # later park (the actual bug). Driven at the RunSession invariant level.
    s = _session("race-1", auto=False)
    s._enter_awaiting({"id": "gate-1", "value": {"action": "deliver"}})
    assert s.status == "awaiting_approval"

    results: list[str] = []

    def call() -> None:
        try:
            s.approve(True)
            results.append("ok")
        except RuntimeError:
            results.append("rejected")

    threads = [threading.Thread(target=call) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == ["ok", "rejected"]  # exactly one wins
    assert s._resume.qsize() == 1  # only one decision queued
    assert s._awaiting_decision is False  # slot closed

    # Worker drains THIS park's single decision, then a SECOND park opens.
    # `authorize_tests` rides every resume (ADR-0087, #65) and is empty unless the operator
    # ticked a blocking test at an ESCALATION gate — the delivery gate never sets it.
    # `option_id` likewise rides every resume (ADR-0082 §5) and is None unless the operator
    # answered a gate that DECLARED its outcomes; it records what they believed they chose and
    # steers nothing.
    # `effect` is the gate's OWN computed verb for that option, resolved here from the same
    # offered set this call validates against — and unlike `option_id` it DOES steer, at the
    # supervise escalation (2026-08-21). Empty here because this park declared no outcomes, which
    # is the compatibility case: no option chosen, no effect, legacy routing unchanged.
    assert s._resume.get() == {
        "approve": True,
        "feedback": "",
        "authorize_tests": [],
        "option_id": None,
        "effect": "",
    }
    s.status = "running"
    s._enter_awaiting({"id": "gate-2", "value": {"action": "deliver"}})
    assert s._resume.empty()  # no stale decision leaked into the next park
    assert s._awaiting_decision is True


def test_high_assurance_parks_delivery_even_when_clear() -> None:
    # High Assurance auto-approves writes but ALWAYS parks the delivery gate for
    # a human — even on all-clear evidence autonomous would have delivered.
    s = _session("ha-1", auto=True, high_assurance=True)
    s.start()
    _settle(s, statuses=("awaiting_approval",))
    gd = (s.pending_interrupt or {}).get("value", {}).get("gate_decision", {})
    assert gd.get("reasons") == []  # clear — autonomous would have shipped
    # The informed human still signs it off.
    s.approve(True, "")
    _settle(s)
    assert s.status == "completed"
    assert bool((s.final or {}).get("approved")) is True


def test_run_budget_parks_then_approve_continues() -> None:
    # Spend already over a tiny token ceiling → the run parks for a human before
    # its first node; approving grants headroom and it runs to completion. Budget
    # is orthogonal to approval mode: even autonomous parks on a spend breach.
    from mosaera_core.cost import TokenUsage

    s = _session("budget-1", auto=True, budget={"tokens": 10})
    s.cost_meter.record("Coder", "m", TokenUsage(input_tokens=100))
    s.start()
    _settle(s, statuses=("awaiting_approval",))
    val = (s.pending_interrupt or {}).get("value", {})
    assert val.get("action") == "budget" and val.get("breach") == "tokens"
    assert val.get("cap") == 10 and val.get("spent") == 100
    s.approve(True, "")  # raise the ceiling, continue
    _settle(s)
    assert s.status == "completed"


def test_run_budget_deny_stops_the_run() -> None:
    from mosaera_core.cost import TokenUsage

    s = _session("budget-2", auto=True, budget={"tokens": 10})
    s.cost_meter.record("Coder", "m", TokenUsage(input_tokens=100))
    s.start()
    _settle(s, statuses=("awaiting_approval",))
    s.approve(False, "too expensive")  # decline to raise → stop with partial work
    _settle(s, statuses=("cancelled",))
    assert s.status == "cancelled"


def test_no_budget_ignores_spend() -> None:
    # No budget configured → spend never parks; the run behaves normally.
    from mosaera_core.cost import TokenUsage

    s = _session("budget-3", auto=True)  # budget=None
    s.cost_meter.record("Coder", "m", TokenUsage(input_tokens=10_000))
    s.start()
    _settle(s)
    assert s.status == "completed"


def test_hard_budget_cancels_without_reask() -> None:
    # P4: a crossed HARD ceiling cancels outright — never parks/asks — and writes a
    # durable terminal record (not stuck RUNNING).
    from mosaera_core.cost import TokenUsage

    mem = _RecordingMem()
    s = _session("hard-1", auto=True, hard_budget={"tokens": 10}, memory=mem)
    s.cost_meter.record("Coder", "m", TokenUsage(input_tokens=100))
    s.start()
    _settle(s, statuses=("cancelled",))
    assert s.status == "cancelled"
    assert s.pending_interrupt is None  # never parked for a human
    assert mem.cancelled == ["hard-1"]  # durable CANCELLED written
    # An honest capability_limit reason is persisted so the UI can distinguish this
    # automatic hard-cap stop from a user cancel (via CapabilityLimitNote).
    caps = [c for (_r, k, c) in mem.decisions if k == "capability_limit"]
    assert caps and "hard tokens budget ceiling" in caps[0]


def test_budget_deny_writes_terminal_record() -> None:
    # P4: denying a soft-budget park is terminal — the run row is CANCELLED durably,
    # not left RUNNING for the orphan sweep.
    from mosaera_core.cost import TokenUsage

    mem = _RecordingMem()
    s = _session("deny-term", auto=True, budget={"tokens": 10}, memory=mem)
    s.cost_meter.record("Coder", "m", TokenUsage(input_tokens=100))
    s.start()
    _settle(s, statuses=("awaiting_approval",))
    s.approve(False, "too expensive")
    _settle(s, statuses=("cancelled",))
    assert mem.cancelled == ["deny-term"]


def test_parked_run_persists_cost_for_restart_recovery() -> None:
    # A parked run's worker BLOCKS (never hits its terminal finally), so cost must be
    # persisted at park — otherwise a restart-rehydrated run reseeds from nothing and can
    # burn another full budget past a hard cap. Newest cost row wins on read.
    import json

    from mosaera_core.cost import TokenUsage

    mem = _RecordingMem()
    s = _session("cost-park", auto=True, budget={"tokens": 10}, memory=mem)
    s.cost_meter.record("Coder", "m", TokenUsage(input_tokens=100))
    s.start()
    _settle(s, statuses=("awaiting_approval",))
    costs = [c for (_r, k, c) in mem.decisions if k == "cost"]
    assert costs, "a parked run must durably persist its spend-so-far"
    assert json.loads(costs[-1])["total_tokens"] == 100


def test_budget_park_payload_carries_honest_context() -> None:
    # P4: the park prompt is honest — how many times already raised, elapsed, calls —
    # so a human isn't asked to blindly fund a loop.
    from mosaera_core.cost import TokenUsage

    s = _session("honest", auto=True, budget={"tokens": 10})
    s.cost_meter.record("Coder", "m", TokenUsage(input_tokens=100))
    s.start()
    _settle(s, statuses=("awaiting_approval",))
    val = (s.pending_interrupt or {}).get("value", {})
    assert val.get("raised_before") == 0  # not raised yet
    assert "elapsed_s" in val and "calls" in val


def test_parked_run_survives_restart_and_resumes(tmp_path: Any) -> None:
    # The crux of P1-2: a run parked at the gate whose checkpoint lives in a
    # DURABLE saver can be resumed by a FRESH RunSession — simulating an API
    # restart. A resume session streams None, so LangGraph replays to the
    # persisted interrupt; the human's later approval then delivers.
    from langgraph.checkpoint.sqlite import SqliteSaver
    from mosaera_api.runner import RunSession

    db = str(tmp_path / "cp.sqlite")
    cfg = {"configurable": {"thread_id": "restart-1"}}

    # Instance 1: run to the gate, then "crash" — drop the session unapproved.
    with SqliteSaver.from_conn_string(db) as saver1:
        saver1.setup()
        s1 = RunSession("restart-1", _build_fake_graph(checkpointer=saver1), cfg, {"task": "x"})
        s1.start()
        _settle(s1, statuses=("awaiting_approval",))
        assert s1.pending_interrupt is not None

    # Instance 2 (the "restart"): a NEW saver over the same file + a fresh graph +
    # the same thread_id, resumed with initial=None.
    with SqliteSaver.from_conn_string(db) as saver2:
        s2 = RunSession("restart-1", _build_fake_graph(checkpointer=saver2), cfg, None)
        s2.start()
        _settle(s2, statuses=("awaiting_approval",))
        assert s2.pending_interrupt is not None  # re-detected the persisted gate
        s2.approve(True, "")
        _settle(s2)
        assert s2.status == "completed"
        assert bool((s2.final or {}).get("approved")) is True


def test_autonomous_parks_on_failing_tests_then_human_overrides() -> None:
    s = _session("auto-park-1", auto=True, tests_passed=False)
    s.start()
    _settle(s, statuses=("awaiting_approval",))
    gd = (s.pending_interrupt or {}).get("value", {}).get("gate_decision", {})
    assert gd.get("reasons") == ["validation_failed"]
    # The informed human override delivers.
    s.approve(True, "shipping anyway — no test suite yet")
    _settle(s)
    assert s.status == "completed"
    assert bool((s.final or {}).get("approved")) is True
    assert (s.final or {}).get("gate_decision", {}).get("human_override") is True


def test_autonomous_auto_denies_on_request_changes_then_delivers() -> None:
    # Reviewer-only complaint → bounded revise loop, no human needed.
    s = _session(
        "auto-deny-1",
        auto=True,
        reviews=["VERDICT: REQUEST_CHANGES\nsplit the change", "VERDICT: APPROVE\nok now"],
    )
    s.start()
    _settle(s)
    assert s.status == "completed"
    final = s.final or {}
    assert bool(final.get("approved")) is True
    assert final.get("iteration") == 2  # looped exactly once
    assert any(str(f).startswith("autonomous:") for f in final.get("feedback", []))


def test_failing_test_self_heals_then_delivers() -> None:
    # First attempt fails; the fix node feeds the coder the failure; the second
    # attempt passes → autonomous delivers WITHOUT parking a human (P1-3).
    s = _fix_session("fix-heal-1", [False, True])
    s.start()
    _settle(s)
    assert s.status == "completed"
    final = s.final or {}
    assert bool(final.get("approved")) is True
    assert final.get("iteration") == 2  # one fix pass, then green


def test_persistent_test_failure_parks_at_budget() -> None:
    # Tests never pass: the fix loop exhausts the shared iteration budget, then
    # falls through to the gate which parks on validation_failed (honest handoff).
    s = _fix_session("fix-park-1", [False, False, False], max_iterations=2)
    s.start()
    _settle(s, statuses=("awaiting_approval",))
    gd = (s.pending_interrupt or {}).get("value", {}).get("gate_decision", {})
    assert "validation_failed" in gd.get("reasons", [])


def test_autonomous_parks_on_unavailable_validation() -> None:
    # The planner found no honest validation (tests_passed=None) → park.
    s = _session("auto-park-5", auto=True, tests_passed=None)
    s.start()
    _settle(s, statuses=("awaiting_approval",))
    gd = (s.pending_interrupt or {}).get("value", {}).get("gate_decision", {})
    assert gd.get("reasons") == ["validation_unavailable"]
    assert gd.get("tests_passed") is None


def test_autonomous_parks_on_findings() -> None:
    s = _session("auto-park-2", auto=True, findings=[{"scanner": "gitleaks", "rule": "aws-key"}])
    s.start()
    _settle(s, statuses=("awaiting_approval",))
    gd = (s.pending_interrupt or {}).get("value", {}).get("gate_decision", {})
    assert gd.get("reasons") == ["security_findings"]


def test_autonomous_delivers_on_unknown_verdict_when_validated() -> None:
    # ADR-0031: reviewer SILENCE (no parseable verdict) + passing DETERMINISTIC validation
    # (default tests_passed=True) DELIVERS autonomously instead of false-parking — the
    # reviewer is a veto, not a required sign-off. Previously this parked on silence, which
    # false-parked most correct local runs (the local reviewer often emits no verdict).
    # Parking on unknown still happens when validation FAILS (see the tests_passed=False /
    # None park tests) or on a real objection.
    s = _session("auto-deliver-unknown", auto=True, review="looks fine to me")
    s.start()
    _settle(s)  # reaches a terminal state rather than awaiting approval
    assert s.status == "completed"


def test_autonomous_parks_at_iteration_cap() -> None:
    # Persistent REQUEST_CHANGES with max_iterations=1: the deny-loop is
    # bounded — the run parks instead of finalizing unreviewed.
    s = _session("auto-park-4", auto=True, max_iterations=1, review="VERDICT: REQUEST_CHANGES\nno")
    s.start()
    _settle(s, statuses=("awaiting_approval",))
    gd = (s.pending_interrupt or {}).get("value", {}).get("gate_decision", {})
    assert gd.get("reasons") == ["reviewer_requested_changes", "iteration_limit"]


def _linear_graph(*nodes: tuple[str, Any]) -> Any:
    """Tiny linear graph from (name, fn) pairs — lifecycle tests need graphs
    whose node timing they control, not the gate."""
    builder: StateGraph = StateGraph(_State)
    prev = START
    for name, fn in nodes:
        builder.add_node(name, fn)
        builder.add_edge(prev, name)
        prev = name
    builder.add_edge(prev, END)
    return builder.compile(checkpointer=InMemorySaver())


def test_cancel_stops_worker_between_nodes() -> None:
    from mosaera_api.runner import RunSession

    reached = threading.Event()
    release = threading.Event()
    ran: list[str] = []

    def node_a(state: _State) -> dict[str, Any]:
        reached.set()
        release.wait(5)
        return {"plan": "a"}

    def node_b(state: _State) -> dict[str, Any]:
        ran.append("b")
        return {"approved": True}

    mem = _FakeProjectMemory()
    mem.create_project("p1", "P", "src")
    iid = mem.add_backlog_item("p1", "one", position=0)
    mem.update_backlog_item(iid, status="in_progress")
    s = RunSession(
        "cx-1",
        _linear_graph(("a", node_a), ("b", node_b)),
        {"configurable": {"thread_id": "cx-1"}},
        {"task": "x"},
        memory=mem,  # type: ignore[arg-type]
        item_id=iid,
    )
    s.start()
    assert reached.wait(5)
    s.cancel()  # arrives while node A is still executing
    assert s.status == "cancelling"
    release.set()
    assert s._thread is not None
    s._thread.join(5)
    assert not s._thread.is_alive()
    assert s.status == "cancelled"
    assert ran == []  # node B never started
    assert any(e[1] == "run.cancelled" for e in mem.audits)
    item = mem.get_backlog_item(iid)
    assert item is not None and item["status"] == "todo"
    assert mem.errored_runs == []  # cancelled is not an error


def test_cancel_while_parked_unblocks_worker() -> None:
    s = _session("cx-2", auto=False)  # human gate → parks at awaiting_approval
    s.start()
    _settle(s, statuses=("awaiting_approval",))
    s.cancel()
    assert s._thread is not None
    s._thread.join(5)
    assert not s._thread.is_alive()
    assert s.status == "cancelled"
    with pytest.raises(RuntimeError):
        s.approve(True)


def test_cancel_after_completion_stays_completed() -> None:
    # The honesty rule: a run that finished delivering is completed; a late
    # cancel must not rewrite history.
    s = _session("cx-3", auto=True)
    s.start()
    _settle(s)
    assert s.status == "completed"
    s.cancel()
    assert s.status == "completed"


def test_wall_clock_cap_errors_the_run() -> None:
    from mosaera_api.runner import RunSession

    ran: list[str] = []

    def slow(state: _State) -> dict[str, Any]:
        time.sleep(0.15)
        return {"plan": "slow"}

    def after(state: _State) -> dict[str, Any]:
        ran.append("after")
        return {"approved": True}

    mem = _FakeProjectMemory()
    mem.create_project("p1", "P", "src")
    iid = mem.add_backlog_item("p1", "one", position=0)
    mem.update_backlog_item(iid, status="in_progress")
    s = RunSession(
        "wc-1",
        _linear_graph(("slow", slow), ("after", after)),
        {"configurable": {"thread_id": "wc-1"}},
        {"task": "x"},
        memory=mem,  # type: ignore[arg-type]
        item_id=iid,
        max_seconds=0.05,
    )
    s.start()
    _settle(s, statuses=("error",))
    assert ran == []  # the cap stopped the run before the next node
    assert mem.errored_runs == ["wc-1"]  # durably finalized, not left RUNNING
    assert any(e[1] == "run.timeout" and "wall-clock cap" in e[2] for e in mem.audits)
    item = mem.get_backlog_item(iid)
    assert item is not None and item["status"] == "todo"


def test_wall_clock_cap_excludes_parked_time() -> None:
    # The cap bounds execution, not human deliberation: a run parked at the
    # gate past the cap still completes once approved.
    s = _session("wc-2", auto=False, max_seconds=0.2)
    s.start()
    _settle(s, statuses=("awaiting_approval",))
    time.sleep(0.4)  # a slow human, well past the cap
    s.approve(True, "")
    _settle(s)
    assert s.status == "completed"
    assert bool((s.final or {}).get("approved")) is True


def test_graph_exception_durably_finalizes_error() -> None:
    from mosaera_api.runner import RunSession

    def boom(state: _State) -> dict[str, Any]:
        raise RuntimeError("kaput")

    mem = _FakeProjectMemory()
    s = RunSession(
        "er-1",
        _linear_graph(("boom", boom)),
        {"configurable": {"thread_id": "er-1"}},
        {"task": "x"},
        memory=mem,  # type: ignore[arg-type]
    )
    s.start()
    _settle(s, statuses=("error",))
    assert mem.errored_runs == ["er-1"]
    assert any(e[1] == "run.error" for e in mem.audits)


def test_coder_activity_milestones_stream_as_activity_events() -> None:
    # A node emitting custom stream events (as the coder's tools do via
    # get_stream_writer) surfaces them as SSE "activity" milestones — the
    # implement node is no longer opaque. No raw tokens, just tool boundaries.
    from langgraph.config import get_stream_writer
    from mosaera_api.runner import RunSession

    def work(state: _State) -> dict[str, Any]:
        writer = get_stream_writer()
        writer({"activity": "file_read", "detail": "pages/index.html", "result": "42 lines"})
        writer({"activity": "file_written", "detail": "pages/index.html"})
        writer({"not_an_activity": True})  # ignored — wrong shape
        return {"approved": True, "plan": "done"}

    s = RunSession(
        "act-1",
        _linear_graph(("work", work)),
        {"configurable": {"thread_id": "act-1"}},
        {"task": "x"},
    )
    s.start()
    _settle(s)
    drained = list(s.events())  # replays the full event history (fan-out subscriber)
    acts = [e["data"] for e in drained if e["type"] == "activity"]
    assert any(a["kind"] == "file_read" and a["detail"] == "pages/index.html" for a in acts)
    assert any(a["kind"] == "file_written" for a in acts)
    # The tool's short result rides through so the transcript shows call → outcome.
    assert any(a.get("result") == "42 lines" for a in acts)
    # Every event carries a server timestamp (epoch ms) so the transcript can show
    # when each step happened and how long each agent worked — correct on replay too.
    assert all(isinstance(e["data"].get("ts"), int) for e in drained if isinstance(e["data"], dict))
    # Every activity is attributed to an owning node (empty namespace in this
    # single-node fake → the "implement" fallback) so the UI credits the right
    # actor (Forge vs Rook).
    assert all(a.get("node") for a in acts)
    assert acts[0]["node"] == "implement"
    # The malformed custom write never became an activity.
    assert all("not_an_activity" not in a for a in acts)


def test_backlog_run_race_reserves_exactly_once(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    # The reservation is taken (under the state lock) BEFORE the slow graph
    # build, so a second launch while the first is mid-build is rejected.
    # Deterministic, not a wall-clock race: the factory signals once run 1 has
    # reserved and blocks there, holding the mutex, while run 2 is fired.
    monkeypatch.setenv("MOSAERA_HOME", str(tmp_path))
    mem = _FakeProjectMemory()
    mem.create_project("p1", "P", "src")
    iid = mem.add_backlog_item("p1", "one", position=0)

    reserved = threading.Event()  # set once run 1 is past _reserve_project
    release = threading.Event()  # lets run 1's build finish

    def blocking_factory(
        req: RunSubmit, run_id: str
    ) -> tuple[Any, dict[str, Any], dict[str, Any], Any]:
        reserved.set()  # we are inside the factory → the reservation is held
        release.wait(5)
        return (
            _build_fake_graph(max_iterations=1),
            {"configurable": {"thread_id": run_id}},
            {"task": req.task},
            mem,
        )

    app = create_app(graph_factory=blocking_factory, memory=mem)  # type: ignore[arg-type]
    url = f"/api/projects/p1/backlog/{iid}/run"
    # Separate clients: Starlette's TestClient isn't safe for concurrent use on
    # one instance (a misrouted call would 405 on the SPA catch-all).
    first: dict[str, int] = {}
    t = threading.Thread(
        target=lambda: first.__setitem__("code", TestClient(app).post(url).status_code)
    )
    t.start()
    try:
        assert reserved.wait(5), "run 1 never reached the factory"
        # With run 1 holding the reservation, the second launch must be rejected.
        assert TestClient(app).post(url).status_code == 409
    finally:
        release.set()
        t.join(5)
    assert first.get("code") == 201


def test_finished_sessions_are_reaped_beyond_cap(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    monkeypatch.setenv("MOSAERA_HOME", str(tmp_path))
    monkeypatch.setattr("mosaera_api.app_context._sessions._MAX_SESSIONS", 3)
    c = TestClient(create_app(graph_factory=_fake_factory))
    rids: list[str] = []
    for i in range(5):
        rid = c.post("/api/runs", json={"repo": "x", "task": f"t{i}"}).json()["run_id"]
        _wait_for(c, rid, "awaiting_approval")
        c.post(f"/api/runs/{rid}/approve", json={"approve": True})
        _wait_for(c, rid, "completed")
        rids.append(rid)
    assert len(c.app.state.sessions) <= 3  # type: ignore[attr-defined]
    assert c.get(f"/api/runs/{rids[-1]}").status_code == 200  # newest retained
    assert c.get(f"/api/runs/{rids[0]}").status_code == 404  # oldest evicted


def test_incomplete_sessions_are_reaped(monkeypatch: pytest.MonkeyPatch) -> None:
    # Finding H-1: `incomplete` (the honest non-delivery outcome, ADR-0006) is a terminal status
    # and MUST be evictable — else a long autonomous stream of give-ups leaks sessions (each
    # pinning its full event history + a DB pool) past the cap forever. The old reap set omitted
    # it, so this would fail (0 evicted, len stays 5).
    from types import SimpleNamespace

    from mosaera_api.routes.context import AppContext

    monkeypatch.setattr("mosaera_api.app_context._sessions._MAX_SESSIONS", 3)
    ctx = AppContext(memory=None, graph_factory=None)
    for i in range(5):
        ctx.sessions[f"r{i}"] = SimpleNamespace(status="incomplete")  # type: ignore[assignment]
    ctx.reap_sessions()
    assert len(ctx.sessions) == 3  # oldest incomplete sessions evicted down to the cap
    assert "r0" not in ctx.sessions and "r4" in ctx.sessions  # oldest gone, newest kept


def _mem_factory(mem: Any, **signals: Any) -> Any:
    # **kw so an escalation re-run (which passes settings=) doesn't TypeError.
    def factory(
        req: RunSubmit, run_id: str, **kw: Any
    ) -> tuple[Any, dict[str, Any], dict[str, Any], Any]:
        return (
            _build_fake_graph(max_iterations=1),
            {"configurable": {"thread_id": run_id}},
            {"task": req.task, **signals},
            mem,
        )

    return factory


def test_autonomous_runs_backlog_and_stops(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    monkeypatch.setenv("MOSAERA_HOME", str(tmp_path))
    mem = _FakeProjectMemory()
    mem.create_project("p1", "P", "src", autonomous=True)
    mem.add_backlog_item("p1", "one", position=0)
    mem.add_backlog_item("p1", "two", position=1)
    c = TestClient(create_app(graph_factory=_mem_factory(mem), memory=mem))  # type: ignore[arg-type]

    assert c.post("/api/projects/p1/start").status_code == 202
    # It auto-approves + auto-queues: both items reach in_review with no HTTP approvals.
    for _ in range(300):
        if all(i["status"] == "in_review" for i in mem.list_backlog_items("p1")):
            break
        time.sleep(0.02)
    assert [i["status"] for i in mem.list_backlog_items("p1")] == ["in_review", "in_review"]


def test_autonomous_gate_park_pauses_chain_until_human(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    monkeypatch.setenv("MOSAERA_HOME", str(tmp_path))
    # Park-and-wait-for-a-human is the resilient_sweep=OFF behavior (ADR-0023): with it ON
    # (the default) a chained autonomous run defers instead of parking (tested separately).
    monkeypatch.setenv("MOSAERA_RESILIENT_SWEEP", "0")
    mem = _FakeProjectMemory()
    mem.create_project("p1", "P", "src", autonomous=True)
    i1 = mem.add_backlog_item("p1", "one", position=0)
    mem.add_backlog_item("p1", "two", position=1)
    # Every run in this project reports failing validation → the gate parks.
    c = TestClient(
        create_app(graph_factory=_mem_factory(mem, tests_passed=False), memory=mem)  # type: ignore[arg-type]
    )
    assert c.post("/api/projects/p1/start").status_code == 202

    # The first run parks at the gate instead of blindly delivering.
    run = None
    for _ in range(300):
        runs = c.get("/api/runs").json()["runs"]
        run = next((r for r in runs if r["status"] == "awaiting_approval"), None)
        if run:
            break
        time.sleep(0.02)
    assert run is not None, "autonomous run never parked"
    item1 = mem.get_backlog_item(i1)
    assert item1 is not None and item1["status"] == "in_progress"  # parked, not reset
    assert "awaiting gate approval" in mem.projects["p1"]["error"]
    # No blind auto approval row was written for the parked deliver gate.
    assert not any(a[1] == "deliver" and a[2] and a[3] == "auto" for a in mem.approvals)
    assert any(e[1] == "auto-park" and "validation_failed" in e[2] for e in mem.audits)

    # Informed human override → the item delivers and the chain resumes.
    assert c.post(f"/api/runs/{run['run_id']}/approve", json={"approve": True}).status_code == 200
    for _ in range(300):
        one = mem.get_backlog_item(i1)
        if one is not None and one["status"] == "in_review":
            break
        time.sleep(0.02)
    one = mem.get_backlog_item(i1)
    assert one is not None and one["status"] == "in_review"
    # The human approval row exists for the deliver gate.
    assert any(a[1] == "deliver" and a[2] for a in mem.approvals)
    # Chain resumed: the second item launches (and parks again on its own gate).
    for _ in range(300):
        runs = c.get("/api/runs").json()["runs"]
        if any(r["status"] == "awaiting_approval" and r["run_id"] != run["run_id"] for r in runs):
            break
        time.sleep(0.02)
    assert any(
        r["status"] == "awaiting_approval" and r["run_id"] != run["run_id"]
        for r in c.get("/api/runs").json()["runs"]
    )


def test_denied_item_run_returns_to_todo(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    monkeypatch.setenv("MOSAERA_HOME", str(tmp_path))
    mem = _FakeProjectMemory()
    mem.create_project("p1", "P", "src")
    iid = mem.add_backlog_item("p1", "one", position=0)
    c = TestClient(create_app(graph_factory=_mem_factory(mem), memory=mem))  # type: ignore[arg-type]
    rid = c.post(f"/api/projects/p1/backlog/{iid}/run").json()["run_id"]
    _wait_for(c, rid, "awaiting_approval")
    started = mem.get_backlog_item(iid)
    assert started is not None and started["status"] == "in_progress"
    c.post(f"/api/runs/{rid}/approve", json={"approve": False, "feedback": "no"})
    for _ in range(200):  # not approved → item recovers to todo, never stuck in_progress
        item = mem.get_backlog_item(iid)
        if item is not None and item["status"] == "todo":
            break
        time.sleep(0.02)
    final = mem.get_backlog_item(iid)
    assert final is not None and final["status"] == "todo"


def test_per_run_autonomous_mode_delivers_without_chaining(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    # Running ONE item in autonomous mode auto-approves it, but per-run auto
    # never chains — the second (todo) item stays untouched.
    monkeypatch.setenv("MOSAERA_HOME", str(tmp_path))
    mem = _FakeProjectMemory()
    mem.create_project("p1", "P", "src")  # project Autonomous flag OFF
    i1 = mem.add_backlog_item("p1", "one", position=0)
    i2 = mem.add_backlog_item("p1", "two", position=1)
    c = TestClient(create_app(graph_factory=_mem_factory(mem), memory=mem))  # type: ignore[arg-type]
    rid = c.post(f"/api/projects/p1/backlog/{i1}/run", json={"mode": "autonomous"}).json()["run_id"]
    for _ in range(300):
        one = mem.get_backlog_item(i1)
        if one is not None and one["status"] == "in_review":
            break
        time.sleep(0.02)
    assert c.get(f"/api/runs/{rid}").json()["status"] == "completed"  # no human needed
    assert mem.get_backlog_item(i1)["status"] == "in_review"  # type: ignore[index]
    assert mem.get_backlog_item(i2)["status"] == "todo"  # type: ignore[index]  # NOT chained


def test_per_run_high_assurance_parks_even_when_clear(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    monkeypatch.setenv("MOSAERA_HOME", str(tmp_path))
    mem = _FakeProjectMemory()
    mem.create_project("p1", "P", "src")
    iid = mem.add_backlog_item("p1", "one", position=0)
    c = TestClient(create_app(graph_factory=_mem_factory(mem), memory=mem))  # type: ignore[arg-type]
    rid = c.post(f"/api/projects/p1/backlog/{iid}/run", json={"mode": "high_assurance"}).json()[
        "run_id"
    ]
    # All-clear evidence, yet High Assurance always asks a human at delivery.
    _wait_for(c, rid, "awaiting_approval")
    gd = c.get(f"/api/runs/{rid}").json()["pending_interrupt"]["value"]["gate_decision"]
    assert gd["reasons"] == []


def test_cancel_run(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    # Cancel is real: the worker thread stops, the session stays visible with
    # an honest status, and the project mutex is freed by the worker itself.
    monkeypatch.setenv("MOSAERA_HOME", str(tmp_path))
    mem = _FakeProjectMemory()
    mem.create_project("p1", "P", "src")
    iid = mem.add_backlog_item("p1", "one", position=0)
    c = TestClient(create_app(graph_factory=_mem_factory(mem), memory=mem))  # type: ignore[arg-type]
    rid = c.post(f"/api/projects/p1/backlog/{iid}/run").json()["run_id"]
    _wait_for(c, rid, "awaiting_approval")
    assert c.post(f"/api/runs/{rid}/cancel").json() == {"cancelled": rid}
    assert mem.cancelled_runs == [rid]  # durable CANCELLED written immediately
    # The session is NOT dropped: it converges to "cancelled" (worker-owned).
    _wait_for(c, rid, "cancelled")
    item = mem.get_backlog_item(iid)
    assert item is not None and item["status"] == "todo"
    # The mutex was released by the worker's on_done — a new run launches.
    for _ in range(200):
        r = c.post(f"/api/projects/p1/backlog/{iid}/run")
        if r.status_code == 201:
            break
        assert r.status_code == 409  # honest busy while the worker winds down
        time.sleep(0.02)
    assert r.status_code == 201


def test_project_files_empty_without_clone(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    monkeypatch.setenv("MOSAERA_HOME", str(tmp_path))
    mem = _FakeProjectMemory()
    mem.create_project("p1", "P", "src")
    c = _client_with(mem)
    assert c.get("/api/projects/p1/files").json() == {"files": []}
    assert c.get("/api/projects/p1/patch").status_code == 404


def test_mr_status_flips_to_merged(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    monkeypatch.setenv("MOSAERA_HOME", str(tmp_path))
    monkeypatch.setenv("MOSAERA_GITLAB_TOKEN", "x")
    from mosaera_connectors import gitlab_client as glc

    monkeypatch.setattr(glc, "get_merge_request", lambda *a: ({"state": "merged"}, None))
    mem = _FakeProjectMemory()
    mem.create_project("p1", "P", "https://gitlab.rengifo.me/mosaera/site.git", gitlab_token="t")
    mem.update_project("p1", status="in_review", mr_url="https://gl/x/-/merge_requests/3")
    c = _client_with(mem)
    assert c.get("/api/projects/p1/mr-status").json()["state"] == "merged"
    assert mem.projects["p1"]["status"] == "merged"


def test_start_requires_autonomous(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    monkeypatch.setenv("MOSAERA_HOME", str(tmp_path))
    mem = _FakeProjectMemory()
    mem.create_project("p1", "P", "src")  # autonomous default off
    c = _client_with(mem)
    assert c.post("/api/projects/p1/start").status_code == 400
    assert c.post("/api/projects/p1/autonomous", json={"on": True}).json()["autonomous"] is True


def test_attachment_upload_lifecycle(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    from mosaera_api.processing import run_processing

    monkeypatch.setenv("MOSAERA_HOME", str(tmp_path))
    mem = _FakeProjectMemory()
    mem.create_project("p1", "P", "src")
    # Run the pipeline synchronously with a fake summarizer (no thread/model).
    monkeypatch.setattr(
        "mosaera_api.routes.messages.start_processing",
        lambda m, att_id: run_processing(
            m, att_id, tmp_path / "uploads", lambda name, text: "A brand notes file."
        ),
    )
    c = _client_with(mem)

    # Happy path: small markdown upload processes to ready with a summary.
    r = c.post(
        "/api/projects/p1/attachments",
        files={"file": ("notes.md", b"# Brand\nUse amber accents.", "text/markdown")},
        data={"scope": "project_context"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "ready" and body["scope"] == "project_context"
    assert body["token_estimate"] > 0
    assert body["summary"] == "A brand notes file."
    assert body["large"] is False
    # project_context + ready ⇒ registered in the context registry (guardrail 8).
    assert mem.list_project_context_items("p1")[0]["title"] == "notes.md"
    assert "storage_path" not in body and "sha256" not in body  # internals stay server-side
    att_id = body["id"]
    # The binary landed on disk under the uploads root, not in the DB record's public view.
    stored = list((tmp_path / "uploads").rglob("notes.md"))
    assert len(stored) == 1 and stored[0].read_text().startswith("# Brand")

    # Guardrail 2: browser MIME is ignored; the extension allowlist decides.
    bad = c.post(
        "/api/projects/p1/attachments",
        files={"file": ("evil.exe", b"MZ\x00binary", "text/plain")},
    )
    assert bad.status_code == 422 and "Unsupported" in bad.json()["detail"]
    binary = c.post(
        "/api/projects/p1/attachments",
        files={"file": ("data.txt", b"ok\x00then", "text/plain")},
    )
    assert binary.status_code == 422 and "binary" in binary.json()["detail"]
    huge = c.post(
        "/api/projects/p1/attachments",
        files={"file": ("big.txt", b"x" * (2 * 1024 * 1024 + 1), "text/plain")},
    )
    assert huge.status_code == 422 and "too large" in huge.json()["detail"].lower()
    assert (
        c.post(
            "/api/projects/p1/attachments",
            files={"file": ("a.md", b"hi", "text/plain")},
            data={"scope": "nonsense"},
        ).status_code
        == 400
    )

    # Dedup: identical content reuses the stored binary (still one file on disk).
    dup = c.post(
        "/api/projects/p1/attachments",
        files={"file": ("notes.md", b"# Brand\nUse amber accents.", "text/markdown")},
    )
    assert dup.status_code == 201
    assert len(list((tmp_path / "uploads").rglob("notes.md"))) == 1

    # List + soft delete (guardrail 5: link survives, list hides).
    assert len(c.get("/api/projects/p1/attachments").json()["attachments"]) == 2
    assert c.delete(f"/api/projects/p1/attachments/{att_id}").json() == {"deleted": att_id}
    remaining = c.get("/api/projects/p1/attachments").json()["attachments"]
    assert all(a["id"] != att_id for a in remaining)
    assert c.delete("/api/projects/p1/attachments/att-nope").status_code == 404


def test_scope_patch_and_delete_keep_context_in_sync(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    from mosaera_api.processing import run_processing

    monkeypatch.setenv("MOSAERA_HOME", str(tmp_path))
    mem = _FakeProjectMemory()
    mem.create_project("p1", "P", "src")
    monkeypatch.setattr(
        "mosaera_api.routes.messages.start_processing",
        lambda m, att_id: run_processing(
            m, att_id, tmp_path / "uploads", lambda n, t: "Notes summary."
        ),
    )
    c = _client_with(mem)
    att_id = c.post(
        "/api/projects/p1/attachments",
        files={"file": ("notes.md", b"note body", "text/markdown")},
    ).json()["id"]
    assert mem.list_project_context_items("p1") == []  # message_only

    # message_only -> project_context: registry entry appears (guardrail 8).
    r = c.patch(f"/api/projects/p1/attachments/{att_id}", json={"scope": "project_context"})
    assert r.status_code == 200 and r.json()["scope"] == "project_context"
    assert mem.list_project_context_items("p1")[0]["summary"] == "Notes summary."

    # project_context -> message_only: no stale context.
    c.patch(f"/api/projects/p1/attachments/{att_id}", json={"scope": "message_only"})
    assert mem.list_project_context_items("p1") == []

    # Back on, then delete: context disabled again.
    c.patch(f"/api/projects/p1/attachments/{att_id}", json={"scope": "project_context"})
    assert len(mem.list_project_context_items("p1")) == 1
    c.delete(f"/api/projects/p1/attachments/{att_id}")
    assert mem.list_project_context_items("p1") == []
    assert (
        c.patch(
            f"/api/projects/p1/attachments/{att_id}", json={"scope": "project_context"}
        ).status_code
        == 404
    )  # deleted attachments can't be patched
    assert (
        c.patch("/api/projects/p1/attachments/att-nope", json={"scope": "nonsense"}).status_code
        == 404
    )


def test_thumbnail_endpoint_guards(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    import io as _io

    from mosaera_api.processing import run_processing
    from PIL import Image

    monkeypatch.setenv("MOSAERA_HOME", str(tmp_path))
    mem = _FakeProjectMemory()
    mem.create_project("p1", "P", "src")
    monkeypatch.setattr(
        "mosaera_api.routes.messages.start_processing",
        lambda m, att_id: run_processing(m, att_id, tmp_path / "uploads", lambda n, t: ""),
    )
    c = _client_with(mem)
    buf = _io.BytesIO()
    Image.new("RGB", (300, 200), (16, 18, 22)).save(buf, "PNG")
    img_id = c.post(
        "/api/projects/p1/attachments",
        files={"file": ("shot.png", buf.getvalue(), "image/png")},
    ).json()["id"]
    txt_id = c.post(
        "/api/projects/p1/attachments",
        files={"file": ("a.md", b"text", "text/markdown")},
    ).json()["id"]

    ok = c.get(f"/api/projects/p1/attachments/{img_id}/thumbnail")
    assert ok.status_code == 200 and ok.headers["content-type"] == "image/png"
    assert len(ok.content) > 0
    # Full-size lightbox endpoint: same strictness, original bytes back.
    full = c.get(f"/api/projects/p1/attachments/{img_id}/image")
    assert full.status_code == 200 and full.headers["content-type"] == "image/png"
    assert len(full.content) > len(ok.content)  # original, not the thumbnail
    assert c.get(f"/api/projects/p1/attachments/{txt_id}/image").status_code == 404
    # /content: text files return extracted text as JSON (never executed HTML).
    content = c.get(f"/api/projects/p1/attachments/{txt_id}/content")
    assert content.status_code == 200 and content.json()["text"] == "text"
    assert c.get(f"/api/projects/p1/attachments/{img_id}/content").status_code == 404
    # /file: PDFs/images only — uploaded .html must NOT be servable inline (XSS).
    html_id = c.post(
        "/api/projects/p1/attachments",
        files={"file": ("page.html", b"<script>alert(1)</script>", "text/html")},
    ).json()["id"]
    assert c.get(f"/api/projects/p1/attachments/{html_id}/file").status_code == 404
    assert c.get(f"/api/projects/p1/attachments/{img_id}/file").status_code == 200
    # Guardrail 10: 404 for non-image, deleted, unknown.
    assert c.get(f"/api/projects/p1/attachments/{txt_id}/thumbnail").status_code == 404
    c.delete(f"/api/projects/p1/attachments/{img_id}")
    assert c.get(f"/api/projects/p1/attachments/{img_id}/thumbnail").status_code == 404
    assert c.get(f"/api/projects/p1/attachments/{img_id}/image").status_code == 404
    assert c.get(f"/api/projects/p1/attachments/{img_id}/file").status_code == 404
    assert c.get("/api/projects/p1/attachments/att-nope/thumbnail").status_code == 404


def test_message_attachment_guardrails(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    monkeypatch.setenv("MOSAERA_HOME", str(tmp_path))
    captured: dict[str, Any] = {}

    def fake_pm_chat(
        mem: Any, pid: str, text: str, attachment_ids: Any = None, session_id: Any = None
    ) -> dict[str, Any]:
        captured["ids"] = attachment_ids
        return {"reply": "ok", "changeset": []}

    monkeypatch.setattr("mosaera_api.routes.messages.pm_chat", fake_pm_chat)
    mem = _FakeProjectMemory()
    mem.create_project("p1", "P", "src")
    mem.add_attachment(
        "att-ok",
        "p1",
        filename="a.md",
        mime_type="text/markdown",
        size_bytes=2,
        sha256="x",
        storage_path="p",
        status="ready",
        token_estimate=1,
        scope="message_only",
    )
    mem.add_attachment(
        "att-failed",
        "p1",
        filename="b.md",
        mime_type="text/markdown",
        size_bytes=2,
        sha256="y",
        storage_path="p",
        status="failed",
        token_estimate=0,
        scope="message_only",
    )
    mem.add_attachment(
        "att-gone",
        "p1",
        filename="c.md",
        mime_type="text/markdown",
        size_bytes=2,
        sha256="z",
        storage_path="p",
        status="ready",
        token_estimate=1,
        scope="message_only",
    )
    mem.soft_delete_attachment("att-gone")
    c = _client_with(mem)

    # Guardrail 3: ready + non-deleted links fine.
    ok = c.post(
        "/api/projects/p1/messages",
        json={"text": "use it", "attachments": [{"attachment_id": "att-ok"}]},
    )
    assert ok.status_code == 200 and captured["ids"] == ["att-ok"]

    # Guardrail 4: failed / deleted / foreign attachments are rejected.
    for bad_id in ("att-failed", "att-gone", "att-other-project"):
        r = c.post(
            "/api/projects/p1/messages",
            json={"text": "x", "attachments": [{"attachment_id": bad_id}]},
        )
        assert r.status_code == 422, bad_id

    # A file alone is a valid message; a fully empty send is not.
    blank_with_file = c.post(
        "/api/projects/p1/messages",
        json={"text": "", "attachments": [{"attachment_id": "att-ok"}]},
    )
    assert blank_with_file.status_code == 200 and captured["ids"] == ["att-ok"]
    assert c.post("/api/projects/p1/messages", json={"text": "  "}).status_code == 422


def test_pm_reply_records_used_context(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    """MR 4D: the reply's context sources come from real builder metadata."""
    from mosaera_api import projects as projects_mod
    from mosaera_api.processing import run_processing

    monkeypatch.setenv("MOSAERA_HOME", str(tmp_path))
    monkeypatch.setattr(projects_mod.pm, "chat", lambda *a, **k: ("the reply", [], None, None))
    monkeypatch.setattr(projects_mod, "get_chat_model", lambda *a, **k: object())
    mem = _FakeProjectMemory()
    mem.create_project("p1", "P", "src")
    mem.update_project("p1", brief="## brief")
    monkeypatch.setattr(
        "mosaera_api.routes.messages.start_processing",
        lambda m, att_id: run_processing(m, att_id, tmp_path / "uploads", lambda n, t: "Notes."),
    )
    c = _client_with(mem)
    att_id = c.post(
        "/api/projects/p1/attachments",
        files={"file": ("guide.md", b"amber rules", "text/markdown")},
    ).json()["id"]
    r = c.post(
        "/api/projects/p1/messages",
        json={"text": "use the guide", "attachments": [{"attachment_id": att_id}]},
    )
    assert r.status_code == 200, r.text
    # The PM reply carries its sources: brief + the attachment, honest mode.
    messages = c.get("/api/projects/p1/messages").json()["messages"]
    pm_msg = messages[-1]
    assert pm_msg["role"] == "pm"
    types = {s["source_type"]: s for s in pm_msg["context_sources"]}
    assert "brief" in types
    att_src = types["attachment"]
    assert att_src["title"] == "guide.md" and att_src["source_id"] == att_id
    assert att_src["included_as"] == "included_raw"  # tiny file fits raw
    # The user message has no sources.
    assert messages[-2]["role"] == "user" and messages[-2]["context_sources"] == []


def test_pm_chat_endpoint(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    monkeypatch.setenv("MOSAERA_HOME", str(tmp_path))
    monkeypatch.setattr(
        "mosaera_api.routes.messages.pm_chat",
        lambda mem, pid, text, attachment_ids=None, session_id=None: {
            "reply": "ok",
            "changeset": [{"op": "add", "title": "X", "why": "needed"}],
        },
    )
    mem = _FakeProjectMemory()
    mem.create_project("p1", "P", "src")
    c = _client_with(mem)
    r = c.post("/api/projects/p1/messages", json={"text": "what's next?"})
    assert r.status_code == 200 and r.json()["reply"] == "ok"
    assert r.json()["changeset"][0]["op"] == "add"
    assert c.post("/api/projects/nope/messages", json={"text": "hi"}).status_code == 404
    assert c.get("/api/projects/p1/messages").json() == {"messages": []}


def test_internal_backlog_conforms_to_provider() -> None:
    from mosaera_api.backlog import InternalBacklog
    from mosaera_connectors import BacklogProvider

    mem = _FakeProjectMemory()
    mem.create_project("p1", "P", "src")
    provider = InternalBacklog(mem)  # type: ignore[arg-type]
    assert isinstance(provider, BacklogProvider)
    iid = provider.add_item("p1", "t", "d", "a", 0)
    assert provider.list_items("p1")[0]["title"] == "t"
    provider.update_item(iid, status="done")
    assert _status(mem, iid) == "done"  # type: ignore[index]


def test_events_ends_when_terminal_and_drained() -> None:
    # A finished run whose events were already consumed must not hang the SSE
    # stream (which would block server shutdown).
    from mosaera_api.runner import RunSession

    session = RunSession("r", graph=None, config={}, initial={})
    session.status = "completed"
    assert list(session.events()) == []


def test_events_fan_out_to_multiple_subscribers() -> None:
    # P5: two viewers of one run each get the FULL stream — a single shared queue
    # (the old behaviour) would split the events across them, leaving one short.
    from mosaera_api.runner import RunSession

    s = RunSession("sse", graph=None, config={}, initial={})
    s._emit("update", {"n": 1})
    s._emit("update", {"n": 2})
    s.status = "completed"  # so each events() replays the backlog and returns
    first = [e["data"]["n"] for e in s.events()]
    second = [e["data"]["n"] for e in s.events()]
    assert first == [1, 2] and second == [1, 2]  # both saw everything


def test_aevents_replays_and_fans_out_like_events() -> None:
    # MR-B: the SSE endpoint uses the ASYNC aevents() (no anyio threadpool token pinned per
    # connection). It must keep events()' replay-then-live, fan-out semantics.
    import asyncio

    from mosaera_api.runner import RunSession

    s = RunSession("asse", graph=None, config={}, initial={})
    s._emit("update", {"n": 1})
    s._emit("update", {"n": 2})
    s.status = "completed"  # each aevents() replays the backlog and returns

    async def drain() -> list[int]:
        return [e["data"]["n"] async for e in s.aevents()]

    assert asyncio.run(drain()) == [1, 2]
    assert asyncio.run(drain()) == [1, 2]  # a second async subscriber also saw everything


def test_aevents_ends_when_terminal_and_drained() -> None:
    # A finished run with nothing queued must not hang the async SSE stream.
    import asyncio

    from mosaera_api.runner import RunSession

    s = RunSession("ar", graph=None, config={}, initial={})
    s.status = "completed"

    async def drain() -> list[dict[str, Any]]:
        return [e async for e in s.aevents()]

    assert asyncio.run(drain()) == []


def test_aevents_does_not_drop_terminal_event_emitted_after_status() -> None:
    # Regression: the worker flips status terminal BEFORE emitting the final done/_end events, so
    # aevents must NOT bail on terminal+empty before they land (dropping done → the client
    # reconnects + duplicates the transcript). The terminal events must be emitted CONCURRENTLY,
    # while the generator is already parked INSIDE its terminal grace-poll (having observed
    # terminal+empty) — otherwise get_nowait returns them before the grace branch is ever hit and
    # the test can't tell the fix from a bare `return` (it would pass on a reverted fix).
    import asyncio

    from mosaera_api.runner import RunSession

    s = RunSession("arace", graph=None, config={}, initial={})
    s._emit("update", {"n": 1})
    s.status = "completed"  # terminal BEFORE the done/_end events (mirrors the real worker order)

    async def _emit_terminal_after(delay: float) -> None:
        await asyncio.sleep(delay)  # let the generator reach the terminal grace-poll first
        s._emit("done", {"ok": True})
        s._emit("_end", {})

    async def drive() -> list[str]:
        gen = s.aevents()
        got: list[str] = [(await gen.__anext__())["type"]]  # the backlog 'update'
        # Now the generator's next step hits terminal+empty and enters the grace sleep. Fire the
        # terminal events from a CONCURRENT task during that window.
        emitter = asyncio.create_task(_emit_terminal_after(0.05))
        async for e in gen:
            got.append(e["type"])
        await emitter
        return got

    delivered = asyncio.run(drive())
    assert "done" in delivered  # the terminal event was NOT dropped by an early terminal return


def test_reasoning_of_surfaces_thinking_and_skips_pure_tool_calls() -> None:
    # MR-B: what the transcript shows as an agent's "thinking" for one turn.
    from langchain_core.messages import AIMessage
    from mosaera_agents.messages import reasoning_of

    # Plain narration.
    assert (
        reasoning_of(AIMessage(content="I'll read the config first."))
        == "I'll read the config first."
    )
    # A reasoning content block + a narration text block — both surface.
    blocks = AIMessage(
        content=[
            {"type": "reasoning", "reasoning": "the footer needs a nav"},
            {"type": "text", "text": "adding it now"},
        ]
    )
    out = reasoning_of(blocks)
    assert "the footer needs a nav" in out and "adding it now" in out
    # Provider CoT via additional_kwargs.reasoning_content (Ollama / deepseek-r1).
    cot = AIMessage(content="", additional_kwargs={"reasoning_content": "deep thought"})
    assert reasoning_of(cot) == "deep thought"
    # A pure tool-call turn with no text → nothing to show (no empty thought bubble).
    tc = AIMessage(content="", tool_calls=[{"name": "read_file", "args": {"path": "x"}, "id": "1"}])
    assert reasoning_of(tc) == ""


def test_reasoning_callback_emits_one_block_per_turn_attributed_to_node() -> None:
    # One emit per model turn, attributed to the owning node; empties skipped; a
    # subgraph call attributes to its outer node via the checkpoint namespace.
    from langchain_core.messages import AIMessage
    from langchain_core.outputs import ChatGeneration, LLMResult
    from mosaera_api.reasoning import ReasoningCallback

    seen: list[tuple[str | None, str]] = []
    cb = ReasoningCallback(lambda node, text: seen.append((node, text)))

    def turn(run_id: str, message: AIMessage, metadata: dict[str, str]) -> None:
        cb.on_chat_model_start({}, [], run_id=run_id, metadata=metadata)
        cb.on_llm_end(LLMResult(generations=[[ChatGeneration(message=message)]]), run_id=run_id)

    turn("r1", AIMessage(content="planning the edit"), {"langgraph_node": "implement"})
    turn("r2", AIMessage(content=""), {"langgraph_node": "implement"})  # empty → skipped
    # Reviewer subgraph call: checkpoint ns outermost segment wins over inner node.
    turn(
        "r3", AIMessage(content="looks correct"), {"langgraph_checkpoint_ns": "review:abc|inner:1"}
    )

    assert seen == [("implement", "planning the edit"), ("review", "looks correct")]


def test_run_session_attaches_reasoning_callback_only_when_enabled(monkeypatch) -> None:
    # The reasoning stream is on by default and fully disabled by the env flag.
    from mosaera_api.reasoning import ReasoningCallback
    from mosaera_api.runner import RunSession

    monkeypatch.delenv("MOSAERA_STREAM_REASONING", raising=False)  # default → on
    on = RunSession("t-on", graph=None, config={}, initial={})
    assert any(isinstance(c, ReasoningCallback) for c in on._config["callbacks"])

    monkeypatch.setenv("MOSAERA_STREAM_REASONING", "0")
    off = RunSession("t-off", graph=None, config={}, initial={})
    assert not any(isinstance(c, ReasoningCallback) for c in off._config["callbacks"])


def test_termination_reason_prefers_stall_then_gate_reasons() -> None:
    from mosaera_api.runner import _termination_reason

    # The no-progress breaker's own message wins.
    assert (
        _termination_reason({"stalled": True, "stall_reason": "validation failed the same way"})
        == "validation failed the same way"
    )
    # Else derive from the gate's evidence reasons.
    assert (
        _termination_reason({"gate_decision": {"reasons": ["iteration_limit"]}})
        == "reached the iteration limit without meeting acceptance"
    )
    assert _termination_reason({"gate_decision": {"reasons": ["validation_failed"]}}) == (
        "validation kept failing"
    )
    assert "reviewer" in _termination_reason(
        {"gate_decision": {"reasons": ["reviewer_requested_changes"]}}
    )
    # Nothing specific → an honest generic fallback (never empty).
    assert _termination_reason({}) == "ended without meeting the acceptance criteria"


def test_run_ends_incomplete_when_it_did_not_deliver() -> None:
    # The core honesty fix: a run that reaches END without an approved delivery is
    # "incomplete" (+ reason), not "completed", and its item goes back to todo.
    from mosaera_api.runner import RunSession

    def gave_up(state: _State) -> dict[str, Any]:
        return {"approved": False, "gate_decision": {"reasons": ["iteration_limit"]}}

    mem = _FakeProjectMemory()
    mem.create_project("p1", "P", "src")
    iid = mem.add_backlog_item("p1", "one", position=0)
    mem.update_backlog_item(iid, status="in_progress")
    s = RunSession(
        "inc-1",
        _linear_graph(("g", gave_up)),
        {"configurable": {"thread_id": "inc-1"}},
        {"task": "x"},
        memory=mem,  # type: ignore[arg-type]
        item_id=iid,
    )
    s.start()
    assert s._thread is not None
    s._thread.join(5)
    assert s.status == "incomplete"
    assert s.termination_reason == "reached the iteration limit without meeting acceptance"
    assert s.snapshot()["termination_reason"] == s.termination_reason
    item = mem.get_backlog_item(iid)
    assert item is not None and item["status"] == "todo"  # not in_review


def test_run_completes_when_delivered() -> None:
    from mosaera_api.runner import RunSession

    def delivered(state: _State) -> dict[str, Any]:
        return {"approved": True}

    s = RunSession(
        "ok-1",
        _linear_graph(("g", delivered)),
        {"configurable": {"thread_id": "ok-1"}},
        {"task": "x"},
    )
    s.start()
    assert s._thread is not None
    s._thread.join(5)
    assert s.status == "completed"
    assert s.termination_reason is None
    assert s.snapshot()["termination_reason"] is None


def test_transcript_events_exclude_control_and_render_markdown() -> None:
    from mosaera_api.routes.runs import _transcript_markdown
    from mosaera_api.runner import RunSession

    s = RunSession("t-1", graph=None, config={}, initial={"task": "add hero"})
    s._emit("thought", {"node": "plan", "text": "thinking about the hero"})
    s._emit(
        "activity",
        {"kind": "file_written", "detail": "index.html", "result": "42 chars", "node": "implement"},
    )
    s._emit("update", {"node": "plan", "update": {"plan": "1. hero"}})
    s._emit("done", s.snapshot())  # lifecycle event — excluded from the transcript
    events = s.transcript_events()
    assert [e["type"] for e in events] == ["thought", "activity", "update"]
    assert events[0]["node"] == "plan" and events[1]["data"]["result"] == "42 chars"
    assert [e["seq"] for e in events] == [1, 2, 3]

    md = _transcript_markdown(
        {
            "run_id": "t-1",
            "status": "incomplete",
            "termination_reason": "no progress",
            "task": "add hero",
        },
        events,
    )
    assert "# Run transcript — t-1" in md
    assert "**Status:** incomplete — no progress" in md
    assert "file written index.html → 42 chars" in md
    assert "> [plan] thinking about the hero" in md


def test_transcript_route_serves_json_and_markdown(client: TestClient) -> None:
    run_id = client.post("/api/runs", json={"repo": "x", "task": "do a thing"}).json()["run_id"]
    _wait_for(client, run_id, "awaiting_approval")  # parked → still live in-process
    body = client.get(f"/api/runs/{run_id}/transcript").json()
    assert body["run_id"] == run_id
    assert isinstance(body["events"], list) and body["events"]  # ≥ the plan update
    md = client.get(f"/api/runs/{run_id}/transcript", params={"format": "md"})
    assert md.status_code == 200
    assert "text/markdown" in md.headers["content-type"]
    assert md.text.startswith("# Run transcript")
    # unknown run → 404
    assert client.get("/api/runs/nope/transcript").status_code == 404


def test_rehydrate_posture_derives_autonomous_and_title() -> None:
    # P5: a restarted run's posture comes from the project's Autonomous flag (the
    # per-run mode isn't persisted); item title is looked up for the pause note.
    from mosaera_api.app_context._rehydrate import _rehydrate_posture

    proj = {"autonomous": True, "backlog": [{"id": 7, "title": "Add a footer"}]}
    assert _rehydrate_posture(proj, 7, "task text") == (True, "Add a footer")
    # Non-autonomous project → guided; falls back to the task's first line for a title.
    assert _rehydrate_posture({"autonomous": False, "backlog": []}, 7, "Do the thing\nmore") == (
        False,
        "Do the thing",
    )
    # No project (ad-hoc run) → guided.
    assert _rehydrate_posture(None, None, "x")[0] is False


def test_rehydrate_threads_autonomous_into_the_graph_rebuild(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    # #52 red-team (HIGH): a restarted AUTONOMOUS run must REBUILD with the oracle posture — the
    # RunSubmit must carry autonomous=True, else _verify_overlay strips the oracle (tester +
    # coverage + mutation) and a run that PARKED on the oracle can rebuild oracle-less and
    # auto-approve-ship on restart. Capture the req the graph factory receives.
    from types import SimpleNamespace

    import mosaera_api.app_context._rehydrate as rehy
    from mosaera_api.app_context._rehydrate import RehydrateMixin

    monkeypatch.setenv("MOSAERA_HOME", str(tmp_path))
    captured: dict[str, object] = {}

    def fake_factory(req: Any, *a: Any, **k: Any) -> Any:
        captured["autonomous"] = req.autonomous
        return object(), {}, None, None

    class FakeSession:
        status = "completed"
        final: dict[str, object] = {}  # noqa: RUF012 — a throwaway test fake, never mutated

        def __init__(self, *a: Any, **k: Any) -> None:
            pass

        def start(self) -> None:
            pass

    monkeypatch.setattr("mosaera_api.factory.default_graph_factory", fake_factory)
    monkeypatch.setattr(rehy, "RunSession", FakeSession)

    ctx = SimpleNamespace(
        history=SimpleNamespace(project_detail=lambda pid: {"autonomous": True, "backlog": []}),
        checkpointer=object(),
        reserve_project=lambda pid: None,
        release_project=lambda pid: None,
        register_session=lambda rid, s: None,
    )
    detail = {"project_id": "p1", "task": "t", "source": "r"}
    RehydrateMixin.rehydrate(ctx, "run-1", detail)  # type: ignore[arg-type]
    assert captured["autonomous"] is True  # the posture-carrying flag reached the rebuild


def test_healthz(client: TestClient) -> None:
    # /healthz now reports the durable-memory state rather than a bare literal (ADR-0035):
    # it used to answer "ok" with a dead database behind it. No DB configured here → the
    # honest answer is ok/none, not ok/postgres.
    assert client.get("/healthz").json() == {"status": "ok", "memory": "none"}


def test_submit_setup_error_returns_400() -> None:
    def boom(req: RunSubmit, run_id: str) -> Any:
        raise ValueError("repo could not be cloned")

    c = TestClient(create_app(graph_factory=boom))
    r = c.post("/api/runs", json={"repo": "bad", "task": "t"})
    assert r.status_code == 400
    assert "repo could not be cloned" in r.json()["detail"]


def test_submit_sandbox_unavailable_returns_503() -> None:
    from mosaera_core.sandbox import SandboxUnavailable

    def no_sandbox(req: RunSubmit, run_id: str) -> Any:
        raise SandboxUnavailable("docker daemon not reachable")

    c = TestClient(create_app(graph_factory=no_sandbox))
    r = c.post("/api/runs", json={"repo": "x", "task": "t"})
    assert r.status_code == 503


def test_history_empty_without_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MOSAERA_DB_URL", raising=False)
    c = TestClient(create_app(graph_factory=_fake_factory))
    assert c.get("/api/history").json() == {"runs": []}
    assert c.get("/api/history/anything").status_code == 404


def test_history_with_memory() -> None:
    app = create_app(graph_factory=_fake_factory, memory=_FakeMemory())  # type: ignore[arg-type]
    c = TestClient(app)
    runs = c.get("/api/history").json()["runs"]
    assert runs[0]["id"] == "r1"
    detail = c.get("/api/history/r1").json()
    assert detail["decisions"][0]["kind"] == "plan"
    assert c.get("/api/history/nope").status_code == 404


def test_unknown_run_404(client: TestClient) -> None:
    assert client.get("/api/runs/nope").status_code == 404
    assert client.post("/api/runs/nope/approve", json={"approve": True}).status_code == 404


def test_submit_pauses_at_gate_then_approves(client: TestClient) -> None:
    resp = client.post("/api/runs", json={"repo": "x", "task": "fix it"})
    assert resp.status_code == 201
    run_id = resp.json()["run_id"]

    snap = _wait_for(client, run_id, "awaiting_approval")
    assert snap["pending_interrupt"]["value"]["action"] == "deliver"

    approve = client.post(f"/api/runs/{run_id}/approve", json={"approve": True})
    assert approve.status_code == 200

    done = _wait_for(client, run_id, "completed")
    assert done["approved"] is True
    assert done["commit_sha"] == "deadbeef"


def test_deny_ends_incomplete_not_approved(client: TestClient) -> None:
    # A run that exhausts its attempts without an approved delivery is honestly
    # "incomplete" (not dressed up as "completed") and surfaces why.
    run_id = client.post("/api/runs", json={"repo": "x", "task": "t"}).json()["run_id"]
    _wait_for(client, run_id, "awaiting_approval")
    client.post(f"/api/runs/{run_id}/approve", json={"approve": False, "feedback": "no"})
    done = _wait_for(client, run_id, "incomplete")
    assert done["approved"] is False
    assert done["commit_sha"] == ""
    assert done["termination_reason"]  # non-empty, honest reason


def test_approve_when_not_awaiting_conflicts(client: TestClient) -> None:
    run_id = client.post("/api/runs", json={"repo": "x", "task": "t"}).json()["run_id"]
    _wait_for(client, run_id, "awaiting_approval")
    client.post(f"/api/runs/{run_id}/approve", json={"approve": True})
    _wait_for(client, run_id, "completed")
    # A second approval after completion is a 409.
    assert client.post(f"/api/runs/{run_id}/approve", json={"approve": True}).status_code == 409


def test_events_stream_reaches_done(client: TestClient) -> None:
    run_id = client.post("/api/runs", json={"repo": "x", "task": "t"}).json()["run_id"]
    _wait_for(client, run_id, "awaiting_approval")
    client.post(f"/api/runs/{run_id}/approve", json={"approve": True})
    with client.stream("GET", f"/api/runs/{run_id}/events") as stream:
        body = "".join(chunk for chunk in stream.iter_text())
    assert "event: update" in body
    assert "event: done" in body


def test_spa_catch_all_confines_to_dist(tmp_path: Any) -> None:
    # The SPA fallback must serve files only from inside dist — a `..` traversal
    # (encoded so the client can't normalize it away) falls back to index.html,
    # never a file outside the bundle.
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>app</title>", encoding="utf-8")
    (dist / "app.js").write_text("console.log('ok')", encoding="utf-8")
    secret = tmp_path / "secret.txt"
    secret.write_text("TOP SECRET", encoding="utf-8")

    c = TestClient(create_app(web_dist=dist))
    # A real file inside dist is served.
    assert c.get("/app.js").text == "console.log('ok')"
    # A client-side route falls back to index.
    assert "<title>app</title>" in c.get("/projects/p1/overview").text
    # Encoded traversal cannot escape dist — it gets index.html, not the secret.
    resp = c.get("/%2e%2e%2fsecret.txt")
    assert "TOP SECRET" not in resp.text
    assert "<title>app</title>" in resp.text


def test_pricing_get_default_and_put_localhost_gated(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    monkeypatch.setenv("MOSAERA_HOME", str(tmp_path))
    monkeypatch.delenv("MOSAERA_MODEL_PRICES", raising=False)
    # No prices configured yet → empty table.
    assert client.get("/api/pricing").json() == {"prices": {}}
    # Config mutation is localhost-only; TestClient's host is not localhost.
    body = {"prices": {"claude-sonnet-5": {"input": 3.0, "output": 15.0}}}
    assert client.put("/api/pricing", json=body).status_code == 403
    # With the override flag it persists and reads back.
    monkeypatch.setenv("MOSAERA_ALLOW_REMOTE_CONFIG", "1")
    saved = client.put("/api/pricing", json=body).json()
    # None, not 0 — zero would price every cache hit as free (see test_pricing_cache_rates.py).
    expected = {"input": 3.0, "output": 15.0, "cache_write": None, "cache_read": None}
    assert saved["prices"]["claude-sonnet-5"] == expected
    assert client.get("/api/pricing").json() == saved


def test_admin_token_gates_config_writes(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    monkeypatch.setenv("MOSAERA_HOME", str(tmp_path))
    monkeypatch.setenv("MOSAERA_ADMIN_TOKEN", "adm1n")
    monkeypatch.delenv(
        "MOSAERA_API_TOKEN", raising=False
    )  # middleware off → isolate the admin gate
    c = TestClient(create_app(graph_factory=_fake_factory))
    # The verify probe: no header / wrong header → 403; correct → ok.
    assert c.get("/api/admin/verify").status_code == 403
    assert c.get("/api/admin/verify", headers={"X-Mosaera-Admin": "nope"}).status_code == 403
    assert c.get("/api/admin/verify", headers={"X-Mosaera-Admin": "adm1n"}).json() == {"ok": True}
    # A config write needs the admin header regardless of socket peer (proxy-safe).
    body = {"prices": {"claude-sonnet-5": {"input": 3.0, "output": 15.0}}}
    assert c.put("/api/pricing", json=body).status_code == 403
    saved = c.put("/api/pricing", headers={"X-Mosaera-Admin": "adm1n"}, json=body)
    assert saved.status_code == 200 and saved.json()["prices"]["claude-sonnet-5"]["input"] == 3.0


def test_providers_test_endpoint(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    # BYOM live discovery: POST /providers/test validates a key + lists the models it
    # grants; admin-gated; a bad key comes back {ok:false} (never a 500).
    monkeypatch.setenv("MOSAERA_HOME", str(tmp_path))
    monkeypatch.setenv("MOSAERA_ADMIN_TOKEN", "adm1n")
    monkeypatch.delenv("MOSAERA_API_TOKEN", raising=False)
    c = TestClient(create_app(graph_factory=_fake_factory))
    hdr = {"X-Mosaera-Admin": "adm1n"}

    # Admin-gated: no header → 403.
    assert (
        c.post("/api/providers/test", json={"provider": "openai", "api_key": "x"}).status_code
        == 403
    )
    # An unknown provider id → 422 (still a real validation error).
    assert (
        c.post("/api/providers/test", headers=hdr, json={"provider": "not-a-provider"}).status_code
        == 422
    )

    # A good key → the models it grants.
    monkeypatch.setattr(
        "mosaera_api.routes.providers.fetch_provider_models",
        lambda *a, **k: ["gpt-4o", "gpt-4o-mini"],
    )
    ok = c.post("/api/providers/test", headers=hdr, json={"provider": "openai", "api_key": "sk-x"})
    assert ok.status_code == 200
    assert ok.json()["ok"] is True and ok.json()["count"] == 2 and "gpt-4o" in ok.json()["models"]

    # A rejected key → {ok:false, error}, HTTP 200 (shown inline by the UI).
    from mosaera_core.models import ProviderAuthError

    def _reject(*_a: object, **_k: object) -> object:
        raise ProviderAuthError("bad key")

    monkeypatch.setattr("mosaera_api.routes.providers.fetch_provider_models", _reject)
    bad = c.post("/api/providers/test", headers=hdr, json={"provider": "openai", "api_key": "nope"})
    assert bad.status_code == 200 and bad.json()["ok"] is False and "invalid" in bad.json()["error"]


def test_providers_test_endpoint_decrypts_stored_key(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    # ADR-0039 regression: with encryption on and NO key in the request, /providers/test must send
    # the DECRYPTED stored key to the provider — not the `enc:v1:…` ciphertext (which would make a
    # valid saved key always test as invalid). The coverage gap that let that bug ship green.
    from cryptography.fernet import Fernet
    from mosaera_core.settings_store import write_settings
    from mosaera_memory import encrypt_secret

    monkeypatch.setenv("MOSAERA_HOME", str(tmp_path))
    monkeypatch.setenv("MOSAERA_ADMIN_TOKEN", "adm1n")
    monkeypatch.delenv("MOSAERA_API_TOKEN", raising=False)
    monkeypatch.setenv("MOSAERA_SECRET_KEY", Fernet.generate_key().decode())
    write_settings(tmp_path, {"providers": {"openai": {"api_key": encrypt_secret("sk-realkey")}}})

    c = TestClient(create_app(graph_factory=_fake_factory))
    seen: dict[str, Any] = {}

    def _capture(provider: str, key: str, *_a: object, **_k: object) -> list[str]:
        seen["key"] = key
        return ["gpt-4o"]

    monkeypatch.setattr("mosaera_api.routes.providers.fetch_provider_models", _capture)
    # No api_key in the body → falls back to the saved (encrypted) key.
    r = c.post(
        "/api/providers/test", headers={"X-Mosaera-Admin": "adm1n"}, json={"provider": "openai"}
    )
    assert r.status_code == 200 and r.json()["ok"] is True
    assert seen["key"] == "sk-realkey"  # the PLAINTEXT reached the provider, not enc:v1:…


def test_delete_tool_admin_toggle(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    monkeypatch.setenv("MOSAERA_HOME", str(tmp_path))
    monkeypatch.setenv("MOSAERA_ADMIN_TOKEN", "adm1n")
    monkeypatch.delenv("MOSAERA_API_TOKEN", raising=False)
    monkeypatch.delenv("MOSAERA_DELETE_TOOL", raising=False)  # env must not override the toggle
    c = TestClient(create_app(graph_factory=_fake_factory))
    assert c.get("/api/features").json() == {"delete_tool_enabled": False}  # off by default
    # The destructive toggle needs the admin header.
    assert c.post("/api/features/delete-tool", json={"enabled": True}).status_code == 403
    ok = c.post(
        "/api/features/delete-tool", headers={"X-Mosaera-Admin": "adm1n"}, json={"enabled": True}
    )
    assert ok.status_code == 200 and ok.json() == {"delete_tool_enabled": True}
    assert c.get("/api/features").json() == {"delete_tool_enabled": True}  # persisted


def test_exposed_instance_without_admin_token_refuses_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Token-protected (exposed) but no admin token → config writes are refused
    # (the localhost gate is unreliable behind a proxy — finding #4).
    monkeypatch.setenv("MOSAERA_API_TOKEN", "run")
    monkeypatch.delenv("MOSAERA_ADMIN_TOKEN", raising=False)
    monkeypatch.delenv("MOSAERA_ALLOW_REMOTE_CONFIG", raising=False)
    c = TestClient(create_app(graph_factory=_fake_factory))
    r = c.put("/api/pricing", headers={"Authorization": "Bearer run"}, json={"prices": {}})
    assert r.status_code == 403 and "MOSAERA_ADMIN_TOKEN" in r.json()["detail"]


def test_config_reports_admin_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MOSAERA_API_TOKEN", raising=False)
    c = TestClient(create_app(graph_factory=_fake_factory))
    monkeypatch.setenv("MOSAERA_ADMIN_TOKEN", "adm1n")
    assert c.get("/api/config").json()["admin_required"] is True
    monkeypatch.delenv("MOSAERA_ADMIN_TOKEN", raising=False)
    assert c.get("/api/config").json()["admin_required"] is False


def test_providers_get_masks_keys(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    # BYOM (#21): the providers view exposes only a masked key hint, never the raw key.
    monkeypatch.setenv("MOSAERA_HOME", str(tmp_path))
    monkeypatch.delenv("MOSAERA_API_TOKEN", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    from mosaera_core.settings_store import write_settings

    write_settings(tmp_path, {"providers": {"openai": {"api_key": "sk-supersecret"}}})
    c = TestClient(create_app(graph_factory=_fake_factory))
    r = c.get("/api/providers")
    assert r.status_code == 200
    openai = next(p for p in r.json()["providers"] if p["id"] == "openai")
    assert openai["has_key"] is True
    assert openai["key_masked"] == "…cret"
    assert "sk-supersecret" not in r.text  # raw key never leaves the server


def test_providers_put_admin_gated_and_persists(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    monkeypatch.setenv("MOSAERA_HOME", str(tmp_path))
    monkeypatch.setenv("MOSAERA_ADMIN_TOKEN", "adm1n")
    monkeypatch.delenv("MOSAERA_API_TOKEN", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    c = TestClient(create_app(graph_factory=_fake_factory))
    body = {
        "providers": {"openai": {"api_key": "sk-live"}},
        "roles": {"coder": {"provider": "openai", "model": "gpt-4o"}},
    }
    # No admin header → refused; with it → persisted.
    assert c.put("/api/providers", json=body).status_code == 403
    r = c.put("/api/providers", headers={"X-Mosaera-Admin": "adm1n"}, json=body)
    assert r.status_code == 200
    assert r.json()["roles"]["coder"] == {"provider": "openai", "model": "gpt-4o"}
    openai = next(p for p in r.json()["providers"] if p["id"] == "openai")
    assert openai["has_key"] is True and "sk-live" not in r.text


def test_providers_put_rejects_keyless_hosted_binding(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    # Binding a role to a hosted provider with no key anywhere is rejected up front
    # (else the run would fail fast at build time).
    monkeypatch.setenv("MOSAERA_HOME", str(tmp_path))
    monkeypatch.setenv("MOSAERA_ADMIN_TOKEN", "adm1n")
    monkeypatch.delenv("MOSAERA_API_TOKEN", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    c = TestClient(create_app(graph_factory=_fake_factory))
    body = {"roles": {"coder": {"provider": "openai", "model": "gpt-4o"}}}
    r = c.put("/api/providers", headers={"X-Mosaera-Admin": "adm1n"}, json=body)
    assert r.status_code == 422


def test_providers_put_persists_on_box_only_for_loopback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """The on-box declaration (ADR-0024, amended) round-trips for a loopback endpoint, and the
    API refuses to store it against a hosted one — so the flag can never sit in settings.json
    meaning nothing, and the rule is enforced server-side, not just by the UI."""
    monkeypatch.setenv("MOSAERA_HOME", str(tmp_path))
    monkeypatch.setenv("MOSAERA_ADMIN_TOKEN", "adm1n")
    monkeypatch.delenv("MOSAERA_API_TOKEN", raising=False)
    c = TestClient(create_app(graph_factory=_fake_factory))
    hdr = {"X-Mosaera-Admin": "adm1n"}

    local = {"providers": {"openai": {"base_url": "http://localhost:8001/v1", "on_box": True}}}
    r = c.put("/api/providers", headers=hdr, json=local)
    assert r.status_code == 200
    entry = next(p for p in r.json()["providers"] if p["id"] == "openai")
    assert entry["on_box"] is True and entry["base_url"] == "http://localhost:8001/v1"
    # Survives a reload (it is persisted, not just echoed).
    assert (
        next(p for p in c.get("/api/providers").json()["providers"] if p["id"] == "openai")[
            "on_box"
        ]
        is True
    )

    # Declaring a HOSTED endpoint on-box is refused outright.
    hosted = {"providers": {"openai": {"base_url": "https://api.openai.com/v1", "on_box": True}}}
    assert c.put("/api/providers", headers=hdr, json=hosted).status_code == 422
    # So is moving an already-declared provider off-box without untangling the flag.
    assert (
        c.put(
            "/api/providers",
            headers=hdr,
            json={"providers": {"openai": {"base_url": "https://x/v1"}}},
        ).status_code
        == 422
    )
    # Untick + repoint together is the honest path, and is accepted.
    off = {"providers": {"openai": {"base_url": "https://x/v1", "on_box": False}}}
    assert c.put("/api/providers", headers=hdr, json=off).status_code == 200


def test_cost_modes_get_defaults(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    monkeypatch.setenv("MOSAERA_HOME", str(tmp_path))
    monkeypatch.delenv("MOSAERA_API_TOKEN", raising=False)
    monkeypatch.delenv("MOSAERA_COST_MODE", raising=False)
    c = TestClient(create_app(graph_factory=_fake_factory))
    body = c.get("/api/cost-modes").json()
    assert body["available"] == ["economy", "balanced", "premium"]
    assert body["default_cost_mode"] == "balanced"
    # Nothing overridden yet → every role shows its effective base fallback.
    assert body["modes"]["economy"]["coder"]["overridden"] is False
    assert body["modes"]["economy"]["coder"]["effective_provider"] == "ollama"


def test_cost_modes_put_admin_gated_and_persists(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    monkeypatch.setenv("MOSAERA_HOME", str(tmp_path))
    monkeypatch.setenv("MOSAERA_ADMIN_TOKEN", "adm1n")
    monkeypatch.delenv("MOSAERA_API_TOKEN", raising=False)
    c = TestClient(create_app(graph_factory=_fake_factory))
    body = {
        "modes": {"premium": {"coder": {"provider": "ollama", "model": "big-local:70b"}}},
        "default_cost_mode": "premium",
    }
    assert c.put("/api/cost-modes", json=body).status_code == 403  # no admin header
    r = c.put("/api/cost-modes", headers={"X-Mosaera-Admin": "adm1n"}, json=body)
    assert r.status_code == 200
    got = r.json()
    assert got["default_cost_mode"] == "premium"
    assert got["modes"]["premium"]["coder"]["model"] == "big-local:70b"
    assert got["modes"]["premium"]["coder"]["overridden"] is True


def test_cost_modes_put_rejects_keyless_hosted(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    monkeypatch.setenv("MOSAERA_HOME", str(tmp_path))
    monkeypatch.setenv("MOSAERA_ADMIN_TOKEN", "adm1n")
    monkeypatch.delenv("MOSAERA_API_TOKEN", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    c = TestClient(create_app(graph_factory=_fake_factory))
    body = {"modes": {"premium": {"coder": {"provider": "openai", "model": "gpt-4o"}}}}
    r = c.put("/api/cost-modes", headers={"X-Mosaera-Admin": "adm1n"}, json=body)
    assert r.status_code == 422


def test_estimate_no_history_is_unavailable(client: TestClient) -> None:
    # Default client has no durable memory → nothing to project from.
    r = client.get("/api/projects/p1/estimate?cost_mode=balanced")
    assert r.status_code == 200
    assert r.json() == {"cost_mode": "balanced", "available": False, "runs_metered": 0}
    assert client.get("/api/projects/p1/estimate?cost_mode=bogus").status_code == 422


def test_project_metrics_endpoint_returns_governance_metrics() -> None:
    class _Mem(_FakeProjectMemory):
        def project_metrics(self, pid: str, since: Any = None) -> dict[str, Any]:
            return {
                "runs_metered": 4,
                "delivered_items": 2,
                "total_calls": 40,
                "total_det_ops": 120,
                "delivered_calls": 24,
                "calls_per_delivered_item": 12.0,
                "det_llm_ratio": 3.0,
                "latency_samples": 6,
                "latency_p50_ms": 820,
                "latency_p95_ms": 1900,
                "by_agent": [],
            }

    body = _client_with(_Mem()).get("/api/projects/p1/metrics").json()
    assert body["det_llm_ratio"] == 3.0
    assert body["calls_per_delivered_item"] == 12.0
    assert body["delivered_items"] == 2
    assert body["latency_p50_ms"] == 820 and body["latency_p95_ms"] == 1900


def test_project_metrics_empty_without_memory(client: TestClient) -> None:
    b = client.get("/api/projects/p1/metrics").json()
    assert b["runs_metered"] == 0
    assert b["calls_per_delivered_item"] is None and b["det_llm_ratio"] is None
    # Latency fields present in the honest empty fallback too.
    assert b["latency_samples"] == 0
    assert b["latency_p50_ms"] is None and b["latency_p95_ms"] is None


def test_estimate_is_conditioned_on_the_mode(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    # Prices this project's historical per-role tokens at the SELECTED mode's models.
    monkeypatch.setenv("MOSAERA_HOME", str(tmp_path))
    monkeypatch.setenv("MOSAERA_MODEL_PRICES", '{"gpt-4o": [10.0, 30.0]}')
    from mosaera_core.settings_store import write_settings

    write_settings(
        tmp_path,
        {"cost_modes": {"premium": {"coder": {"provider": "openai", "model": "gpt-4o"}}}},
    )

    class _Mem(_FakeProjectMemory):
        def project_cost(self, pid: str, since: Any = None) -> dict[str, Any]:
            # 2 runs; coder used 2M input / 1M output total → avg 1M in, 0.5M out.
            return {
                "runs_metered": 2,
                "by_agent": [
                    {"agent": "Coder", "input_tokens": 2_000_000, "output_tokens": 1_000_000},
                    {"agent": "PM", "input_tokens": 0, "output_tokens": 0},
                ],
            }

    c = _client_with(_Mem())
    body = c.get("/api/projects/p1/estimate?cost_mode=premium").json()
    assert body["available"] is True and body["runs_metered"] == 2
    # gpt-4o @ ($10 in, $30 out)/1M on 1M in + 0.5M out → 10 + 15 = $25.
    assert abs(body["projected_usd"] - 25.0) < 1e-6
    coder = next(r for r in body["per_role"] if r["role"] == "coder")
    assert coder["model"] == "gpt-4o"


def test_models_falls_back_to_configured_when_ollama_unreachable(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    # Point at a black-hole Ollama so /api/tags fails; the endpoint must still
    # offer the configured role models (so the pricing picker is never empty).
    # Isolate MOSAERA_HOME to an empty dir so /api/models sees ONLY Ollama — otherwise it
    # reads the developer's real .mosaera/settings.json, which configures cloud providers
    # (e.g. the escalation ladder), and they legitimately appear as extra source groups.
    monkeypatch.setenv("MOSAERA_HOME", str(tmp_path))
    monkeypatch.setenv("MOSAERA_OLLAMA_BASE_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("MOSAERA_MODEL_PM", "gpt-oss:20b")
    monkeypatch.setenv("MOSAERA_MODEL_CODER", "qwen3-coder:30b")
    sources = client.get("/api/models").json()["sources"]
    # One group, attributed to Ollama, carrying the configured models.
    assert [s["source"] for s in sources] == ["Ollama"]
    models = sources[0]["models"]
    assert "gpt-oss:20b" in models
    assert "qwen3-coder:30b" in models


class _FakeMemoryBudget:
    """Minimal store for the project-budget endpoints: holds caps, reports a
    fixed cumulative spend."""

    def __init__(self) -> None:
        self._budget: dict[str, Any] = {"budget_usd": None, "budget_tokens": None}

    def project_detail(self, project_id: str) -> dict[str, Any]:
        return {"id": project_id, "runs": [], **self._budget}

    def project_cost(self, project_id: str, since: Any = None) -> dict[str, Any]:
        return {"usd": 8.0, "total_tokens": 900_000, "runs_metered": 2}

    def set_project_budget(
        self, project_id: str, *, budget_usd: Any, budget_tokens: Any
    ) -> dict[str, Any]:
        self._budget = {"budget_usd": budget_usd, "budget_tokens": budget_tokens}
        return {"id": project_id, **self._budget}


def test_project_budget_set_and_status_warns_and_caps() -> None:
    c = _client_with(_FakeMemoryBudget())
    # A $10 / 1M-token monthly cap; spent is a fixed 8 / 900k.
    resp = c.post("/api/projects/p1/budget", json={"budget_usd": 10.0, "budget_tokens": 1_000_000})
    assert resp.json()["budget_usd"] == 10.0 and resp.json()["budget_tokens"] == 1_000_000
    st = c.get("/api/projects/p1/budget").json()
    assert st["spent_usd"] == 8.0 and st["spent_tokens"] == 900_000
    assert st["warn"] is True and st["over"] is False  # 90% of tokens → warn, not over
    assert st["resets_at"] and st["cycle_start"]

    # Tighten the token cap below current spend → over.
    c.post("/api/projects/p1/budget", json={"budget_usd": None, "budget_tokens": 500_000})
    over = c.get("/api/projects/p1/budget").json()
    assert over["over"] is True and "tokens" in over["reason"]


def test_project_budget_status_reports_spend_with_no_cap_set() -> None:
    """A capless project still reports the month's spend — the Overview budgets card shows
    spend regardless of whether a ceiling was configured; only ENFORCEMENT is cap-gated."""
    c = _client_with(_FakeMemoryBudget())
    st = c.get("/api/projects/p1/budget").json()
    assert st["budget_usd"] is None and st["budget_tokens"] is None
    assert st["spent_usd"] == 8.0 and st["spent_tokens"] == 900_000
    assert st["over"] is False and st["warn"] is False and st["pct"] == 0.0


# --- ADR-0035: a configured-but-unreachable database is FATAL, not a silent degrade ---


_DEAD_DB = "postgresql://u:p@127.0.0.1:1/nope"  # port 1 refuses immediately — no DB needed


def test_boot_refuses_when_the_db_is_configured_but_unreachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The API used to boot happily with a dead database and say nothing.

    It ran with no run history, parked runs that could not be rehydrated, project endpoints
    400-ing with "set MOSAERA_DB_URL" (which IS set) — and, worst, auth enforcement FAILING
    OPEN, because `users_exist` read the unreachable store as "no users exist". Fail closed,
    matching guard_bind and the CLI (which already raises on exactly this).
    """
    monkeypatch.setenv("MOSAERA_DB_URL", _DEAD_DB)
    monkeypatch.delenv("MOSAERA_ALLOW_DEGRADED_MEMORY", raising=False)
    with pytest.raises(SystemExit) as exc:
        create_app(graph_factory=_fake_factory)
    msg = str(exc.value)
    assert "unreachable" in msg
    assert "MOSAERA_ALLOW_DEGRADED_MEMORY" in msg  # the escape hatch is named
    assert "auth would NOT be enforced" in msg  # and the real stake is spelled out


def test_boot_degrades_loudly_with_the_explicit_opt_in(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # An operator who genuinely wants a history-less API can have one — as a CHOICE, stated
    # out loud. That is the whole difference from the old silent degrade.
    monkeypatch.setenv("MOSAERA_DB_URL", _DEAD_DB)
    monkeypatch.setenv("MOSAERA_ALLOW_DEGRADED_MEMORY", "1")
    app = create_app(graph_factory=_fake_factory)
    out = capsys.readouterr().out
    assert "durable memory is UNAVAILABLE" in out
    assert "auth is NOT enforced" in out
    assert TestClient(app).get("/healthz").json() == {
        "status": "degraded",
        "memory": "unavailable",
    }


def test_healthz_is_honest_about_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    # /healthz used to be the literal {"status": "ok"} — it would report healthy with a dead
    # database behind it, which is precisely the lie a health check exists to catch.
    monkeypatch.delenv("MOSAERA_DB_URL", raising=False)
    c = TestClient(create_app(graph_factory=_fake_factory))
    assert c.get("/healthz").json() == {"status": "ok", "memory": "none"}


# --- Standing corrections are visible to the operator (F17 follow-up). ---
# They were exposed nowhere — not run detail, not the transcript, not a decision row — so a
# constraint that steers every later write was invisible to whoever set it, and the 2026-08-06
# failure could not be diagnosed from outside the process.


def _bare_session() -> Any:
    from mosaera_api.runner._base import RunSessionBase

    s = RunSessionBase.__new__(RunSessionBase)  # no engine/thread wiring needed for this
    s.corrections = []
    s.unsatisfiable_tests = []
    return s


def test_corrections_accumulate_from_node_updates_deduped() -> None:
    s = _bare_session()
    s._record_corrections({"corrections": ["never the src. prefix"]})
    # The same rule can legitimately arrive twice — from the Proctor's delta and from the coder.
    s._record_corrections({"corrections": ["never the src. prefix"]})
    s._record_corrections({"corrections": ["keep the hard assertions"]})
    assert s.corrections == [
        "never the src. prefix",
        "keep the hard assertions",
    ]


def test_corrections_ignore_unrelated_or_malformed_updates() -> None:
    s = _bare_session()
    s._record_corrections({"design": "x"})
    s._record_corrections({"corrections": []})
    s._record_corrections({"corrections": ["   "]})  # blank is not a constraint
    s._record_corrections("not a dict")
    s._record_corrections(None)
    assert s.corrections == []


def test_unsatisfiable_findings_accumulate_and_dedupe() -> None:
    # F36: surfaced at authoring time rather than discovered ~256k tokens later at an escalation.
    s = _bare_session()
    s.unsatisfiable_tests = []
    f = {
        "file": "tests/test_x.py",
        "line": 12,
        "kind": "unsupplied_value",
        "snippet": "2023-01-01,12.34,food",
        "suggestion": "pins '2023-01-01'",
        "auto_loosenable": False,
    }
    s._record_corrections({"unsatisfiable_tests": [f]})
    s._record_corrections({"unsatisfiable_tests": [f]})  # a re-plan can re-emit the same finding
    assert s.unsatisfiable_tests == [f]


def test_unsatisfiable_findings_ignore_junk() -> None:
    s = _bare_session()
    s.unsatisfiable_tests = []
    s._record_corrections({"unsatisfiable_tests": ["not a dict"]})
    s._record_corrections({"unsatisfiable_tests": []})
    s._record_corrections({"corrections": ["unrelated"]})
    assert s.unsatisfiable_tests == []


# --- F50: a run that was CANCELLED must still record why it ended ----------------------------
#
# Measured 2026-08-06: all 11 LedgerCLI runs were cancelled, so the project's entire history was
# diagnostically blank. When the PM was finally given run evidence to read (F47) it correctly
# reported "the engine recorded no diagnosis" — and then filled the silence with a wrong causal
# story anyway. The honest-absence line only helps when absence is rare; here it was universal.
# A cancel is how an operator ends a stuck run, which makes it the case we can least afford to lose.


def test_a_cancelled_run_records_why_it_ended() -> None:
    from mosaera_api.runner import RunSession

    reached = threading.Event()
    release = threading.Event()

    def node_a(state: _State) -> dict[str, Any]:
        reached.set()
        release.wait(5)
        return {"plan": "a"}

    def node_b(state: _State) -> dict[str, Any]:
        return {"approved": True}

    mem = _FakeProjectMemory()
    mem.create_project("p1", "P", "src")
    iid = mem.add_backlog_item("p1", "one", position=0)
    mem.update_backlog_item(iid, status="in_progress")
    s = RunSession(
        "cxd-1",
        _linear_graph(("a", node_a), ("b", node_b)),
        {"configurable": {"thread_id": "cxd-1"}},
        {"task": "x"},
        memory=mem,  # type: ignore[arg-type]
        item_id=iid,
    )
    s.start()
    assert reached.wait(5)
    s.cancel()
    release.set()
    assert s._thread is not None
    s._thread.join(5)
    assert s.status == "cancelled"

    diagnosis = mem.diagnoses.get("cxd-1")
    assert diagnosis is not None, "a cancelled run must not be diagnostically blank"
    # Stamped, so a reader can tell "the operator stopped it" from "it concluded on its own".
    assert diagnosis["ended_by"] == "cancelled"
    assert "outcome" in diagnosis
    assert any(e[1] == "diagnosis" for e in mem.audits)


def test_a_cancel_before_any_graph_state_still_records_how_it_ended() -> None:
    """The partial case, and the common one: a cancel can land anywhere, including before the
    graph has produced state. Partial evidence beats none — recording nothing is what left the
    LedgerCLI history blank."""
    from mosaera_api.runner import RunSession

    mem = _FakeProjectMemory()
    s = RunSession(
        "cxd-2",
        _linear_graph(("a", lambda state: {"approved": True})),
        {"configurable": {"thread_id": "cxd-2"}},
        {"task": "x"},
        memory=mem,  # type: ignore[arg-type]
    )
    s._record_terminal_diagnosis("cancelled")
    diagnosis = mem.diagnoses.get("cxd-2")
    assert diagnosis is not None
    assert diagnosis["ended_by"] == "cancelled"


def test_snapshot_records_the_control_set_the_run_started_with(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """The UI shows the run's full cast — agents AND oracles — from t=0, including the ones that
    are switched OFF. Before this the roster was inferred from observed events, so a disabled
    control looked exactly like one that had not been reached yet, and neither appeared at all.
    That is how `critic_enabled` sat at its highest proven liveness rung and OFF on the live
    instance (2026-08-06) with no screen saying so.

    Captured at construction and never re-read: a knob flipped later must not retroactively
    re-describe a finished run.
    """
    from mosaera_api.runner import RunSession

    monkeypatch.setenv("MOSAERA_CRITIC_ENABLED", "0")
    monkeypatch.setenv("MOSAERA_TESTER", "1")
    s = RunSession(
        "ctl-1",
        _linear_graph(("g", lambda _s: {"approved": True})),
        {"configurable": {"thread_id": "ctl-1"}},
        {"task": "x"},
    )
    controls = s.snapshot()["controls"]
    assert controls["critic_enabled"] is False
    assert controls["tester_enabled"] is True

    # Flipping the knob afterwards must NOT re-describe this run.
    monkeypatch.setenv("MOSAERA_CRITIC_ENABLED", "1")
    assert s.snapshot()["controls"]["critic_enabled"] is False


# --- option_id: the gate's answers become checkable (ADR-0082 §5, F61) -------------------------
#
# `authorize_tests` was threaded through four layers as a bespoke field; a second such field is
# the anti-pattern. `option_id` is the general contract — and its real value is not plumbing, it
# is catching a STALE SCREEN: an operator shown "Send back to revise" whose run has since hit the
# cap (where that same answer ENDS the run and discards their notes) now gets a refusal instead of
# silently doing the opposite of what they clicked.


def _build_outcomes_graph(captured: dict[str, Any], outcomes: list[dict[str, Any]]) -> Any:
    """A graph whose single interrupt DECLARES its available outcomes, like the real gate."""

    def gate(state: _State) -> dict[str, Any]:
        captured["resume"] = interrupt(
            {"action": "deliver", "summary": "finalize", "outcomes": outcomes}
        )
        return {"approved": True}

    builder: StateGraph = StateGraph(_State)
    builder.add_node("g", gate)
    builder.add_edge(START, "g")
    builder.add_edge("g", END)
    return builder.compile(checkpointer=InMemorySaver())


_TWO_OPTIONS = [
    {"id": "approve", "label": "Approve & deliver", "effect": "approve"},
    {"id": "send_back", "label": "Send it back to revise", "effect": "send_back"},
]


def _parked(captured: dict[str, Any], outcomes: list[dict[str, Any]]) -> Any:
    from mosaera_api.runner import RunSession

    s = RunSession(
        "opt-1",
        _build_outcomes_graph(captured, outcomes),
        {"configurable": {"thread_id": "opt-1"}},
        {"task": "t"},
        auto_approve=False,
        mode="guided",
    )
    s.start()
    _settle(s, statuses=("awaiting_approval",))
    return s


def test_a_declared_option_is_accepted_and_carried() -> None:
    captured: dict[str, Any] = {}
    s = _parked(captured, _TWO_OPTIONS)
    s.approve(True, "", None, "approve")
    _settle(s)
    assert captured["resume"]["option_id"] == "approve"


def test_an_undeclared_option_is_REJECTED_never_auto_approved() -> None:
    """The hazard ADR-0080 recorded: the runner auto-approves unknown interrupt actions, so a
    new answer that is merely *ignored* becomes an approval. It must raise instead."""
    captured: dict[str, Any] = {}
    s = _parked(captured, _TWO_OPTIONS)
    with pytest.raises(ValueError, match="unknown option"):
        s.approve(False, "", None, "end_run")  # not offered at THIS gate
    assert "resume" not in captured  # nothing was decided


def test_a_rejected_option_leaves_the_park_ANSWERABLE() -> None:
    """A typo must not strand the run with nothing awaiting — validation happens before the
    single decision slot is claimed."""
    captured: dict[str, Any] = {}
    s = _parked(captured, _TWO_OPTIONS)
    with pytest.raises(ValueError):
        s.approve(True, "", None, "nonsense")
    assert s.status == "awaiting_approval"
    s.approve(True, "", None, "approve")  # still answerable
    _settle(s)
    assert s.status == "completed"


def test_the_stale_screen_case_is_refused() -> None:
    """THE reason this exists. The run has reached a state where the only denial is terminal, so
    the gate offers `end_run` — an operator whose page still shows `send_back` is refused rather
    than silently ending the run (F61's failure mode, made detectable)."""
    captured: dict[str, Any] = {}
    terminal = [
        {"id": "approve", "label": "Approve anyway", "effect": "approve"},
        {"id": "end_run", "label": "End the run without delivering", "effect": "end_run"},
    ]
    s = _parked(captured, terminal)
    with pytest.raises(ValueError, match="send_back"):
        s.approve(False, "please fix the naming", None, "send_back")
    assert "resume" not in captured


def test_a_gate_declaring_no_outcomes_rejects_any_option() -> None:
    """Deny-by-default. A write gate declares no outcomes yet, so it accepts no option ids —
    it must not silently ignore one."""
    captured: dict[str, Any] = {}
    s = _parked(captured, [])
    with pytest.raises(ValueError, match="offers none"):
        s.approve(True, "", None, "approve")


def test_omitting_option_id_is_byte_identical_to_the_old_contract() -> None:
    """Compatibility is the default: every existing caller omits it."""
    captured: dict[str, Any] = {}
    s = _parked(captured, _TWO_OPTIONS)
    s.approve(True, "notes")
    _settle(s)
    assert captured["resume"]["approve"] is True
    assert captured["resume"]["feedback"] == "notes"
    assert captured["resume"]["option_id"] is None
