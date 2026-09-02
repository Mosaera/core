/* Charter constraints as ROWS, not a paragraph.
 *
 * The charter stores `constraints` as one free-text column, so the console rendered 2.4KB of prose
 * behind a "Constraints" disclosure — unreadable, uncountable, and impossible to point at (owner,
 * 2026-08-22: "the constraints for the charter should be structured data not a paragraph").
 *
 * The honest structured store DOES exist — ratified clauses, `GET /projects/{id}/clauses`, with
 * `binds`/`value_kind`/`when`/`because`/`provenance` per clause — but it is EMPTY on every live
 * project today (checked: 0 clauses on the instance this was designed against). Rendering it
 * would be a permanently blank panel claiming rigour the data does not have.
 *
 * So this parses what the PM actually writes. The stored text is an enumerated list by
 * construction ("1. All monetary values must use decimal.Decimal…"), and splitting on that
 * enumeration is deterministic — no model call, no inference, no reordering. When the text is NOT
 * enumerated the parser says so by returning a single row, and the caller renders the prose it was
 * given rather than inventing structure that is not there.
 *
 * When clauses become populated they should supersede this, and a row here is deliberately shaped
 * like the subset of a clause a human reads: a short label and the rule itself. */

export interface ConstraintRow {
  /** A short handle for the rule — its first few words, which is what the PM writes as the head. */
  label: string;
  /** The rule, verbatim. Never summarized: a paraphrased constraint is a different constraint. */
  text: string;
}

/** Leading "1." / "1)" / "-" / "•" markers, at the start of a line. */
const MARKER = /^\s*(?:\d+[.)]|[-•*])\s+/;

function labelFor(text: string): string {
  // The head of the sentence up to the first strong break — enough to scan a column of rules
  // without reading each one in full. Falls back to a word-bounded truncation.
  const head = text.split(/[:;]|\s+—\s+/)[0].trim();
  if (head.length > 0 && head.length <= 48) return head;
  const words = text.split(/\s+/);
  let out = "";
  for (const w of words) {
    if ((out + " " + w).trim().length > 44) break;
    out = (out + " " + w).trim();
  }
  return out || text.slice(0, 44);
}

/**
 * Split stored constraint prose into rows. Returns [] for empty input, and a SINGLE row carrying
 * the whole text when the prose is not enumerated — the caller can then tell "structured" from
 * "one blob" by the row count rather than being handed fabricated structure.
 */
export function constraintRows(constraints: string | null | undefined): ConstraintRow[] {
  const raw = (constraints ?? "").trim();
  if (!raw) return [];
  const lines = raw.split(/\r?\n/);
  const rows: ConstraintRow[] = [];
  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    if (MARKER.test(trimmed)) {
      rows.push({ label: "", text: trimmed.replace(MARKER, "").trim() });
    } else if (rows.length > 0) {
      // A continuation line belongs to the rule above it — wrapping is not a new constraint.
      rows[rows.length - 1].text = `${rows[rows.length - 1].text} ${trimmed}`.trim();
    }
  }
  if (rows.length === 0) return [{ label: "", text: raw }];
  return rows.map((r) => ({ ...r, label: labelFor(r.text) }));
}
