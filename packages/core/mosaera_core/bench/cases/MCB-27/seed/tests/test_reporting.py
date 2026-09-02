"""The existing suite. It exercises only the LIVE path, which is the point: a green suite cannot
tell you whether the dead exporter is gone, which is why the removal needs its own oracle."""

from __future__ import annotations

from reporting.cli import report
from reporting.exporters import render_row


def test_render_row_pads_and_truncates() -> None:
    assert render_row(["ab", "cdefghijklmnop"], width=4) == "ab   | cdef"


def test_report_joins_rows() -> None:
    assert report([["a"], ["b"]]) == f"{render_row(['a'])}\n{render_row(['b'])}"
