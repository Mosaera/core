"""The wizard's off-UI-thread workers, split out of `app.py` (the 500-line ratchet).

Each is a thin `@work(thread=True)` delegator: the slow half of a step — a machine probe, an image
build, a database bring-up, a removal, a server launch — runs on a worker thread so the UI loop
keeps painting and answering keys, and `workers.guarded` funnels every failure back to a screen
that names the log rather than a traceback over the wizard. Kept as a mixin so `SetupApp` still
owns them by inheritance; the modules below type-hint `SetupApp` under `TYPE_CHECKING` only, so
importing them here creates no cycle.
"""

from __future__ import annotations

from textual import work

from mosaera_api.setup import build_flow, done_flow, enter_steps, uninstall_flow, workers


class SetupWorkers:
    """Mixed into `SetupApp`; every method here runs on a worker thread."""

    @work(thread=True, exit_on_error=False)
    def _probe_worker(self) -> None:
        workers.guarded(
            self,  # type: ignore[arg-type]
            lambda: self.call_from_thread(  # type: ignore[attr-defined]
                enter_steps.probed, self, enter_steps.configured(self)  # type: ignore[arg-type]
            ),
            "welcome",
        )

    @work(thread=True, exit_on_error=False)
    def _images_worker(self) -> None:
        workers.guarded(self, lambda: build_flow.build_images_only(self), "configured")  # type: ignore[arg-type]

    @work(thread=True, exit_on_error=False)
    def _database_worker(self) -> None:
        workers.guarded(self, lambda: build_flow.bundled_database(self), "database")  # type: ignore[arg-type]

    @work(thread=True, exit_on_error=False)
    def _uninstall_worker(self) -> None:
        workers.guarded(self, lambda: uninstall_flow.work(self), "uninstall")  # type: ignore[arg-type]

    @work(thread=True, exit_on_error=False)
    def _launch_worker(self) -> None:
        workers.guarded(self, lambda: done_flow.bring_up(self), "done")  # type: ignore[arg-type]
