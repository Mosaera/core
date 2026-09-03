"""The sandbox images: which exist, whether they match their recipe, and how to build one.

Split out of `steps.py` at the 500-line ceiling, and cohesive on its own — everything here answers
one question, "is the image on this machine the one this checkout describes".

That question was first answered with CLOCKS and it did not work: comparing the image's `.Created`
against the Dockerfile's mtime meant `git pull` made every image look stale, the wizard rebuilt,
docker served the build from cache in under a second, and a cached rebuild leaves `.Created`
exactly as it was — so the image stayed stale and the wizard offered to build it again, forever.
It is answered with CONTENT now: the recipe's hash is stamped on the image as a label at build
time, and a rebuild that changes a label produces a different image even when every layer is
cached. The thing compared is the thing the build writes.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from mosaera_core.config import Settings
from mosaera_core.preflight_host import _image_tags, _run


@dataclass(frozen=True)
class Image:
    """A sandbox/scanner image and the Dockerfile that builds it."""

    tag: str
    dockerfile: str
    present: bool


def survey_images(settings: Settings) -> list[Image]:
    """Which of the four images exist. Uses the same `tag -> Dockerfile` map the readiness check
    reads, so the wizard cannot build a different set from the one `doctor` reports on."""
    out: list[Image] = []
    for tag, dockerfile in _image_tags(settings).items():
        code, labelled = _run(
            [
                settings.docker_bin,
                "image",
                "inspect",
                "--format",
                f'{{{{index .Config.Labels "{RECIPE_LABEL}"}}}}',
                tag,
            ]
        )
        # `index` on a missing key prints "<no value>", which is not a hash and so reads as stale.
        present = code == 0 and not _image_is_stale(labelled, dockerfile)
        out.append(Image(tag=tag, dockerfile=dockerfile, present=present))
    return out


#: The Dockerfile's content hash, stamped on the image it builds.
RECIPE_LABEL = "dev.mosaera.recipe"


def recipe_hash(dockerfile: str) -> str:
    """A hash of the recipe, or "" if it cannot be read."""
    try:
        return hashlib.sha256(Path(dockerfile).read_bytes()).hexdigest()[:16]
    except OSError:
        return ""


def _image_is_stale(labelled: str, dockerfile: str) -> bool:
    """Whether this image was built from a DIFFERENT recipe than the one on disk.

    Compares CONTENT, after comparing clocks did not work. The first version read the image's
    `.Created` against the Dockerfile's mtime, and `git pull` rewrites mtimes — so after any update
    the image looked stale, the wizard rebuilt it, DOCKER SERVED THE BUILD FROM CACHE IN UNDER A
    SECOND, and a cached rebuild leaves `.Created` exactly as it was. The image was therefore still
    stale, and the wizard offered to build it again, forever. Reported as "two of them said they
    were built in under one second" and "it still says two sandboxes need building". Measured:
    910ms, `.Created` unchanged.

    A label cannot get stuck that way. It is part of the image config, so a rebuild that changes it
    produces a different image even when every layer is cached — the thing being compared is the
    thing the build actually writes.

    An image with NO label predates this and cannot be judged, so it is treated as stale: one
    rebuild, once, and then it carries its recipe like the rest.
    """
    current = recipe_hash(dockerfile)
    if not current:
        return False  # unreadable recipe: rebuilding on a guess costs minutes and proves nothing
    return labelled.strip() != current


def build_image_argv(settings: Settings, image: Image) -> list[str]:
    """The build, as argv — never a shell string. The repo root is the context, exactly as
    `dev-up.sh` does it."""
    return [
        settings.docker_bin,
        "build",
        "-f",
        image.dockerfile,
        "-t",
        image.tag,
        # STAMPED AT BUILD TIME, which is what makes the freshness check clearable: a cached
        # rebuild with a new label still produces a new image, where a cached rebuild alone leaves
        # `.Created` untouched and the old mtime comparison permanently unsatisfied.
        "--label",
        f"{RECIPE_LABEL}={recipe_hash(image.dockerfile)}",
        ".",
    ]
