"""Mosaera governance: deny-by-default tool allowlist and human approval gate.

This package is CODEOWNERS-protected. Changes here alter what agents are
allowed to do — treat every diff as security-sensitive (see AGENTS.md).
"""

from mosaera_policies.allowlist import (
    ALLOWED_SCANNERS,
    ROLE_TOOL_ALLOWLIST,
    render_capabilities,
    scanner_allowed,
    scoped_tools,
)
from mosaera_policies.approval import (
    GATED_ACTIONS,
    ApprovalDecision,
    parse_decision,
    request_approval,
)
from mosaera_policies.gate import (
    REASON_CLASS,
    GateDecision,
    ReasonClass,
    autonomous_resolution,
    evaluate_gate,
    reason_class,
    reasons_of_class,
)

__all__ = [
    "ALLOWED_SCANNERS",
    "GATED_ACTIONS",
    "REASON_CLASS",
    "ROLE_TOOL_ALLOWLIST",
    "ApprovalDecision",
    "GateDecision",
    "ReasonClass",
    "autonomous_resolution",
    "evaluate_gate",
    "parse_decision",
    "reason_class",
    "reasons_of_class",
    "render_capabilities",
    "request_approval",
    "scanner_allowed",
    "scoped_tools",
]
