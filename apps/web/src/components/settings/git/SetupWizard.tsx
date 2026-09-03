import { useId } from "react";

import { cn } from "@/lib/utils";

/** The shared first-run shell both providers use: a step indicator, a title and lede, an
 *  optional instructions panel, the step's own fields, and a Back/Continue footer.
 *
 *  Both forges get the same shell even though their middle step differs completely — GitHub
 *  registers its App in one click via the manifest flow, GitLab requires the operator to create
 *  an OAuth application by hand because it has no equivalent. That difference is real and the
 *  wizard shows it in exactly one place; everything around it stays identical, so the operator
 *  learns the shape once. */
export function SetupWizard({
  step,
  steps,
  title,
  description,
  instructions,
  children,
  onBack,
  onContinue,
  continueLabel = "Continue",
  continueDisabled,
}: {
  step: number;
  steps: number;
  title: string;
  description: string;
  instructions?: React.ReactNode;
  children?: React.ReactNode;
  onBack?: () => void;
  onContinue?: () => void;
  continueLabel?: string;
  continueDisabled?: boolean;
}) {
  return (
    <div className="flex flex-col items-stretch gap-5">
      <Stepper step={step} steps={steps} />

      <div className="flex flex-col gap-1.5">
        <h3 className="text-lg font-semibold tracking-tight text-foreground">{title}</h3>
        <p className="text-[13px] leading-relaxed text-muted-foreground">{description}</p>
      </div>

      {instructions && (
        <div className="rounded-lg bg-muted/30 p-4 ring-1 ring-white/10">
          <h4 className="mb-2 text-[13px] font-semibold text-foreground">Setup instructions</h4>
          {instructions}
        </div>
      )}

      {children}

      {(onBack || onContinue) && (
        <div className="flex items-center justify-between gap-3 pt-1">
          {onBack ? (
            <button
              type="button"
              onClick={onBack}
              className="rounded-md border-0 bg-transparent px-2 py-1.5 text-sm text-muted-foreground transition-colors hover:text-foreground"
            >
              Back
            </button>
          ) : (
            <span />
          )}
          {onContinue && (
            <button
              type="button"
              onClick={onContinue}
              disabled={continueDisabled}
              className="rounded-md border-0 bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/80 disabled:pointer-events-none disabled:opacity-50"
            >
              {continueLabel}
            </button>
          )}
        </div>
      )}
    </div>
  );
}

/** Where you are, and how much is left. Rendered as a row of dashes rather than numbered
 *  circles: the count is what matters here, and three of five steps done is legible at a glance
 *  without reading anything. */
function Stepper({ step, steps }: { step: number; steps: number }) {
  return (
    <div
      className="flex items-center justify-center gap-1.5"
      role="progressbar"
      aria-valuenow={step}
      aria-valuemin={1}
      aria-valuemax={steps}
      aria-label={`Step ${step} of ${steps}`}
    >
      {Array.from({ length: steps }, (_, i) => (
        <span
          key={i}
          className={cn(
            "h-1 w-6 rounded-full transition-colors",
            i + 1 === step ? "bg-foreground" : i + 1 < step ? "bg-foreground/50" : "bg-border",
          )}
        />
      ))}
    </div>
  );
}

/** A labelled field. Plain rather than a form library: these forms are three fields long and a
 *  dependency for that would be the wrong trade. */
export function Field({
  label,
  hint,
  value,
  onChange,
  placeholder,
  type = "text",
  mono,
}: {
  label: string;
  hint?: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  type?: string;
  mono?: boolean;
}) {
  // An explicit id rather than a wrapping label: a wrapper label folds EVERY descendant into the
  // accessible name, so a field with a hint announced as "Instance URL The address you sign in
  // at — no trailing path". The hint is described-by instead, which is what it is.
  const id = useId();
  const hintId = `${id}-hint`;
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="text-[13px] font-medium text-foreground">
        {label}
      </label>
      <input
        id={id}
        type={type}
        value={value}
        placeholder={placeholder}
        aria-describedby={hint ? hintId : undefined}
        onChange={(e) => onChange(e.target.value)}
        className={cn(
          "w-full rounded-md border border-border/70 bg-background px-3 py-2 text-sm outline-none transition-colors placeholder:text-muted-foreground/60 focus:border-ring",
          mono && "font-mono text-xs",
        )}
      />
      {hint && (
        <span id={hintId} className="text-[11.5px] text-muted-foreground">
          {hint}
        </span>
      )}
    </div>
  );
}

/** A value the operator must copy into the provider's own form, shown verbatim and derived from
 *  this instance rather than written down in a doc that would go stale the moment the instance
 *  moved. */
export function CopyValue({ children }: { children: React.ReactNode }) {
  return (
    <code className="rounded bg-background/80 px-1.5 py-0.5 font-mono text-[11.5px] text-foreground/90">
      {children}
    </code>
  );
}

/** A numbered instruction list.
 *
 *  The markers are rendered as text rather than left to `list-decimal`, because this app resets
 *  `list-style: none` globally on `ol`/`ul` — Tailwind's list utilities lose to that rule, and a
 *  numbered list silently rendering without its numbers is worse than no list at all when the
 *  numbers ARE the instruction ("do this, then this").
 */
export function Steps({ items }: { items: React.ReactNode[] }) {
  return (
    <ol className="flex flex-col gap-1.5 text-[12.5px] leading-relaxed text-muted-foreground">
      {items.map((item, i) => (
        <li key={i} className="flex gap-2">
          <span className="shrink-0 tabular-nums text-muted-foreground/70">{i + 1}.</span>
          <span className="min-w-0">{item}</span>
        </li>
      ))}
    </ol>
  );
}

/** The bullets nested inside one instruction step — same reason as `Steps`. */
export function SubItems({ items }: { items: React.ReactNode[] }) {
  return (
    <ul className="mt-1 flex flex-col gap-1">
      {items.map((item, i) => (
        <li key={i} className="flex gap-2">
          <span className="shrink-0 text-muted-foreground/70">&bull;</span>
          <span className="min-w-0">{item}</span>
        </li>
      ))}
    </ul>
  );
}
