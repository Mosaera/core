"""Where a run's artefacts live on disk — the five directories derived from ``home``.

Split out of ``_settings`` on 2026-08-07 when that file hit the 500-line ceiling and a one-line
knob could not be added. The paths are a cohesive slice: five one-line properties over a single
field, with no dependency on any other setting, so they read the same in either place. As a mixin
rather than free functions so `settings.workspaces_dir` keeps working everywhere it is already
used — every caller is unchanged.
"""

from __future__ import annotations

from pathlib import Path


class RunPaths:
    """The ``home``-derived directories. Mixed into ``Settings``; ``home`` comes from there."""

    home: Path

    @property
    def workspaces_dir(self) -> Path:
        return self.home / "workspaces"

    @property
    def projects_dir(self) -> Path:
        return self.home / "projects"

    @property
    def reports_dir(self) -> Path:
        return self.home / "reports"

    @property
    def runs_dir(self) -> Path:
        return self.home / "runs"

    @property
    def uploads_dir(self) -> Path:
        return self.home / "uploads"
