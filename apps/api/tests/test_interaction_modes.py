"""ADR-0101: ask parks writes; accept/auto auto-accept them RECORDED, never silently;
the switch itself is a recorded operator decision; the sanction authority is untouched
(an auto-accept resumes as "autonomous", never "human")."""

from __future__ import annotations

import json
from typing import Any

from mosaera_api.runner._mode import get_mode, set_mode, writes_auto


class _Session:
    def __init__(self, mode: str = "guided") -> None:
        self.mode = mode
        self.run_id = "r1"
        self.audits: list[tuple[str, str]] = []
        self.decisions: list[tuple[str, str, str]] = []
        self._memory = self

    # memory-protocol shims
    def add_decision(self, run_id: str, kind: str, content: str) -> None:
        self.decisions.append((run_id, kind, content))

    def _audit(self, kind: str, detail: str) -> None:
        self.audits.append((kind, detail))

    def _safe(self, fn: Any) -> None:
        fn()


def test_launch_mode_maps_to_the_ladder() -> None:
    assert get_mode(_Session("guided")) == "ask"
    assert get_mode(_Session("autonomous")) == "auto"
    assert get_mode(_Session("high_assurance")) == "ask"
    assert writes_auto(_Session("guided")) is False
    assert writes_auto(_Session("autonomous")) is True


def test_switch_records_decision_and_audit() -> None:
    s = _Session("guided")
    previous = set_mode(s, "accept")
    assert previous == "ask" and get_mode(s) == "accept" and writes_auto(s) is True
    assert ("mode-change", "ask -> accept (operator)") in s.audits
    (_, kind, content) = s.decisions[0]
    assert kind == "mode_change"
    assert json.loads(content) == {"from": "ask", "to": "accept", "actor": "human"}


def test_unknown_mode_is_refused() -> None:
    s = _Session()
    try:
        set_mode(s, "yolo")
        raise AssertionError("must refuse")
    except ValueError:
        pass
    assert get_mode(s) == "ask" and s.decisions == []


def test_auto_accept_never_resumes_as_human() -> None:
    """The sanction authority (tools factory: actor == 'human') must be unreachable
    from an auto-accept — pin the resume actor in the loop source."""
    import inspect

    from mosaera_api.runner import _loop

    src = inspect.getsource(_loop)
    block = src.partition("auto-accepted")[2].partition("continue")[0]
    assert '"actor": "autonomous"' in block and '"actor": "human"' not in block
