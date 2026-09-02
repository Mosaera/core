from langchain_core.tools import tool
from mosaera_policies import ROLE_TOOL_ALLOWLIST, render_capabilities, scoped_tools


@tool
def read_file(path: str) -> str:
    """Read a file."""
    return path


@tool
def write_file(path: str, content: str) -> str:
    """Write a file."""
    return path


@tool
def launch_missiles() -> str:
    """A tool no allowlist should ever include."""
    return "boom"


ALL = [read_file, write_file, launch_missiles]


def test_unknown_role_gets_nothing() -> None:
    assert scoped_tools("intern", ALL) == []


def test_pm_cannot_write() -> None:
    names = {t.name for t in scoped_tools("pm", ALL)}
    assert "read_file" in names
    assert "write_file" not in names


def test_coder_scope() -> None:
    names = {t.name for t in scoped_tools("coder", ALL)}
    assert names == {"read_file", "write_file"}
    # The coder may also make surgical edits (preferred over whole-file writes).
    assert "edit_file" in ROLE_TOOL_ALLOWLIST["coder"]


def test_unlisted_tool_never_passes() -> None:
    for role in ROLE_TOOL_ALLOWLIST:
        assert "launch_missiles" not in {t.name for t in scoped_tools(role, ALL)}


def test_reviewer_is_read_only() -> None:
    # The reviewer reads the repo to verify acceptance, but never writes.
    names = {t.name for t in scoped_tools("reviewer", ALL)}
    assert "read_file" in names
    assert "write_file" not in names
    assert "launch_missiles" not in names


def test_tester_scope_writes_and_edits_tests_but_not_source() -> None:
    # Separation of duties (ADR-0013) + up-front validate/repair (#54, ADR-0058): the tester reads,
    # WRITES and EDITS test files, and runs tests — so the Proctor can repair an over-strict/wrong
    # pre-existing test BEFORE the coder runs. It still has NO delete_file (deletion drops a
    # requirement wholesale and can't be quality-checked), and both write_file AND edit_file are
    # confined to tests/ by build_repo_tools' write_prefix — it can never modify source.
    scope = ROLE_TOOL_ALLOWLIST["tester"]
    assert scope == {"list_files", "read_file", "search", "edit_file", "write_file", "run_tests"}
    assert "edit_file" in scope
    assert "delete_file" not in scope
    names = {t.name for t in scoped_tools("tester", ALL)}
    assert names == {"read_file", "write_file"}  # of the sample ALL, only these are in scope


def test_critic_is_read_only() -> None:
    # The held-out critic / Judge (#60, ADR-0065) reads the repo to confirm a specific spec
    # requirement is unmet before it vetoes, but never writes or runs — same read-only capability
    # contract as the reviewer. Its verdict can only downgrade ship->park at the gate.
    scope = ROLE_TOOL_ALLOWLIST["critic"]
    assert scope == {"list_files", "read_file", "search"}
    names = {t.name for t in scoped_tools("critic", ALL)}
    assert "read_file" in names
    assert "write_file" not in names
    assert "launch_missiles" not in names


def test_render_capabilities_lists_tools_and_states_the_limit() -> None:
    text = render_capabilities({"edit_file": "Edit a file.", "run_tests": "Run the tests."})
    # every tool name + its description is present, positive-only...
    assert "edit_file" in text and "Edit a file." in text
    assert "run_tests" in text and "Run the tests." in text
    # ...and the implicit-limit framing makes "anything else is off-limits" explicit.
    assert "ONLY" in text and "OUT OF CAPABILITY" in text


def test_render_capabilities_handles_empty() -> None:
    # Deny-by-default: no tools → an honest "nothing available", still framed.
    text = render_capabilities({})
    assert "no tools available" in text
    assert "OUT OF CAPABILITY" in text
