/** The owning account of a GitHub source URL, or `null` if it isn't one.
 *
 *  Mirrors the server's `github_delivery.owner_repo_from_source` (https and scp/ssh shapes,
 *  `.git` stripped) but answers a strictly weaker question, and only for display: how many
 *  projects sit under each installation. Nothing is authorized on this answer — the server
 *  re-derives owner/repo itself and asks GitHub, which is what ADR-0114 rests on. A wrong
 *  answer here miscounts a column; it cannot grant anything.
 *
 *  Host equality, not a substring match: `github.com.evil.io` and `evil.io/github.com/x` must
 *  not read as GitHub. That is the same rule TM-0002/M-1 established for the delivery path,
 *  applied here so the two surfaces agree about what a GitHub project is. */
export function ownerOf(source: string | null | undefined): string | null {
  const raw = (source ?? "").trim();
  if (!raw) return null;

  let host: string;
  let path: string;
  const scp = /^[^/]+@([^:/]+):(.+)$/.exec(raw); // git@github.com:owner/repo.git
  if (scp) {
    host = scp[1];
    path = scp[2];
  } else {
    let url: URL;
    try {
      url = new URL(raw);
    } catch {
      return null;
    }
    if (url.protocol !== "https:" && url.protocol !== "http:") return null;
    host = url.hostname; // hostname, not host — strips the port, and userinfo never appears
    path = url.pathname;
  }

  if (host.toLowerCase() !== "github.com") return null;
  const parts = path
    .replace(/\.git$/, "")
    .split("/")
    .filter(Boolean);
  return parts.length >= 2 ? parts[0] : null;
}

/** `owner/repo` for display, or the raw source when it isn't a GitHub URL. Display only —
 *  the server derives its own owner/repo for anything that acts. */
export function ownerRepoLabel(source: string | null | undefined): string {
  const raw = (source ?? "").trim();
  if (ownerOf(raw) === null) return raw;
  const path = raw.replace(/\.git$/, "").split(/[:/]/).filter(Boolean);
  return path.slice(-2).join("/");
}
