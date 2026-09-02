/* Pure derivations for the Artifacts (deliverables) tab. Every value traces to
   a real API field. Deliberately NO +/− stats or diff framing — the repo delta
   belongs to Changes; Artifacts is about outputs the user can take away.
   Unit-tested in artifacts-lib.test.ts. */

export interface PathGroup {
  name: string;
  files: string[];
}

/** Group produced-file paths by top-level folder; bare files land in "(root)".
 *  Groups ordered by file count desc, then name. */
export function groupPathsByFolder(paths: string[]): PathGroup[] {
  const groups = new Map<string, PathGroup>();
  for (const path of paths) {
    const slash = path.indexOf("/");
    const name = slash === -1 ? "(root)" : path.slice(0, slash);
    let g = groups.get(name);
    if (!g) {
      g = { name, files: [] };
      groups.set(name, g);
    }
    g.files.push(path);
  }
  return [...groups.values()].sort(
    (a, b) => b.files.length - a.files.length || a.name.localeCompare(b.name),
  );
}

export type PreviewKind = "text" | "image" | "pdf" | "none";

const IMAGE_EXT = new Set(["png", "jpg", "jpeg", "gif", "webp", "svg"]);
const TEXT_EXT = new Set([
  "md", "markdown", "txt", "json", "ts", "tsx", "js", "jsx", "mjs", "cjs", "py",
  "css", "html", "htm", "yml", "yaml", "toml", "xml", "csv", "sh", "sql", "ini", "cfg",
]);

/** What kind of in-app preview a produced file supports, by extension.
 *  Text renders in a <pre> (never executed); svg only ever renders via <img>
 *  (scripts don't run in an image context); unknown types are download-only. */
export function previewKind(path: string): PreviewKind {
  const dot = path.lastIndexOf(".");
  if (dot === -1) return "none";
  const ext = path.slice(dot + 1).toLowerCase();
  if (IMAGE_EXT.has(ext)) return "image";
  if (ext === "pdf") return "pdf";
  if (TEXT_EXT.has(ext)) return "text";
  return "none";
}

/** Toolbar line: only what is cheaply and honestly knowable. Run-report counts
 *  are deliberately omitted — existence is only knowable per-run via 404. */
export function artifactsSummary(fileCount: number, hasBrief: boolean): string {
  const parts = [`${fileCount} ${fileCount === 1 ? "file" : "files"}`];
  if (fileCount > 0) parts.push("patch available");
  if (hasBrief) parts.push("brief");
  return parts.join(" · ");
}

export const TEXT_PREVIEW_LIMIT = 200_000;

export function clipPreview(text: string): { text: string; truncated: boolean } {
  if (text.length <= TEXT_PREVIEW_LIMIT) return { text, truncated: false };
  return { text: text.slice(0, TEXT_PREVIEW_LIMIT), truncated: true };
}
