import { useQuery } from "@tanstack/react-query";
import { Check, Copy } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";

import { api } from "../../../api/client";

/** Read-only repository listing for one App installation (task 4C). New Project accepts any
 *  of these URLs — this panel does not itself start a project, it only helps an operator find
 *  the URL to paste there. */
export function InstallationRepositories({ installationId }: { installationId: number }) {
  const { data, isPending } = useQuery({
    queryKey: ["github-installation-repos", installationId],
    queryFn: () => api.githubInstallationRepositories(installationId),
  });
  const [copied, setCopied] = useState<string | null>(null);

  function copyUrl(url: string) {
    void navigator.clipboard.writeText(url).then(() => {
      setCopied(url);
      setTimeout(() => setCopied((c) => (c === url ? null : c)), 1500);
    });
  }

  if (isPending) {
    return <p className="text-[11.5px] text-muted-foreground/70">Reading repositories…</p>;
  }
  if (data?.error) {
    return (
      <p className="text-[11.5px] text-amber-600 dark:text-amber-400">
        Couldn&rsquo;t list repositories: {data.error}
      </p>
    );
  }
  const repos = data?.repositories ?? [];
  if (repos.length === 0) {
    return <p className="text-[11.5px] text-muted-foreground/70">No repositories yet.</p>;
  }
  return (
    <div className="flex flex-col gap-1">
      <p className="text-[11px] text-muted-foreground/80">
        Paste any of these URLs into New Project to start a project against it.
      </p>
      <ul className="flex flex-col items-stretch overflow-hidden rounded-lg ring-1 ring-white/12">
        {repos.map((r) => (
          <li
            key={r.full_name}
            className="flex items-center gap-2 border-b border-border/40 px-3 py-1.5 last:border-0"
          >
            <span className="min-w-0 flex-1 truncate font-mono text-[11.5px] text-foreground/90">
              {r.full_name}
            </span>
            {r.private && (
              <span className="shrink-0 font-mono text-[10px] text-muted-foreground/70">
                private
              </span>
            )}
            <Button
              size="sm"
              variant="ghost"
              className="h-6 shrink-0 px-1.5"
              aria-label={`Copy the URL for ${r.full_name}`}
              onClick={() => copyUrl(r.html_url)}
            >
              {copied === r.html_url ? (
                <Check className="size-3.5 text-success" />
              ) : (
                <Copy className="size-3.5" />
              )}
            </Button>
          </li>
        ))}
      </ul>
    </div>
  );
}
