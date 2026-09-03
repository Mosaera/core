"""Project setup — the onboarding endpoints (#121).

The properties that matter, in the order they matter:

1. **Three authorities, gated separately.** A member may set their own project's run mode and test
   command; only an admin may move the ADR-0046 posture or the deployment-global Proctor knob. A
   body that touches one must not smuggle the others.
2. **Enumerables are server-declared.** The UI renders dropdowns from `choices`, and the write path
   rejects anything outside them (ADR-0005) — so a typo can never become stored config.
3. **A clone that is not there yet says so.** Intake clones in the background, so "not readable
   yet" is the COMMON first read. It must never render as a shape (ADR-0035).
4. **The levers actually move something.** A stored test command reaches the run, and a stored run
   mode is what an unspecified launch uses — otherwise both are invisible controls.
"""

from __future__ import annotations

from typing import Any, ClassVar

import pytest
from test_api import _client_with, _FakeProjectMemory


class _SetupMemory(_FakeProjectMemory):
    """`_FakeProjectMemory` plus the onboarding columns and their store-side rules.

    Lives HERE, not in `test_api.py`: that file is a grandfathered god-file the size ratchet only
    lets shrink, and this fixture is only ever needed by these tests. Subclassing also keeps the
    fake honest — the run-mode check below mirrors the real store's deny-by-default validation, so
    the route's 400 path is genuinely exercised rather than assumed.
    """

    _ONBOARDING: ClassVar[dict[str, Any]] = {
        "default_run_mode": "guided",
        "test_cmd": "",
        "setup_completed_at": None,
    }

    def create_project(self, pid: str, *a: Any, **kw: Any) -> None:
        super().create_project(pid, *a, **kw)
        self.projects[pid].update(self._ONBOARDING)

    def update_project(self, pid: str, **kw: Any) -> None:
        from mosaera_memory.models import RUN_MODES

        mode = kw.get("default_run_mode")
        if mode is not None and mode not in RUN_MODES:
            raise ValueError(f"unknown run mode {mode!r}")
        if (done := kw.pop("setup_completed", None)) is not None:
            kw["setup_completed_at"] = "t" if done else None
        # `test_cmd=""` CLEARS, so it must survive the base class's None-filter — that filter is
        # about "omitted", not "empty", and `""` is not None.
        super().update_project(pid, **kw)

    def set_project_budget(
        self, pid: str, *, budget_usd: float | None, budget_tokens: int | None
    ) -> dict[str, Any] | None:
        if (p := self.projects.get(pid)) is None:
            return None
        p["budget_usd"], p["budget_tokens"] = budget_usd, budget_tokens
        return self.project_detail(pid)


def _mem() -> Any:
    mem: Any = _SetupMemory()
    mem.create_project("p1", "P", "https://gitlab.example.com/g/p.git")
    return mem


# --- the read -------------------------------------------------------------------------------


def test_get_setup_serves_the_choice_sets_the_write_path_validates_against() -> None:
    from mosaera_memory.models import RUN_MODES
    from mosaera_memory.models_charter import CHARTER_POSTURES

    body = _client_with(_mem()).get("/api/projects/p1/setup").json()
    # One origin for every enumerable: the SPA never keeps its own copy of these lists.
    assert set(body["choices"]["run_mode"]) == RUN_MODES
    assert set(body["choices"]["posture"]) == CHARTER_POSTURES
    assert body["choices"]["cost_mode"]  # the routing tiers, for the budget row


def test_get_setup_starts_at_the_safe_defaults() -> None:
    body = _client_with(_mem()).get("/api/projects/p1/setup").json()
    # Graduated autonomy: the flow opens at the most supervised mode and the operator opts UP.
    assert body["current"]["run_mode"] == "guided"
    assert body["current"]["posture"] == "business"
    assert body["current"]["test_cmd"] == ""
    assert body["completed_at"] is None  # never answered


def test_a_clone_that_is_not_there_yet_reads_as_unavailable_not_as_a_shape() -> None:
    body = _client_with(_mem()).get("/api/projects/p1/setup").json()
    assert body["available"] is False
    assert body["reason"]  # names WHY, per ADR-0035 — never a silent omission
    assert "repo_shape" not in body  # and emphatically not a guessed one


def test_the_unavailable_reason_does_not_leak_the_host_path() -> None:
    """Red-team 2026-08-24, finding 1. `open_project_workspace` raises `project clone not found at
    <absolute host path>`; interpolating it handed the server's filesystem layout to any
    authenticated caller, on the ordinary first read, for no operator benefit."""
    body = _client_with(_mem()).get("/api/projects/p1/setup").json()
    assert body["available"] is False
    assert body["reason"]  # still says WHY (ADR-0035) — the state, not the stack trace
    assert "/" not in body["reason"]
    assert ".mosaera" not in body["reason"]


def test_get_setup_404s_on_an_unknown_project() -> None:
    assert _client_with(_mem()).get("/api/projects/nope/setup").status_code == 404


def test_the_shape_and_plan_are_served_once_the_clone_exists(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_clone(tmp_path, monkeypatch, {"app.py": "x = 1\n"})
    body = _client_with(_mem()).get("/api/projects/p1/setup").json()
    assert body["available"] is True
    assert body["repo_shape"]["shape"] == "greenfield"
    assert body["repo_shape"]["evidence"]  # provenanced, never a bare claim
    # The newcomer's default state, stated before the first run rather than discovered at the gate.
    assert body["oracle_plan"]["verified_possible"] is False
    assert body["oracle_plan"]["recommended_knobs"] == ["tester_enabled"]


# --- the write: three authorities -----------------------------------------------------------


def test_a_member_may_set_run_mode_and_test_command(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOSAERA_ADMIN_TOKEN", "adm")
    c = _client_with(_mem())
    r = c.put(
        "/api/projects/p1/setup",
        json={"run_mode": "autonomous", "test_cmd": "pytest -q", "completed": True},
    )
    assert r.status_code == 200
    out = r.json()["current"]
    assert out["run_mode"] == "autonomous" and out["test_cmd"] == "pytest -q"
    assert r.json()["completed_at"] is not None  # the card can now collapse


def test_moving_the_posture_needs_an_admin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOSAERA_ADMIN_TOKEN", "adm")
    c = _client_with(_mem())
    denied = c.put("/api/projects/p1/setup", json={"posture": "regulated"})
    assert denied.status_code == 403  # governance is not a preference
    ok = c.put(
        "/api/projects/p1/setup",
        json={"posture": "regulated"},
        headers={"X-Mosaera-Admin": "adm"},
    )
    assert ok.status_code == 200 and ok.json()["current"]["posture"] == "regulated"


def test_resending_the_stored_posture_is_not_a_governance_act(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The ADR-0047 amendment's rule. The card sends the whole body on every save, so re-sending an
    # unchanged posture must not 403 a member out of setting their own run mode.
    monkeypatch.setenv("MOSAERA_ADMIN_TOKEN", "adm")
    c = _client_with(_mem())
    r = c.put("/api/projects/p1/setup", json={"posture": "business", "run_mode": "autonomous"})
    assert r.status_code == 200 and r.json()["current"]["run_mode"] == "autonomous"


def test_the_global_proctor_knob_needs_an_admin(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    monkeypatch.setenv("MOSAERA_ADMIN_TOKEN", "adm")
    monkeypatch.setenv("MOSAERA_HOME", str(tmp_path / "home"))
    c = _client_with(_mem())
    assert c.put("/api/projects/p1/setup", json={"tester_enabled": True}).status_code == 403
    ok = c.put(
        "/api/projects/p1/setup",
        json={"tester_enabled": True},
        headers={"X-Mosaera-Admin": "adm"},
    )
    assert ok.status_code == 200 and ok.json()["current"]["tester_enabled"] is True
    # It really is the deployment-global knob store, not a per-project shadow copy.
    from mosaera_core.settings_store import read_settings

    assert read_settings(tmp_path / "home")["tester_enabled"] is True


def test_out_of_set_values_are_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOSAERA_ADMIN_TOKEN", "adm")
    c = _client_with(_mem())
    adm = {"X-Mosaera-Admin": "adm"}
    assert c.put("/api/projects/p1/setup", json={"run_mode": "yolo"}).status_code == 400
    assert c.put("/api/projects/p1/setup", json={"posture": "yolo"}, headers=adm).status_code == 400


def test_an_omitted_field_is_left_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    # The charter's red-team lesson (2026-08-18 finding 2) applied here, where it matters more:
    # this body spans three authorities, so a defaulting field would exercise one by accident.
    monkeypatch.setenv("MOSAERA_ADMIN_TOKEN", "adm")
    c = _client_with(_mem())
    c.put("/api/projects/p1/setup", json={"run_mode": "autonomous", "test_cmd": "pytest -q"})
    c.put("/api/projects/p1/setup", json={"completed": True})  # touches nothing else
    out = c.get("/api/projects/p1/setup").json()["current"]
    assert out["run_mode"] == "autonomous" and out["test_cmd"] == "pytest -q"


def test_an_empty_test_command_clears_it(monkeypatch: pytest.MonkeyPatch) -> None:
    # "" is a real instruction (stop using my command), distinct from omitting the field.
    monkeypatch.setenv("MOSAERA_ADMIN_TOKEN", "adm")
    c = _client_with(_mem())
    c.put("/api/projects/p1/setup", json={"test_cmd": "pytest -q"})
    r = c.put("/api/projects/p1/setup", json={"test_cmd": ""})
    assert r.json()["current"]["test_cmd"] == ""


def test_put_setup_404s_on_an_unknown_project() -> None:
    assert _client_with(_mem()).put("/api/projects/nope/setup", json={}).status_code == 404


# --- the levers actually move something -----------------------------------------------------


def _recording_client(mem: Any) -> tuple[Any, list[Any]]:
    """A client whose graph factory RECORDS the `RunSubmit` each launch builds.

    The submit is where the onboarding choices enter the engine, so it is the honest place to
    assert they arrived — driving a real launch rather than inspecting source text (a string match
    would pass against a stub, which is the green-by-vacancy shape this repo keeps measuring).
    """
    from fastapi.testclient import TestClient
    from mosaera_api import create_app
    from test_api import _fake_factory

    seen: list[Any] = []

    def factory(req: Any, run_id: str) -> Any:
        seen.append(req)
        return _fake_factory(req, run_id)

    return TestClient(create_app(graph_factory=factory, memory=mem)), seen


def test_the_stored_test_command_reaches_the_run() -> None:
    """`test_cmd` is one of the four independence legs and was reachable only from the CLI. If it
    does not arrive on the submit, the setup card's oracle row is decorative."""
    mem = _mem()
    item = mem.add_backlog_item("p1", "do the thing", position=0)
    c, seen = _recording_client(mem)
    c.put("/api/projects/p1/setup", json={"test_cmd": "pytest -q tests/"})
    assert c.post(f"/api/projects/p1/backlog/{item}/run").status_code == 201
    assert seen and seen[-1].test_cmd == "pytest -q tests/"


def test_no_stored_command_leaves_the_planner_to_detect() -> None:
    # Absent must be None, not "" — `resolve_plan` branches on truthiness, and an empty custom
    # command would build a plan with a step that runs nothing.
    mem = _mem()
    item = mem.add_backlog_item("p1", "do the thing", position=0)
    c, seen = _recording_client(mem)
    assert c.post(f"/api/projects/p1/backlog/{item}/run").status_code == 201
    assert seen[-1].test_cmd is None


def test_an_unspecified_launch_uses_the_projects_default_mode() -> None:
    """`RunItemBody.mode` had a hard `guided` default, which made the stored project default
    unreachable through the path the UI calls — an invisible control. `autonomous` on the submit is
    the observable consequence of the resolved mode (it drives the ADR-0020 verify overlay)."""
    mem = _mem()
    item = mem.add_backlog_item("p1", "do the thing", position=0)
    c, seen = _recording_client(mem)
    c.put("/api/projects/p1/setup", json={"run_mode": "autonomous"})
    assert c.post(f"/api/projects/p1/backlog/{item}/run").status_code == 201
    assert seen[-1].autonomous is True  # the project default was honoured


def test_an_explicit_run_mode_still_wins_over_the_project_default() -> None:
    # Its own client: the project is reserved for the duration of a launch, so a second launch on
    # the same one is a 409 and would silently leave `seen[-1]` as the first submit.
    mem = _mem()
    item = mem.add_backlog_item("p1", "do the thing", position=0)
    c, seen = _recording_client(mem)
    c.put("/api/projects/p1/setup", json={"run_mode": "autonomous"})
    assert (
        c.post(f"/api/projects/p1/backlog/{item}/run", json={"mode": "guided"}).status_code == 201
    )
    assert seen[-1].autonomous is False


# --- helpers ---------------------------------------------------------------------------------


def _seed_clone(tmp_path: Any, monkeypatch: pytest.MonkeyPatch, files: dict[str, str]) -> None:
    """Materialize the persistent project clone the setup read opens, under an isolated home.

    `MOSAERA_HOME` is set to a tmp dir on purpose: `Settings.home` is cwd-relative, and a probe
    that inherits its destination is the mistake that destroyed ~2,500 scorecards on 2026-08-10.
    """
    from git import Repo

    home = tmp_path / "home"
    monkeypatch.setenv("MOSAERA_HOME", str(home))
    root = home / "projects" / "p1" / "repo"
    root.mkdir(parents=True)
    repo = Repo.init(root)
    for rel, content in files.items():
        (root / rel).write_text(content, encoding="utf-8")
    repo.index.add(list(files))
    repo.index.commit("seed")


def test_run_modes_in_sync() -> None:
    """The store enum and the API literal must be the same set.

    `memory` is a leaf and cannot import apps/api, so the pairing is pinned by a test rather than
    an import — the `test_charter_postures_in_sync` precedent. Without it the route could accept a
    mode the store rejects (a 400 on a value the schema advertises) or the reverse.
    """
    from typing import get_args, get_type_hints

    from mosaera_api.schemas import RunItemBody
    from mosaera_memory.models import RUN_MODES

    # `mode` is `Literal[...] | None`, so the strings sit one level down inside the union.
    literal = {
        value
        for member in get_args(get_type_hints(RunItemBody)["mode"])
        for value in get_args(member)
        if isinstance(value, str)
    }
    assert literal == RUN_MODES
