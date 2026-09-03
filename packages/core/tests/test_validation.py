"""Validation Planner: detection table, the HTML checker program, run_plan."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from mosaera_core.languages.node import NODE_SANDBOX_IMAGE
from mosaera_core.languages.sql import SQL_SANDBOX_IMAGE
from mosaera_core.progress import parse_failing_count
from mosaera_core.sandbox import SubprocessSandbox
from mosaera_core.tools.repo import Workspace
from mosaera_core.validation import (
    HTML_CHECK_SRC,
    cap_output,
    detect_validation_plan,
    resolve_plan,
    run_plan,
)


def testcap_output_keeps_the_pytest_summary_so_the_count_survives() -> None:
    # Regression (#56): a HEAD-only cap ate pytest's trailing `=== N failed ===` summary, so
    # parse_failing_count returned None and the honest-stop's progress breaker never engaged.
    # Head+tail capping keeps both the failure context AND the summary.
    body = "\n".join(
        "    E       assert 0 == 1  # a long verbose assertion diff line" for _ in range(500)
    )
    summary = "=== 2 failed, 5 passed in 1.2s ==="
    full = f"test session starts\n{body}\nFAILED tests/test_x.py::test_a\n{summary}"
    assert len(full) > 4_000  # genuinely over the default cap
    capped = cap_output(full)
    assert len(capped) < len(full)  # it truncated
    assert summary in capped  # the summary survived (tail kept)
    assert "test session starts" in capped  # early context survived (head kept)
    assert parse_failing_count(capped) == 2  # the count signal is readable → breaker can engage


def _ws(tmp_path: Path, files: dict[str, str]) -> Workspace:
    for rel, content in files.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return Workspace(root=tmp_path, run_id="t", branch="b")


# --- detection decision tree (normative table) ---


def test_detects_pytest_via_config(tmp_path: Path) -> None:
    plan = detect_validation_plan(_ws(tmp_path, {"pytest.ini": "[pytest]\n", "app.py": "x=1\n"}))
    assert plan.project_type == "python-pytest"
    assert [s.name for s in plan.steps] == ["pytest"]
    assert "pytest configuration" in plan.reason


def test_detects_pytest_via_test_files(tmp_path: Path) -> None:
    plan = detect_validation_plan(_ws(tmp_path, {"tests/test_app.py": "def test_x(): pass\n"}))
    assert plan.project_type == "python-pytest"
    assert "test files" in plan.reason


def test_pytest_plan_is_config_driven_not_scoped_to_tests(tmp_path: Path) -> None:
    # #45 (ADR-0054): the plan runs pytest's OWN discovery from the workspace root — NO hard-coded
    # `tests/` path arg and NO synthesized paths — so a test ANYWHERE (incl. the repo root) is
    # validated, while the repo's own testpaths/python_files/norecursedirs are honored. The end-to-
    # end proofs (test_run_plan_* below) show the root regression is actually caught.
    plan = detect_validation_plan(
        _ws(
            tmp_path,
            {"tests/test_app.py": "def test_x(): pass\n", "test_root.py": "def test_r(): pass\n"},
        ),
        install=False,
    )
    assert plan.project_type == "python-pytest"
    args = next(s for s in plan.steps if s.name == "pytest").cmd
    assert "--import-mode=importlib" in args  # duplicate-basename import safety
    assert "tests" not in args and "test_root.py" not in args  # no synthesized path scoping
    # #55: full assertion diffs on failure (not truncated) while keeping -q's quiet summary.
    assert "-q" in args and "verbosity_assertions=2" in args
    # #59 (ADR-0064): the agent scratch space is pruned from collection regardless of the untrusted
    # repo's norecursedirs — so a scratch test_*.py can never poison the oracle (red-team fix).
    assert "--ignore=.mosaera" in args


def test_pytest_beats_package_json(tmp_path: Path) -> None:
    # Runnable evidence beats manifest presence (fullstack repo with a suite).
    plan = detect_validation_plan(
        _ws(tmp_path, {"package.json": "{}", "test_app.py": "def test_x(): pass\n"})
    )
    assert plan.project_type == "python-pytest"


def test_node_project_with_no_tsconfig_or_tests_is_unavailable(tmp_path: Path) -> None:
    # A package.json with neither a tsconfig nor a test suite has no offline correctness check
    # → empty steps → validation_unavailable (honest park), not a false green.
    plan = detect_validation_plan(_ws(tmp_path, {"package.json": '{"name":"t"}'}), install=False)
    assert plan.project_type == "node"
    assert plan.steps == []
    assert "no offline correctness check" in plan.reason


def test_manifest_signal_beats_a_stray_source_file(tmp_path: Path) -> None:
    # LanguagePack confidence dispatch: a package.json (manifest, strong signal) beats a stray
    # .py (bare sources, weak signal) with no pytest — so a JS repo carrying a debug script is
    # detected as Node, not mis-detected as a Python project.
    plan = detect_validation_plan(
        _ws(tmp_path, {"package.json": "{}", "index.js": "console.log(1)", "debug.py": "print(1)"}),
        install=False,
    )
    assert plan.project_type == "node"


def test_node_project_gets_install_typecheck_and_test(tmp_path: Path) -> None:
    plan = detect_validation_plan(
        _ws(
            tmp_path,
            {
                "package.json": (
                    '{"name":"t","scripts":{"test":"vitest run"},'
                    '"devDependencies":{"vitest":"^1","typescript":"^5"}}'
                ),
                "tsconfig.json": "{}",
                "src/index.ts": "export const x = 1;\n",
                "package-lock.json": "{}",
            },
        ),
        install=True,
    )
    assert plan.project_type == "node"
    assert plan.image == NODE_SANDBOX_IMAGE  # runs on the Node sandbox image (Stage 1a override)
    assert [s.name for s in plan.steps] == ["install", "typecheck", "test"]
    install = plan.steps[0]
    assert install.network is True and "npm ci" in " ".join(install.cmd)
    assert "tsc --noEmit" in " ".join(plan.steps[1].cmd)
    assert plan.steps[2].network is False  # tests run network-off


def test_node_install_creates_node_modules_before_stamping(tmp_path: Path) -> None:
    # Guards the zero-dependency install fix (ADR-0032 / H-9): a dep-free `npm install` never
    # creates node_modules/, so a bare `touch node_modules/.stamp` fails with ENOENT and sinks
    # the install step. The script must mkdir -p node_modules before the stamp. Pinned at shape
    # level so it holds in plain `make test` (the docker e2e that first caught it self-skips).
    plan = detect_validation_plan(
        _ws(tmp_path, {"package.json": '{"name":"t","scripts":{"test":"node --test"}}'}),
        install=True,
    )
    install_cmd = " ".join(plan.steps[0].cmd)
    assert "mkdir -p node_modules" in install_cmd
    assert install_cmd.index("mkdir -p node_modules") < install_cmd.index("touch node_modules/")


def test_node_pnpm_lockfile_uses_pnpm(tmp_path: Path) -> None:
    plan = detect_validation_plan(
        _ws(
            tmp_path,
            {
                "package.json": '{"name":"t","devDependencies":{"vitest":"^1"}}',
                "pnpm-lock.yaml": "lockfileVersion: 9\n",
            },
        ),
        install=True,
    )
    install = next(s for s in plan.steps if s.name == "install")
    assert "pnpm install --frozen-lockfile" in " ".join(install.cmd)


def test_node_placeholder_test_script_is_ignored(tmp_path: Path) -> None:
    # npm-init's default `test` placeholder is not a real suite; don't emit a bogus `npm test`
    # — fall back to typecheck-only (still a valid oracle) when no runner is present.
    plan = detect_validation_plan(
        _ws(
            tmp_path,
            {
                "package.json": (
                    '{"name":"t","scripts":'
                    '{"test":"echo \\"Error: no test specified\\" && exit 1"}}'
                ),
                "tsconfig.json": "{}",
            },
        ),
        install=False,
    )
    assert plan.project_type == "node"
    assert [s.name for s in plan.steps] == ["typecheck"]


def test_sql_schema_project_detected(tmp_path: Path) -> None:
    plan = detect_validation_plan(
        _ws(tmp_path, {"schema.sql": "CREATE TABLE t(id int primary key);\n"}), install=False
    )
    assert plan.project_type == "sql"
    assert plan.image == SQL_SANDBOX_IMAGE  # runs on the Postgres sandbox image
    assert [s.name for s in plan.steps] == ["sql-validate"]
    assert plan.steps[0].network is False  # embedded DB, no egress


def test_sql_migrations_project_detected(tmp_path: Path) -> None:
    plan = detect_validation_plan(
        _ws(tmp_path, {"migrations/0001_init.sql": "CREATE TABLE t(id int);\n"}), install=False
    )
    assert plan.project_type == "sql"


def test_sql_only_assertion_tests_not_detected(tmp_path: Path) -> None:
    # A bare tests/*.sql with no schema/migration to apply isn't a validatable SQL project.
    plan = detect_validation_plan(_ws(tmp_path, {"tests/check.sql": "SELECT 1;\n"}), install=False)
    assert plan.project_type != "sql"


def test_python_suite_beats_sql_schema(tmp_path: Path) -> None:
    # A Python app with a SQL schema is a Python project (strong pytest signal > sql sources).
    plan = detect_validation_plan(
        _ws(
            tmp_path,
            {
                "tests/test_app.py": "def test_x(): pass\n",
                "schema.sql": "CREATE TABLE t(id int);\n",
            },
        ),
        install=False,
    )
    assert plan.project_type == "python-pytest"


_CLI = (
    "import argparse\n\n\ndef main():\n    argparse.ArgumentParser().parse_args()\n\n\n"
    'if __name__ == "__main__":\n    main()\n'
)


def test_pytest_project_with_cli_gets_behaviour_smoke(tmp_path: Path) -> None:
    # A tool with a runnable entrypoint gets a "does it start" smoke AFTER the unit tests —
    # the ADR-0025 floor: green units must not hide a CLI that can't even run.
    plan = detect_validation_plan(
        _ws(tmp_path, {"cli.py": _CLI, "tests/test_app.py": "def test_x(): pass\n"}), install=False
    )
    assert plan.project_type == "python-pytest"
    names = [s.name for s in plan.steps]
    assert names == ["pytest", "cli-smoke"]  # smoke runs after the suite
    smoke = plan.steps[-1]
    assert smoke.cmd[-2:] == ["cli.py", "--help"] and smoke.network is False
    assert "behaviour smoke" in plan.reason


def test_package_main_gets_module_smoke(tmp_path: Path) -> None:
    plan = detect_validation_plan(
        _ws(tmp_path, {"pkg/__main__.py": _CLI, "tests/test_x.py": "def test_x(): pass\n"}),
        install=False,
    )
    smoke = next(s for s in plan.steps if s.name == "cli-smoke")
    assert smoke.cmd[-3:] == ["-m", "pkg", "--help"]


# A hand-rolled sys.argv dispatcher (no argparse/click/typer) treats `--help` as an unknown
# command and exits non-zero — so smoking `--help` against it would FALSE-FAIL correct code.
# The gate must NOT emit a smoke step for such a CLI (regression: the MCB-01 park, where a
# fully-tested todo CLI was marked broken purely because `python -m todo --help` exited 1).
_HANDROLLED_CLI = (
    "import sys\n\n\ndef main():\n"
    "    if len(sys.argv) < 2:\n        print('usage: todo <cmd>'); sys.exit(1)\n"
    "    cmd = sys.argv[1]\n    print(cmd)\n\n\n"
    'if __name__ == "__main__":\n    main()\n'
)


def test_handrolled_package_cli_gets_no_smoke(tmp_path: Path) -> None:
    plan = detect_validation_plan(
        _ws(
            tmp_path,
            {"todo/__main__.py": _HANDROLLED_CLI, "tests/test_x.py": "def test_x(): pass\n"},
        ),
        install=False,
    )
    assert plan.project_type == "python-pytest"
    assert "cli-smoke" not in [s.name for s in plan.steps]


def test_handrolled_script_cli_gets_no_smoke(tmp_path: Path) -> None:
    plan = detect_validation_plan(_ws(tmp_path, {"cli.py": _HANDROLLED_CLI}))
    assert "cli-smoke" not in [s.name for s in plan.steps]


# --- False-park regression corpus -------------------------------------------------
# Correct Python project shapes that MUST NOT be false-failed by the validator. Each
# test pins a specific finding from the false-park audit; a green suite is the standing
# guarantee that working, tested code always gets a fair validation plan (not a park).

_TOOL_ONLY_PYPROJECT = (
    '[tool.pytest.ini_options]\naddopts = "-q"\n\n[tool.ruff]\nline-length = 100\n'
)
_INSTALLABLE_PYPROJECT = (
    '[build-system]\nrequires = ["setuptools"]\n\n[project]\nname = "pkg"\nversion = "0.1"\n'
)


def test_tool_only_pyproject_gets_no_editable_install(tmp_path: Path) -> None:
    # A pyproject carrying ONLY [tool.*] config (pytest/ruff) is not an installable
    # package; `pip install -e .` on a flat multi-module layout errors (setuptools
    # flat-layout auto-discovery) and false-parks a correct, fully-tested deliverable.
    plan = detect_validation_plan(
        _ws(
            tmp_path,
            {
                "pyproject.toml": _TOOL_ONLY_PYPROJECT,
                "app.py": "def f():\n    return 1\n",
                "util.py": "def g():\n    return 2\n",
                "tests/test_app.py": "def test_x(): pass\n",
            },
        ),
        install=True,
    )
    assert plan.project_type == "python-pytest"
    assert "install" not in [s.name for s in plan.steps]  # no false-failing `-e .`
    assert "pytest" in [s.name for s in plan.steps]  # still honestly validated


def test_installable_pyproject_still_gets_editable_install(tmp_path: Path) -> None:
    # The fix must NOT suppress a legitimate install: a real package ([build-system]/
    # [project]) still gets `pip install -e .`.
    plan = detect_validation_plan(
        _ws(
            tmp_path,
            {"pyproject.toml": _INSTALLABLE_PYPROJECT, "tests/test_x.py": "def test_x(): pass\n"},
        ),
        install=True,
    )
    install = next(s for s in plan.steps if s.name == "install")
    assert "-e ." in " ".join(install.cmd)


def test_requirements_txt_still_installs(tmp_path: Path) -> None:
    plan = detect_validation_plan(
        _ws(
            tmp_path, {"requirements.txt": "requests\n", "tests/test_x.py": "def test_x(): pass\n"}
        ),
        install=True,
    )
    install = next(s for s in plan.steps if s.name == "install")
    assert "-r requirements.txt" in " ".join(install.cmd)


def test_root_tests_with_fixture_only_tests_dir_not_scoped(tmp_path: Path) -> None:
    # Real tests at the repo root + a tests/ dir holding only conftest/fixtures. The old scoping
    # `pytest tests` would collect 0 (exit 5) and false-fail; config-driven pytest discovers the
    # root tests instead — the plan is not scoped to the test-less tests/ dir.
    plan = detect_validation_plan(
        _ws(
            tmp_path,
            {
                "test_app.py": "def test_x(): pass\n",
                "tests/conftest.py": "import pytest\n",
                "tests/data.py": "FIXTURE = 1\n",
            },
        ),
        install=False,
    )
    pytest_step = next(s for s in plan.steps if s.name == "pytest")
    assert "tests" not in pytest_step.cmd  # not scoped to the test-less tests/ dir


def test_handrolled_cli_mentioning_argparse_in_comment_gets_no_smoke(tmp_path: Path) -> None:
    # A hand-rolled CLI whose source only MENTIONS argparse (in a comment) must not be
    # smoked with --help: _implements_help requires a real import, not a substring.
    src = (
        "import sys\n\n"
        "# Note: intentionally NOT using argparse — zero-dependency startup.\n"
        "def main():\n"
        "    if sys.argv[1:2] == ['status']:\n        print('ok')\n"
        "    else:\n        print('unknown command'); sys.exit(2)\n\n"
        'if __name__ == "__main__":\n    main()\n'
    )
    plan = detect_validation_plan(
        _ws(tmp_path, {"todo/__main__.py": src, "tests/test_x.py": "def test_x(): pass\n"}),
        install=False,
    )
    assert "cli-smoke" not in [s.name for s in plan.steps]


def test_no_entrypoint_no_smoke(tmp_path: Path) -> None:
    # A pure library (no __main__/argparse entrypoint) gets no smoke — conservative, never
    # false-fail a fine deliverable that simply isn't runnable.
    plan = detect_validation_plan(
        _ws(
            tmp_path,
            {
                "lib.py": "def add(a, b):\n    return a + b\n",
                "tests/test_x.py": "def test_x(): pass\n",
            },
        ),
        install=False,
    )
    assert plan.project_type == "python-pytest"
    assert "cli-smoke" not in [s.name for s in plan.steps]


def test_scripts_project_with_cli_gets_smoke(tmp_path: Path) -> None:
    # No test suite → the smoke is the only runtime evidence beyond a syntax check.
    plan = detect_validation_plan(_ws(tmp_path, {"cli.py": _CLI}))
    assert plan.project_type == "python-scripts"
    assert [s.name for s in plan.steps] == ["py-compile", "cli-smoke"]


def test_python_scripts_get_compileall_plus_html(tmp_path: Path) -> None:
    plan = detect_validation_plan(
        _ws(tmp_path, {"app.py": "x = 1\n", "pages/index.html": "<h1>x</h1>"})
    )
    assert plan.project_type == "python-scripts"
    assert [s.name for s in plan.steps] == ["py-compile", "html-check"]
    assert "syntax check only" in plan.reason


def test_static_site(tmp_path: Path) -> None:
    plan = detect_validation_plan(_ws(tmp_path, {"pages/index.html": "<h1>x</h1>"}))
    assert plan.project_type == "static-site"
    assert [s.name for s in plan.steps] == ["html-check"]
    assert plan.steps[0].cmd[:2] == [sys.executable, "-c"]
    assert plan.steps[0].cmd[-1] == "pages/index.html"


def test_unknown_is_unavailable(tmp_path: Path) -> None:
    plan = detect_validation_plan(_ws(tmp_path, {"README.md": "# hi\n"}))
    assert plan.project_type == "unknown"
    assert plan.steps == []
    assert "validation unavailable" in plan.reason


def test_config_data_project_is_parse_validated(tmp_path: Path) -> None:
    plan = detect_validation_plan(_ws(tmp_path, {"config.json": "{}", "settings.toml": "a = 1\n"}))
    assert plan.project_type == "config-data"
    assert [s.name for s in plan.steps] == ["config-parse"]
    assert "config.json" in plan.steps[0].cmd and "settings.toml" in plan.steps[0].cmd
    assert "JSON/YAML/TOML" in plan.reason


def test_python_wins_over_config_data(tmp_path: Path) -> None:
    # A repo with both python and data files is a python project, not config-data.
    plan = detect_validation_plan(_ws(tmp_path, {"app.py": "x = 1\n", "config.json": "{}"}))
    assert plan.project_type == "python-scripts"


def test_html_cap_notes_truncation(tmp_path: Path) -> None:
    files = {f"p/{i:02}.html": "<p>x</p>" for i in range(25)}
    plan = detect_validation_plan(_ws(tmp_path, files))
    assert plan.project_type == "static-site"
    # python -c <program> + the 20 checked files
    assert len(plan.steps[0].cmd) == 3 + 20
    assert "first 20 of 25" in plan.reason


def test_explicit_test_cmd_pins_custom(tmp_path: Path) -> None:
    ws = _ws(tmp_path, {"package.json": "{}"})
    plan = resolve_plan(ws, ["npm", "test"])
    assert plan.project_type == "custom"
    assert plan.steps[0].cmd == ["npm", "test"]
    assert plan.reason == "user-specified test command"
    assert resolve_plan(ws, None).project_type == "node"  # detection falls through to NodePack


# --- the HTML checker program itself ---


def _check(tmp_path: Path, files: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    for rel, content in files.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return subprocess.run(  # noqa: S603 — our own checker program under test
        [sys.executable, "-c", HTML_CHECK_SRC, *args],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_checker_clean_page_with_assets(tmp_path: Path) -> None:
    r = _check(
        tmp_path,
        {
            "index.html": '<html><head><link href="css/style.css"></head>'
            '<body><h1>Hi</h1><script src="js/app.js"></script></body></html>',
            "css/style.css": "body{}",
            "js/app.js": "//x",
        },
        "index.html",
    )
    assert r.returncode == 0
    assert "checked 1 html file(s): OK" in r.stdout


def test_checker_flags_unclosed_tag(tmp_path: Path) -> None:
    r = _check(tmp_path, {"a.html": "<html><body><div><h1>Hi</h1></body></html>"}, "a.html")
    assert r.returncode == 1
    assert "unclosed <div>" in r.stdout


def test_checker_flags_unexpected_close(tmp_path: Path) -> None:
    r = _check(tmp_path, {"a.html": "<p>hello</p></div>"}, "a.html")
    assert r.returncode == 1
    assert "unexpected closing </div>" in r.stdout


def test_checker_flags_missing_asset(tmp_path: Path) -> None:
    r = _check(tmp_path, {"pages/a.html": '<img src="../img/logo.png">'}, "pages/a.html")
    assert r.returncode == 1
    assert "missing local asset: ../img/logo.png" in r.stdout


def test_checker_skips_external_and_anchor_refs(tmp_path: Path) -> None:
    r = _check(
        tmp_path,
        {
            "a.html": '<a href="https://x.dev">x</a><a href="mailto:a@b.c">m</a>'
            '<a href="#top">t</a><img src="data:image/png;base64,xx">'
            '<script src="//cdn.example.com/x.js"></script>'
        },
        "a.html",
    )
    assert r.returncode == 0


def test_checker_tolerates_legal_omitted_closes(tmp_path: Path) -> None:
    r = _check(
        tmp_path,
        {"a.html": "<html><body><ul><li>one<li>two</ul><p>para</body></html>"},
        "a.html",
    )
    assert r.returncode == 0


def test_checker_oversize_is_skip_not_failure(tmp_path: Path) -> None:
    big = "<p>" + ("x" * (513 * 1024)) + "</p>"
    r = _check(tmp_path, {"big.html": big, "ok.html": "<p>hi</p>"}, "big.html", "ok.html")
    assert r.returncode == 0
    assert "skipped (file larger than 512KB)" in r.stdout
    assert "checked 1 html file(s): OK" in r.stdout


# --- run_plan via the SubprocessSandbox (offline) ---


def test_run_plan_static_site_passes(tmp_path: Path) -> None:
    ws = _ws(tmp_path, {"index.html": "<h1>hi</h1>"})
    outcome = run_plan(detect_validation_plan(ws), SubprocessSandbox(ws.root), cwd=ws.root)
    assert outcome.passed is True
    assert "[step html-check: exit code 0]" in outcome.output
    assert outcome.step_results[0]["ok"] is True


def test_run_plan_broken_html_fails(tmp_path: Path) -> None:
    ws = _ws(tmp_path, {"index.html": "<div><h1>hi</h1>"})
    outcome = run_plan(detect_validation_plan(ws), SubprocessSandbox(ws.root), cwd=ws.root)
    assert outcome.passed is False
    assert "unclosed <div>" in outcome.output


def test_run_plan_multi_step_aggregates(tmp_path: Path) -> None:
    ws = _ws(tmp_path, {"app.py": "x = 1\n", "index.html": "<div>broken"})
    outcome = run_plan(detect_validation_plan(ws), SubprocessSandbox(ws.root), cwd=ws.root)
    assert outcome.passed is False  # py-compile ok, html-check fails
    assert "[step py-compile: exit code 0]" in outcome.output
    assert "[step html-check: exit code 1]" in outcome.output
    assert [r["ok"] for r in outcome.step_results] == [True, False]


def test_run_plan_whole_suite_catches_a_failing_root_test(tmp_path: Path) -> None:
    # #45 (ADR-0054) end-to-end, THE headline: a passing suite under tests/ + a FAILING test at the
    # repo ROOT. The old tests/-scoping ran `pytest tests` only, so the root regression shipped
    # green. Config-driven pytest runs the root test too → the run FAILS validation (no false-ship).
    ws = _ws(
        tmp_path,
        {
            "tests/test_ok.py": "def test_ok():\n    assert 1 + 1 == 2\n",
            "test_contract.py": "def test_contract():\n    assert 1 + 1 == 3\n",  # regression
        },
    )
    outcome = run_plan(
        detect_validation_plan(ws, install=False), SubprocessSandbox(ws.root), cwd=ws.root
    )
    assert (
        outcome.passed is False
    )  # the root test executed and failed — the #45 false-ship is closed


def test_run_plan_honors_testpaths_no_false_park_on_examples(tmp_path: Path) -> None:
    # #45 red-team (ADR-0054): config-driven pytest HONORS the repo's own testpaths. A repo that
    # scopes itself to tests/ + a committed examples/ tree that import-errors must PASS (its own
    # suite is green) — NOT false-park. Synthesizing explicit CLI paths would override testpaths and
    # collect the broken example → the exact false-park the red-team caught.
    ws = _ws(
        tmp_path,
        {
            "pyproject.toml": '[tool.pytest.ini_options]\ntestpaths = ["tests"]\n',
            "tests/test_ok.py": "def test_ok():\n    assert True\n",
            "examples/test_demo.py": "import a_module_that_does_not_exist  # noqa\n",
        },
    )
    outcome = run_plan(
        detect_validation_plan(ws, install=False), SubprocessSandbox(ws.root), cwd=ws.root
    )
    assert outcome.passed is True  # testpaths honored → the broken example is out of scope


def test_run_plan_duplicate_basenames_do_not_collide(tmp_path: Path) -> None:
    # #45 red-team (ADR-0054): a tests/ test and a root test sharing a basename (no __init__.py)
    # collide under pytest's default prepend import mode (import file mismatch → collection error →
    # false-park). --import-mode=importlib gives each a path-unique module name → both run cleanly.
    ws = _ws(
        tmp_path,
        {
            "tests/test_utils.py": "def test_a():\n    assert True\n",
            "test_utils.py": "def test_b():\n    assert True\n",
        },
    )
    outcome = run_plan(
        detect_validation_plan(ws, install=False), SubprocessSandbox(ws.root), cwd=ws.root
    )
    assert outcome.passed is True  # no import-mismatch collision


def test_run_plan_empty_is_unavailable(tmp_path: Path) -> None:
    ws = _ws(tmp_path, {"package.json": "{}"})
    outcome = run_plan(detect_validation_plan(ws), SubprocessSandbox(ws.root), cwd=ws.root)
    assert outcome.passed is None
    assert outcome.output.startswith("[no validation available]")
    assert outcome.step_results == []


def test_run_plan_behaviour_smoke_catches_broken_entrypoint(tmp_path: Path) -> None:
    # THE headline (ADR-0025): the code compiles (syntax OK) but the entrypoint can't START —
    # a broken import at module load. compileall passes; the smoke `python cli.py --help`
    # crashes → the run FAILS validation. That's "passes the checks it controls ≠ works".
    ws = _ws(
        tmp_path,
        {
            "cli.py": "import argparse\nimport definitely_missing_module_xyz  # startup crash\n"
            'if __name__ == "__main__":\n    argparse.ArgumentParser().parse_args()\n',
        },
    )
    outcome = run_plan(
        detect_validation_plan(ws, install=False), SubprocessSandbox(ws.root), cwd=ws.root
    )
    assert outcome.passed is False  # compileall ok, but the entrypoint won't start -> caught
    assert "cli-smoke" in outcome.output


def test_run_plan_behaviour_smoke_passes_for_working_cli(tmp_path: Path) -> None:
    ws = _ws(tmp_path, {"cli.py": _CLI})  # a well-formed argparse CLI
    outcome = run_plan(
        detect_validation_plan(ws, install=False), SubprocessSandbox(ws.root), cwd=ws.root
    )
    assert outcome.passed is True  # compiles AND `--help` exits 0


def test_run_plan_config_data_valid_passes(tmp_path: Path) -> None:
    ws = _ws(tmp_path, {"a.json": '{"x": 1}', "b.toml": "k = 2\n"})
    outcome = run_plan(detect_validation_plan(ws), SubprocessSandbox(ws.root), cwd=ws.root)
    assert outcome.passed is True
    assert "OK: parsed" in outcome.output


def test_run_plan_config_data_invalid_fails(tmp_path: Path) -> None:
    ws = _ws(tmp_path, {"broken.json": "{not valid json"})
    outcome = run_plan(detect_validation_plan(ws), SubprocessSandbox(ws.root), cwd=ws.root)
    assert outcome.passed is False
    assert "INVALID" in outcome.output


# --- ADR-0034: every pack declares what a PASS of its plan is actually WORTH ---------
#
# `strength` gates the autonomous reviewer-silence backstop: only "suite" may ship over a
# silent reviewer. A pack that over-claims lets unvalidated code ship unattended, so these
# assertions are load-bearing security, not metadata checks.


def test_pytest_plan_is_a_real_suite(tmp_path: Path) -> None:
    ws = _ws(tmp_path, {"tests/test_a.py": "def test_a():\n    assert True\n"})
    assert detect_validation_plan(ws).strength == "suite"


def test_scripts_plan_is_shallow_not_a_suite(tmp_path: Path) -> None:
    # THE case ADR-0034 closes: a testless Python repo validates with `compileall`. Green
    # means "it parses" — it must never carry an autonomous delivery over a silent reviewer.
    ws = _ws(tmp_path, {"app.py": "x = 1\n"})
    plan = detect_validation_plan(ws)
    assert plan.project_type == "python-scripts"
    assert plan.strength == "shallow"


def test_static_site_and_config_data_plans_are_shallow(tmp_path: Path) -> None:
    html = _ws(tmp_path / "a", {"index.html": "<html><body>hi</body></html>"})
    assert detect_validation_plan(html).strength == "shallow"
    data = _ws(tmp_path / "b", {"conf.json": '{"a": 1}'})
    assert detect_validation_plan(data).strength == "shallow"


def test_unknown_project_declares_no_validation(tmp_path: Path) -> None:
    ws = _ws(tmp_path, {"README.md": "# nothing to validate\n"})
    plan = detect_validation_plan(ws)
    assert plan.project_type == "unknown"
    assert plan.strength == "none"


def test_node_with_a_test_script_is_a_suite_typecheck_alone_is_shallow(tmp_path: Path) -> None:
    with_test = _ws(
        tmp_path / "a",
        {"package.json": '{"scripts": {"test": "vitest run"}}', "index.js": "// x\n"},
    )
    assert detect_validation_plan(with_test).strength == "suite"
    # tsconfig but no test script → only `tsc --noEmit` runs: a typecheck is a parse-class
    # check, not evidence of behaviour.
    typecheck_only = _ws(
        tmp_path / "b",
        {"package.json": "{}", "tsconfig.json": "{}", "index.ts": "export const x = 1;\n"},
    )
    assert detect_validation_plan(typecheck_only).strength == "shallow"


def test_sql_with_assertion_queries_is_a_suite_schema_alone_is_shallow(tmp_path: Path) -> None:
    with_asserts = _ws(
        tmp_path / "a",
        {"schema.sql": "CREATE TABLE t (id int);", "tests/assert.sql": "SELECT 1;"},
    )
    assert detect_validation_plan(with_asserts).strength == "suite"
    # Applying the schema proves the DDL is valid against a real engine — real evidence, but
    # about syntax, not behaviour.
    schema_only = _ws(tmp_path / "b", {"schema.sql": "CREATE TABLE t (id int);"})
    assert detect_validation_plan(schema_only).strength == "shallow"


def test_an_operator_test_command_counts_as_a_suite(tmp_path: Path) -> None:
    ws = _ws(tmp_path, {"app.py": "x = 1\n"})
    plan = resolve_plan(ws, ["pytest", "-q"])
    assert plan.project_type == "custom"
    assert plan.strength == "suite"  # the operator asserted what "validated" means here


def test_dispatch_stamps_the_winning_pack_name(tmp_path: Path) -> None:
    # #81: the plan must remember which pack built it, so the run's output can be handed back to
    # that pack to interpret. Packs don't set it — the registry does, since it is the only thing
    # that knows which pack won the confidence contest.
    cases = {
        "a": ({"test_x.py": "def test_x(): pass\n"}, "python"),
        "b": ({"package.json": '{"scripts": {"test": "vitest run"}}'}, "node"),
        "c": ({"schema.sql": "CREATE TABLE t (id int);"}, "sql"),
        "d": ({"index.html": "<html><body>hi</body></html>"}, "static-site"),
        "e": ({"conf.json": '{"a": 1}'}, "config-data"),
    }
    for sub, (files, expected) in cases.items():
        plan = detect_validation_plan(_ws(tmp_path / sub, files))
        assert plan.pack_name == expected, f"{sub}: {plan.project_type}"
        assert plan.as_dict()["pack_name"] == expected  # survives into RunState


def test_operator_command_and_unknown_have_no_pack_name(tmp_path: Path) -> None:
    # A `--test-cmd` plan has no owning pack; interpret_outcome must fall back rather than
    # mis-attribute the operator's command to whichever pack happens to detect the repo.
    ws = _ws(tmp_path / "a", {"app.py": "x = 1\n"})
    assert resolve_plan(ws, ["pytest", "-q"]).pack_name == ""
    unknown = _ws(tmp_path / "b", {"README.md": "# nothing\n"})
    assert detect_validation_plan(unknown).pack_name == ""


def test_plan_as_dict_stays_json_serializable(tmp_path: Path) -> None:
    # pack_name is a STRING on purpose: the plan is checkpointed into RunState, so it can never
    # carry the pack object or a callable.
    plan = detect_validation_plan(_ws(tmp_path, {"test_x.py": "def test_x(): pass\n"}))
    payload = plan.as_dict()
    assert json.loads(json.dumps(payload)) == payload
