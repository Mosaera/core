/* Pure unified-diff parsing shared by the legacy DiffView (/history/:id) and
   the Changes tab file panel. Lifted verbatim from DiffView so both render the
   exact same numbers. Unit-tested in changes-lib.test.ts. */

export interface FileDiff {
  path: string;
  adds: number;
  dels: number;
  lines: string[];
}

export function parseDiff(diff: string): FileDiff[] {
  const files: FileDiff[] = [];
  let cur: FileDiff | null = null;
  for (const line of diff.split("\n")) {
    if (line.startsWith("diff --git")) {
      const m = line.match(/ b\/(.+)$/);
      cur = { path: m ? m[1] : line.slice(11), adds: 0, dels: 0, lines: [] };
      files.push(cur);
      continue;
    }
    if (!cur) {
      cur = { path: "", adds: 0, dels: 0, lines: [] }; // tolerate a bare hunk
      files.push(cur);
    }
    if (line.startsWith("+") && !line.startsWith("+++")) cur.adds++;
    else if (line.startsWith("-") && !line.startsWith("---")) cur.dels++;
    cur.lines.push(line);
  }
  return files;
}

export type DiffLineKind = "add" | "del" | "hunk" | "meta" | "ctx";

export function diffLineKind(line: string): DiffLineKind {
  if (line.startsWith("+") && !line.startsWith("+++")) return "add";
  if (line.startsWith("-") && !line.startsWith("---")) return "del";
  if (line.startsWith("@@")) return "hunk";
  if (
    line.startsWith("index ") ||
    line.startsWith("+++") ||
    line.startsWith("---") ||
    line.startsWith("new file") ||
    line.startsWith("deleted file")
  )
    return "meta";
  return "ctx";
}

/** The server caps the accumulated diff at 200k chars and appends this marker
 *  (mosaera_core/tools/repo.py project_diff) — when present, client-side file
 *  lists and line counts derived from the text are partial. */
export function isTruncatedDiff(diff: string): boolean {
  return diff.includes("... (diff truncated");
}

export interface DiffRow {
  kind: DiffLineKind;
  text: string;
  /** Old-file line number (null on added lines and headers). */
  oldNo: number | null;
  /** New-file line number (null on deleted lines and headers). */
  newNo: number | null;
}

/** Annotate a file's diff lines with old/new line numbers derived from the `@@`
 *  hunk headers, for a two-gutter line-numbered view. Pure; unit-tested. */
export function annotateDiff(lines: string[]): DiffRow[] {
  const rows: DiffRow[] = [];
  let oldNo = 0;
  let newNo = 0;
  for (const text of lines) {
    const kind = diffLineKind(text);
    if (kind === "hunk") {
      const m = text.match(/@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/);
      if (m) {
        oldNo = Number(m[1]);
        newNo = Number(m[2]);
      }
      rows.push({ kind, text, oldNo: null, newNo: null });
    } else if (kind === "meta") {
      rows.push({ kind, text, oldNo: null, newNo: null });
    } else if (kind === "add") {
      rows.push({ kind, text, oldNo: null, newNo: newNo++ });
    } else if (kind === "del") {
      rows.push({ kind, text, oldNo: oldNo++, newNo: null });
    } else {
      rows.push({ kind, text, oldNo: oldNo++, newNo: newNo++ });
    }
  }
  return rows;
}
