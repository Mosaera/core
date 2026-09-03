"""The PM-facing coder capability surface — extracted from ``factory`` (which owns the tool
factory) so that module stays under the god-file ceiling. What the PM is told the coder can do,
so it never plans work the coder can't build.
"""

from __future__ import annotations

# One-line, PM-facing capability descriptions for the coder's tools — the source the PM is told
# about so it never plans work the coder can't do. A test binds these keys to the actual built tool
# set (test_repo_tools) so the two can't drift.
CODER_TOOL_CAPABILITIES: dict[str, str] = {
    "list_files": "List files in the repository (optionally under a subdirectory).",
    "read_file": "Read the contents of a file.",
    "search": "Search file contents with a regular expression.",
    "edit_file": "Replace an exact snippet in an existing file (the preferred edit).",
    "write_file": "Create a new file or fully overwrite an existing one.",
    "run_tests": "Run the project's test/validation suite in the sandbox.",
    # Only advertised to the PM when the admin has enabled deletion (allow_delete).
    "delete_file": "Delete a single existing file (human-approved).",
    # Only advertised when the read-only probe is enabled (enable_exec / coder_repl_enabled).
    "sandbox_exec": "Run a Python snippet in the sandbox (read-only) to observe behaviour.",
}


def describe_coder_capabilities(allow_delete: bool = False, enable_exec: bool = False) -> str:
    """Render the coder's live capability surface for the PM (workspace-free).

    Filters ``CODER_TOOL_CAPABILITIES`` by the coder allowlist so a tool that is
    defined but not granted to the coder is never advertised, then renders through
    the single policy renderer. Pure and cheap — safe to call per PM turn. As the
    coder gains tools (allowlist + description), the PM sees them automatically.

    ``delete_file`` and ``sandbox_exec`` are in the allowlist (ceilings) but are only
    built — and only advertised here — when their flag is set (``allow_delete`` /
    ``enable_exec``), so the PM plans that work only where the instance enables it.
    """
    from mosaera_policies import ROLE_TOOL_ALLOWLIST, render_capabilities

    allowed = set(ROLE_TOOL_ALLOWLIST.get("coder", frozenset()))
    if not allow_delete:
        allowed.discard("delete_file")
    if not enable_exec:
        allowed.discard("sandbox_exec")
    caps = {name: desc for name, desc in CODER_TOOL_CAPABILITIES.items() if name in allowed}
    return render_capabilities(caps)
