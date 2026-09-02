"""The wizard's visual language: a mark, a heading, a hint, a progress table.

Borrowed from the shape of a good installer rather than invented: ONE centred column, no borders and
no boxes, a brand mark drawn from a single repeated glyph, and a great deal of empty space. Chrome —
rails, panels, framed logs — reads as an admin panel. Its absence reads as confidence, and it is the
whole difference between a terminal form and something an operator enjoys walking through.
"""

from __future__ import annotations

import re
import textwrap
import time
from dataclasses import dataclass

from mosaera_core.prereqs import Found

#: Console markup, so a renderer can measure what it is about to draw rather than what it wrote.
_TAG = re.compile(r"\[/?[^\]]*\]")

#: The wordmark. Owner-supplied art, kept verbatim.
#:
#: Raw string on purpose — the glyphs include backticks and quotes, and a stray escape would bend a
#: letter without failing anything. The earlier attempts drew the Æ by hand and it read as neither
#: an Æ nor anything else; this spells the name outright and the problem stops existing.
#: The wordmark, uppercase, in Georgia11 — the owner's chosen face, rendered from the real
#: figlet font and verified against their own paste of the mixed-case version.
#:
#: Raw single-quoted: the glyphs contain `"""`, which terminated a triple-quoted string on the
#: first attempt and silently ate half a letter.
_MARK_WIDE = r'''
`7MMM.     ,MMF' .g8""8q.    .M"""bgd      db      `7MM"""YMM  `7MM"""Mq.        db
  MMMb    dPMM .dP'    `YM. ,MI    "Y     ;MM:       MM    `7    MM   `MM.      ;MM:
  M YM   ,M MM dM'      `MM `MMb.        ,V^MM.      MM   d      MM   ,M9      ,V^MM.
  M  Mb  M' MM MM        MM   `YMMNq.   ,M  `MM      MMmmMM      MMmmdM9      ,M  `MM
  M  YM.P'  MM MM.      ,MP .     `MM   AbmmmqMA     MM   Y  ,   MM  YM.      AbmmmqMA
  M  `YM'   MM `Mb.    ,dP' Mb     dM  A'     VML    MM     ,M   MM   `Mb.   A'     VML
.JML. `'  .JMML. `"bmmd"'   P"Ybmmd" .AMA.   .AMMA..JMMmmmmMMM .JMML. .JMM..AMA.   .AMMA.
'''

#: The same name at 66 columns, for terminals too narrow for the full mark. Not a degraded
#: version of it — a different cut, which is what a typeface does when the measure changes.
_MARK_NARROW = r'''
`7MMM.     ,MMF'
  MMMb    dPMM
  M YM   ,M MM  ,pW"Wq.  ,pP"Ybd  ,6"Yb.  .gP"Ya `7Mb,od8 ,6"Yb.
  M  Mb  M' MM 6W'   `Wb 8I   `" 8)   MM ,M'   Yb  MM' "'8)   MM
  M  YM.P'  MM 8M     M8 `YMMMa.  ,pm9MM 8M""""""  MM     ,pm9MM
  M  `YM'   MM YA.   ,A9 L.   I8 8M   MM YM.    ,  MM    8M   MM
.JML. `'  .JMML.`Ybmd9'  M9mmmP' `Moo9^Yo.`Mbmmd'.JMML.  `Moo9^Yo.
'''


def _as_block(art: str) -> str:
    """Pad every line to the widest, so the logotype centres as ONE shape.

    `text-align: center` centres each line independently, so a row shorter than its neighbours
    drifts sideways and the letterforms stop lining up — the top two rows of this mark are much
    shorter than the rest, and it read as broken.
    """
    lines = art.strip("\n").splitlines()
    width = max(len(line) for line in lines)
    return "\n".join(line.ljust(width) for line in lines)


#: Below this the full mark cannot be drawn without wrapping, and a wrapped logotype is worse than
#: a smaller one. Measured, not guessed: the wide art is 89 columns and the stage adds a margin.
_WIDE_MIN_COLUMNS = 93


#: Below this many ROWS the wordmark is not drawn at all. The header is the one fixed-height region
#: on screen, so on a short terminal it is the thing eating the choices — and a logotype the
#: operator cannot act on is worth less than the list they can.
_ART_MIN_ROWS = 34

#: And below this, even the strapline goes. What survives is the ribbon: where you are in the flow.
_TAGLINE_MIN_ROWS = 28


def mark_for(columns: int, rows: int = 999) -> str:
    """The widest wordmark this terminal can hold — in BOTH axes.

    Width was the only axis considered, so a 24-row terminal (still the default almost everywhere)
    gave 17 of its rows to a header and pushed the choice list off the bottom of the screen. With no
    key bound to scrolling, that is a wizard the operator can look at and not use.
    """
    if rows < _ART_MIN_ROWS:
        return ""
    return _as_block(_MARK_WIDE if columns >= _WIDE_MIN_COLUMNS else _MARK_NARROW)


def header_rows(rows: int) -> int:
    """How tall the header may be on a terminal this size.

    Measured, not guessed: 3 rows of top padding + 7 of art + 4 for the strapline and its padding +
    4 for the ribbon and its padding.
    """
    if rows < _TAGLINE_MIN_ROWS:
        # THREE, not two: one row of padding, the ribbon, and the ribbon's own padding. At two the
        # ribbon was clipped away entirely and a short terminal lost its "where am I" indicator.
        return 3
    if rows < _ART_MIN_ROWS:
        return 6  # strapline + ribbon
    return 17


def show_tagline(rows: int) -> bool:
    return rows >= _TAGLINE_MIN_ROWS


def compact(rows: int) -> bool:
    """Whether to drop the vertical padding.

    Below the strapline threshold the padding is what pushes the choice list off the bottom — the
    rows that read as considered spacing on a full window are the difference between usable and
    unusable on a short one.
    """
    return rows < _TAGLINE_MIN_ROWS


#: The default, for callers that do not know the width yet.
MARK = _as_block(_MARK_NARROW)

#: THE PALETTE, in markup form.
#:
#: LITERAL HEX, NOT `[$dim]`. Textual resolves a `$name` inside content markup against the THEME's
#: variables, not against the ones this stylesheet declares — so `[$dim]`, `[$alarm]` and `[$faint]`
#: silently rendered at the widget's own colour and did nothing at all. Every "dimmed" label in this
#: file had been drawing at full brightness since the first one, which is why the screens read as a
#: wall of equally-important text, and an error toast was never once red. `[$accent]` worked only
#: because `$accent` happens to be a name the theme knows.
#:
#: These four must equal the stylesheet's own `$accent`/`$dim`/`$alarm`/`$faint`, and a test says
#: so: two sources for one palette is exactly how the drift above went unnoticed.
ACCENT = "#ffaf00"
DIM = "#6b6b6b"
ALARM = "#ff6b6b"
FAINT = "#4e4e52"


#: THE MEASURE — the width of the imaginary box every screen draws itself inside.
#:
#: There is no border and there will not be one. What makes a screen read as a block is that its
#: lines share edges: the prose wraps to this, the tables end on it, and a two-column row puts its
#: value hard against it. Before this every renderer chose its own widths — the note column was
#: padded to 24, a prerequisite's detail ran straight on after the label, the access rows were
#: spaced with a hand-counted run of spaces — so no two screens agreed where the right-hand edge
#: was, and nothing looked deliberate.
MEASURE = 84


def measure_for(columns: int) -> int:
    """The box on a terminal this wide. Narrower windows narrow the box; they do not clip it."""
    return min(MEASURE, max(columns - 4, 20))


def visible(text: str) -> str:
    """`text` without its console markup, for anything that needs to know how wide it will draw."""
    return _TAG.sub("", text)


def split(left: str, right: str, width: int, *, gap: int = 2) -> str:
    """One row of the box: `left` at the left edge, `right` ending exactly on the right one.

    Padding is computed on the VISIBLE text and the markup left where it is. Computing it on the
    marked-up string is the bug this replaces — `f"{note:<24}"` counted a dim-marked "creating" as
    22 characters, so the column moved whenever the colour did and only lined up by accident.

    When the two do not fit, the right-hand value wins its space and the left is trimmed: an address
    or an elapsed time is the fact being read, and half of one is worth nothing.
    """
    room = max(width - len(visible(right)) - (gap if right else 0), 0)
    if len(visible(left)) > room:
        left = _trim(left, room)
    return f"{left}{' ' * max(width - len(visible(left)) - len(visible(right)), 0)}{right}"


def note_under(text: str, width: int, indent: str = "   ") -> str:
    """The dim line beneath a row — a prerequisite's purpose, an uninstall entry's cost.

    WRAPPED to the box, not cut. It was cut, and the first thing to go over the edge was the volume
    name in "Delete all project data" — the one string on that screen an operator has to be able to
    match against `docker volume ls` before agreeing to lose it.
    """
    lines = textwrap.wrap(text, max(width - len(indent), 8)) or [""]
    return "\n".join(f"{indent}[{FAINT}]{line}[/]" for line in lines)


def _trim(text: str, room: int) -> str:
    """`text` cut to `room` visible columns, with an ellipsis and its markup left closed.

    Cutting the raw string would slice through a colour tag and leave the rest of the screen
    painted in whatever the fragment happened to mean.
    """
    if room <= 0:
        return ""
    kept: list[str] = []
    depth = seen = index = 0
    while index < len(text) and seen < room - 1:
        tag = _TAG.match(text, index)
        if tag:
            depth += -1 if tag.group().startswith("[/") else 1
            kept.append(tag.group())
            index = tag.end()
            continue
        kept.append(text[index])
        seen += 1
        index += 1
    return "".join(kept) + "…" + "[/]" * depth


#: The select cursor. Named so the one ambiguous-looking glyph in the file is declared once.
_CURSOR = "\u276f"

#: Braille dots, which advance without the width of a character changing — a spinner that reflows
#: the line it sits in draws the eye to the wrong thing.
SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


def spinner_line(tick: int, line: str) -> str:
    """One frame of the spinner, with whatever the command last said beside it.

    The frame and the text share ONE widget: two would repaint independently and the eye would read
    the drift between them as stutter. And a spinner matters most where there is no text at all —
    `compose up -d --wait` prints nothing for tens of seconds, and a screen with no motion during
    that is indistinguishable from a wedged one.

    Used only where there is NO task list — see `timers.paint_status`. Beside one, the running row
    is already spinning in the marker column and this one sits three to its right.
    """
    return f"[{ACCENT}]{SPINNER[tick % len(SPINNER)]}[/]  [{DIM}]{line}[/]"


#: What a task is doing. There is no fifth state and no percentage — see `task_list`.
WAITING, RUNNING, DONE, FAILED = "waiting", "running", "done", "failed"


@dataclass(frozen=True)
class Row:
    """One task: what is being done, how it is going, and what that cost so far."""

    label: str
    state: str = WAITING
    note: str = ""
    #: Seconds the task took, once it is over.
    seconds: float = 0.0
    #: `time.monotonic()` when it started, for a task still running. The spinner tick recomputes the
    #: elapsed from this, so the number counts up — which is the motion a bar was pretending to
    #: supply while jumping straight from empty to full.
    started: float = 0.0

    @property
    def done(self) -> bool:
        return self.state == DONE


#: The tessellation the name points at. Three tones on a short cycle, shifted by an odd stride each
#: row so the pattern never lines up into columns — a repeating tile with an even stride reads as
#: vertical stripes, which is a curtain, not a mosaic.
_TONES = "▓▒░"
_STRIDE = 2

#: Tile size, in cells. Big enough to read as a laid surface at a glance rather than as noise.
_TILE_W, _TILE_H = 6, 3


def mosaic(width: int, height: int) -> str:
    """A mosaic field to sit behind the content at very low opacity.

    A real image would need sixel or the kitty protocol and would render as garbage everywhere else;
    block glyphs render in any terminal that can already draw this wizard.
    """
    lines: list[str] = []
    for row in range(height):
        band = row // _TILE_H
        # The odd stride is what stops the tiles lining up into columns — an even one draws a
        # curtain, not a mosaic.
        cells = [
            _TONES[((col // _TILE_W) + band * _STRIDE + band // 2) % len(_TONES)]
            for col in range(width)
        ]
        lines.append("".join(cells))
    return "\n".join(lines)


#: The marker per task state. `▰`/`▱` are the same tiles the step ribbon uses, so "filled means
#: finished" means one thing everywhere in this wizard.
_MARK = {
    DONE: f"[{ACCENT}]▰[/]",
    WAITING: f"[{DIM}]▱[/]",
    FAILED: f"[{ALARM}]✕[/]",
}


def task_list(rows: list[Row], tick: int = 0, width: int = MEASURE) -> str:
    """The tasks as one block: a marker, what it is doing, and how long it has taken.

    NO PERCENTAGE, and no bar. There was one, and it was fiction: every caller only ever reported 0
    and then 100, so a bar that promised proportional progress jumped straight from empty to full.
    A bar needs a denominator; none of these tasks has one. Elapsed time is the honest measure, and
    the spinner on the running row carries the motion the bar was pretending to.

    Rendered as text rather than widgets so the whole block repaints atomically — a column of live
    widgets updating one at a time shimmers, and an operator reads shimmer as instability.
    """
    if not rows:
        return ""
    pad = max(len(r.label) for r in rows)
    out: list[str] = []
    for row in rows:
        mark = _MARK.get(row.state) or f"[{ACCENT}]{SPINNER[tick % len(SPINNER)]}[/]"
        took = row.seconds or (time.monotonic() - row.started if row.started else 0.0)
        elapsed = f"[{DIM}]{took:5.1f}s[/]" if took else ""
        note = f"[{DIM}]{row.note}[/]" if row.state != FAILED else f"[{ALARM}]{row.note}[/]"
        out.append(split(f"{mark}  {row.label:<{pad}}   {note}", elapsed, width))
    return "\n".join(out)


def choice_list(options: list[str], selected: int) -> str:
    """A select list: a cursor on the current line, everything else dimmed back.

    Numbers are deliberately absent. A numbered menu asks the operator to translate an intention
    into an index; a cursor does not.
    """
    out: list[str] = []
    for i, option in enumerate(options):
        # Only the HEAD line takes the treatment. An option can carry its own lines beneath it — an
        # uninstall entry's cost, wrapped and fainter — and wrapping the whole thing in one tag
        # flattened those back up to the label's own weight, which is what made that list read as a
        # block of undifferentiated text.
        head, _, rest = option.partition("\n")
        marked = f"[{ACCENT}]{_CURSOR}[/] {head}" if i == selected else f"  [{DIM}]{head}[/]"
        out.append(f"{marked}\n{rest}" if rest else marked)
    return "\n".join(out)


def step_ribbon(count: int, current: int) -> str:
    """The flow's spine: one tile per step, everything up to and including the current one filled.

    Every step stays visible. A ribbon that dropped what was done would show only what is left,
    which tells an operator how much further to go and never how far they have come.

    NO LABEL. It used to append the step's name, which then sat directly above a heading naming the
    same step — and the heading says it better (`Database — port 5432`, not `Database`).
    """
    return " ".join(f"[{ACCENT}]▰[/]" if i <= current else f"[{DIM}]▱[/]" for i in range(count))


def toast(message: str, *, error: bool) -> str:
    """A notification, marked as one.

    It used to render as a centred line of coloured prose sitting between the detail line and the
    key hints, where it read as one more instruction rather than as something that had just
    happened.
    """
    colour = "$alarm" if error else "$accent"
    return f"[{colour}]▌[/] {message}"


def save_shot(app: object) -> tuple[str, bool]:
    """Write the current screen to an SVG in the home directory. Returns the line to show and
    whether it failed.

    A full-screen application leaves nothing in the scrollback, so "what did you see?" is otherwise
    unanswerable. A read-only home or a full disk must not take the wizard down with it.
    """
    from pathlib import Path

    try:
        path = app.save_screenshot(path=str(Path.home()))  # type: ignore[attr-defined]
    except Exception as exc:
        return f"Could not save a screenshot: {exc}", True
    return f"Screenshot saved to {path}", False


def failure_reason(code: int) -> str:
    """A negative status from the runner, in words. See `steps.FAILURE_REASON`."""
    from mosaera_api.setup.steps import FAILURE_REASON

    return FAILURE_REASON.get(code, f"exit {code}")


def machine_table(found: list[Found], width: int = MEASURE) -> str:
    """Every prerequisite, present ones included, with what it is FOR.

    Listing only the gaps tells an operator what to do; listing all of it tells them what shape
    their machine is in, which is what they were actually asking.
    """
    label_width = max(len(f.prereq.label) for f in found)
    blocks: list[str] = []
    for f in found:
        mark = f"[{ACCENT}]▰[/]" if f.present else f"[{DIM}]▱[/]"
        # What was FOUND goes to the right edge — the column an operator scans down to see which
        # rows are answered — and the label stays at the left edge with the purpose beneath it.
        detail = f"[{DIM}]{f.detail}[/]" if f.present else f"[{ACCENT}]{f.detail}[/]"
        blocks.append(
            split(f"{mark}  {f.prereq.label:<{label_width}}", detail, width)
            + "\n"
            # Indented to the LABEL's own column, not past it: hung out under the detail column the
            # purpose floated in the middle of the row with nothing above it to belong to.
            + note_under(f.prereq.purpose, width)
        )
    # A blank line between entries. Four two-line rows stacked tight read as one paragraph, and the
    # eye has to work out where each prerequisite starts.
    return "\n\n".join(blocks)


def gap_label(found: Found) -> str:
    """The row that offers to close one gap — with the verb the PLAN chose.

    Hardcoding "Install" meant a Docker that was merely stopped was offered
    "Install Docker  curl … | sudo sh": re-download the vendor script in order to start a service.
    """
    plan = found.plan
    if not plan.runnable:
        return f"{found.prereq.label} — read {plan.docs}"
    # `offer` when the action is not named after the prerequisite: on macOS the Docker gap is
    # closed by installing Colima, and "Install Docker   brew install colima …" would name one
    # product while running another.
    return f"{plan.verb} {plan.offer or found.prereq.label}   {plan.steps[0].command}"


def uninstall_labels(removable: list, chosen: set[int], width: int = MEASURE) -> list[str]:
    """The uninstall list: a tick, what goes, and what it costs — with the irreversible one saying
    so on its own line rather than in a footnote.

    The two trailing rows are actions, not items. "Go back to continue" was a contradiction: the
    row that leaves and the row that proceeds must not be the same row.
    """
    out: list[str] = []
    for i, item in enumerate(removable):
        tick = f"[{ACCENT}]▰[/]" if i in chosen else f"[{DIM}]▱[/]"
        # The warning goes to the box's right edge rather than trailing the label, so the one
        # irreversible row is findable by shape and not only by reading every line to the end.
        # `width - 2` because `choice_list` indents every option by two columns.
        warn = f"[{ACCENT}](no undo)[/]" if item.destructive else ""
        head = split(f"{tick} {item.label}", warn, width - 2)
        # A blank row after each entry. Three two-line entries stacked tight read as one paragraph
        # of running text, and the eye has to work out where each row starts before it can decide
        # anything — the same reason `machine_table` separates its own entries.
        out.append(head + "\n" + note_under(item.detail, width - 2, "     ") + "\n")
    proceed = f"Remove the {len(chosen)} selected" if chosen else f"[{DIM}]Nothing selected[/]"
    # The last entry's trailing blank is the separator before the two ACTION rows, which belong
    # together and not spread apart like the items.
    return [*out, proceed, "Cancel — leave everything as it is"]
