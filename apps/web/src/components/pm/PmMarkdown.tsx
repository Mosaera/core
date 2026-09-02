import { ImageOff } from "lucide-react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";

/** A model-authored image URL, shown as inert text instead of being fetched.
 *
 *  Trimmed to something a human can read at a glance while still being long
 *  enough to recognise a host that has no business being here. */
function inertUrl(src: string): string {
  const clean = src.replace(/\s+/g, "");
  return clean.length > 96 ? `${clean.slice(0, 96)}…` : clean;
}

/** Markdown renderer for PM replies, styled for the dark console theme.
 *  Preflight is off and there's no typography plugin, so every element is
 *  styled explicitly via the components map (tables need remark-gfm).
 *
 *  SECURITY — why `img` is overridden and must stay overridden.
 *  A PM reply is model-authored text that has been influenced by untrusted
 *  content: attachments and repo-derived strings reach this model by design
 *  (ADR-0105; `quote_repo_text` exists for exactly that reason). react-markdown
 *  renders `![](url)` as a real <img src>, and its default urlTransform permits
 *  http/https — so an unoverridden `img` turns any reply into a zero-click GET
 *  to a host the model was told to name. That is the exfiltration leg of the
 *  lethal trifecta, and this surface already holds the other two.
 *
 *  Raw HTML is off by default in react-markdown, so this was never XSS: the
 *  hazard is the request itself, carrying whatever the model just read in its
 *  query string. The response CSP (`img-src 'self' data: blob:`) is the second
 *  layer; this one exists so the hole does not reopen the moment someone serves
 *  the bundle from something that drops headers.
 *
 *  Withheld, not silently dropped: the operator sees that an image was claimed
 *  and what URL it pointed at, because "no image here" and "something tried to
 *  call out and we stopped it" are opposite facts. */
export function PmMarkdown({ children }: { children: string }) {
  return (
    <Markdown
      remarkPlugins={[remarkGfm]}
      components={{
        p: ({ children }) => <p className="my-1.5 leading-relaxed first:mt-0 last:mb-0">{children}</p>,
        strong: ({ children }) => <strong className="font-semibold text-foreground">{children}</strong>,
        em: ({ children }) => <em className="italic">{children}</em>,
        // Never fetched. See the SECURITY note above before relaxing this.
        img: ({ src, alt }) => (
          <span className="my-1 inline-flex max-w-full flex-wrap items-baseline gap-1.5 rounded border border-border/50 bg-muted/30 px-2 py-1 align-middle font-mono text-[12px] text-muted-foreground">
            <ImageOff className="size-3.5 shrink-0 translate-y-0.5" aria-hidden />
            <span>{alt?.trim() || "image"}</span>
            <span className="opacity-60">not loaded —</span>
            <span className="break-all opacity-60">{inertUrl(String(src ?? ""))}</span>
          </span>
        ),
        a: ({ href, children }) => (
          <a
            href={href}
            target="_blank"
            rel="noreferrer"
            className="text-primary underline underline-offset-2 hover:opacity-80"
          >
            {children}
          </a>
        ),
        h1: ({ children }) => <h3 className="mb-1.5 mt-3 text-[17px] font-semibold first:mt-0">{children}</h3>,
        h2: ({ children }) => <h4 className="mb-1 mt-3 text-base font-semibold first:mt-0">{children}</h4>,
        h3: ({ children }) => <h5 className="mb-1 mt-2.5 text-base font-semibold first:mt-0">{children}</h5>,
        ul: ({ children }) => <ul className="my-1.5 flex list-disc flex-col gap-1 pl-5">{children}</ul>,
        ol: ({ children }) => <ol className="my-1.5 flex list-decimal flex-col gap-1 pl-5">{children}</ol>,
        li: ({ children }) => <li className="leading-relaxed [&>p]:my-0">{children}</li>,
        code: ({ children, className }) =>
          className ? (
            // fenced block content (inside <pre>)
            <code className={className}>{children}</code>
          ) : (
            <code className="rounded bg-muted/60 px-1 py-0.5 font-mono text-[13px]">{children}</code>
          ),
        pre: ({ children }) => (
          <pre className="my-2 overflow-x-auto rounded-lg border border-border/50 bg-muted/30 p-3 font-mono text-[13px] leading-relaxed">
            {children}
          </pre>
        ),
        blockquote: ({ children }) => (
          <blockquote className="my-2 border-l-2 border-primary/40 pl-3 text-muted-foreground">
            {children}
          </blockquote>
        ),
        hr: () => <hr className="my-3 border-border/50" />,
        table: ({ children }) => (
          <div className="my-2 overflow-x-auto">
            <table className="w-full border-collapse text-[15px]">{children}</table>
          </div>
        ),
        thead: ({ children }) => <thead>{children}</thead>,
        th: ({ children }) => (
          <th className="border-b border-border bg-muted/30 px-2.5 py-1.5 text-left font-mono text-[11px] uppercase tracking-wide text-muted-foreground">
            {children}
          </th>
        ),
        td: ({ children }) => (
          <td className="border-b border-border/40 px-2.5 py-1.5 align-top leading-relaxed">
            {children}
          </td>
        ),
      }}
    >
      {children}
    </Markdown>
  );
}
