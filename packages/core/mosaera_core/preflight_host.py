"""What this MACHINE has installed — the host half of the readiness probe.

Split from `preflight.py` at the 500-line ceiling, along the seam the module already had: these
checks ask what is installed on the box, while the rest asks what can serve a model. They are also
the only ones that shell out, so keeping them together keeps the one place that runs a host command
small enough to read in a sitting.

REPORT-ONLY, like everything in the probe: nothing here builds an image or installs a package. Every
failure instead carries a `fix` — a command the operator can paste, never prose.
"""

from __future__ import annotations

import subprocess

from mosaera_core.config import Settings
from mosaera_core.preflight_types import _PROBE_TIMEOUT, Check


def _run(argv: list[str], timeout: float = _PROBE_TIMEOUT) -> tuple[int, str]:
    """A bounded host command. Returns ``(code, output)``; ``-1`` when it could not run at all."""
    try:
        proc = subprocess.run(  # noqa: S603 — argv is built here, never from user input
            argv, capture_output=True, text=True, timeout=timeout, check=False
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return -1, str(exc)
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def _install_command(pkg: str) -> str:
    """A pasteable install command for THIS machine, from the one prerequisite table.

    Delegates to `mosaera_core.prereqs` rather than deriving a command from a name. Deriving is what
    produced `apt-get install -y node` — a package that is an amateur packet radio program — and a
    Docker installer offered for every tool on any distribution we did not recognise.
    """
    from mosaera_core.prereqs import PREREQS, detect_platform, plan_for

    prereq = next((p for p in PREREQS if p.key == pkg or p.label.lower() == pkg), None)
    if prereq is None:
        return ""
    plan = plan_for(prereq, detect_platform())
    return plan.steps[0].command if plan.steps else f"see {plan.docs}" if plan.docs else ""


def _repair_command(output: str) -> str:
    """How to make an installed-but-unusable Docker answer, on THIS machine.

    This was a literal — `sudo systemctl start docker && sudo usermod -aG docker $USER  # then log
    out and back in` — emitted verbatim on macOS, which has no systemctl, and on WSL, where the
    re-login does nothing (`wsl --shutdown` does). The reason is classified by the same matcher the
    prerequisite probe uses, so the two cannot drift apart.
    """
    from mosaera_core.prereqs import PREREQS, classify_docker_failure, detect_platform, plan_for

    prereq = next(p for p in PREREQS if p.key == "docker")
    plan = plan_for(prereq, detect_platform(), classify_docker_failure(output))
    steps = " && ".join(step.command for step in plan.steps)
    if steps and plan.note:
        return f"{steps}  # {plan.note}"
    return steps or plan.note or (f"see {plan.docs}" if plan.docs else "")


def check_docker(settings: Settings) -> Check:
    """Is the Docker daemon reachable? Every tool command a run issues executes in a container."""
    binary = settings.docker_bin
    code, out = _run([binary, "info", "--format", "{{.ServerVersion}}"])
    if code == 0:
        return Check("docker", "Docker daemon", "ok", f"reachable (server {out.splitlines()[0]})")
    if code == -1:
        return Check(
            "docker",
            "Docker daemon",
            "fail",
            f"'{binary}' is not installed or not on PATH",
            fix=_install_command("docker"),
        )
    return Check(
        "docker",
        "Docker daemon",
        "fail",
        f"'{binary}' is installed but the daemon did not answer: {out.splitlines()[0][:160]}"
        if out
        else f"'{binary}' is installed but the daemon did not answer",
        fix=_repair_command(out),
    )


def _image_tags(settings: Settings) -> dict[str, str]:
    """``tag -> the Dockerfile that builds it``. The scan image is separate from the sandbox
    images because it runs the security scanners on a different toolchain."""
    return {
        settings.sandbox_image: "infra/docker/sandbox.Dockerfile",
        "mosaera-sandbox-node:dev": "infra/docker/sandbox-node.Dockerfile",
        "mosaera-sandbox-sql:dev": "infra/docker/sandbox-sql.Dockerfile",
        settings.scan_image: "infra/docker/scan.Dockerfile",
    }


def check_images(settings: Settings) -> Check:
    """Are the sandbox + scanner images built? `make up` builds them on first run, so a
    hand-started API is the case this catches."""
    missing: list[tuple[str, str]] = []
    for tag, dockerfile in _image_tags(settings).items():
        code, _ = _run([settings.docker_bin, "image", "inspect", tag])
        if code != 0:
            missing.append((tag, dockerfile))
    if not missing:
        return Check("images", "Sandbox images", "ok", "all four images are present")
    fix = " && ".join(f"docker build -f {dockerfile} -t {tag} ." for tag, dockerfile in missing)
    names = ", ".join(tag for tag, _ in missing)
    return Check("images", "Sandbox images", "fail", f"missing: {names}", fix=fix)
