import { useEffect, useRef, useState } from "react";

/** How long the run has been WORKING — the stage shows per-agent time; this is the whole run.
 *
 *  It stops while a gate is open. It used to tick `Date.now() - startedAt` unconditionally, so a
 *  run parked overnight reported "elapsed 14h" — measuring how long the OPERATOR took to answer
 *  and calling it run time. Wall clock is a true number but not the one this label promises.
 *
 *  The accumulation is client-side, so a page loaded DURING a pause starts from wall clock and
 *  therefore includes any earlier waiting. Exact working time needs park/resume timestamps on the
 *  run row; that is a server change, and this fixes the defect actually observed — the clock
 *  running while nothing is happening in front of you. */
export function TotalElapsed({ startedAt, paused }: { startedAt: number | null; paused: boolean }) {
  const [shown, setShown] = useState(0);
  const last = useRef<number | null>(null);
  useEffect(() => {
    if (startedAt) setShown(Math.max(0, Math.floor(Date.now() / 1000 - startedAt)));
  }, [startedAt]);
  useEffect(() => {
    if (paused) {
      last.current = null; // resume from NOW, so the wait is never back-filled
      return;
    }
    // Stamp the resume point BEFORE the first tick. Reading it lazily inside the tick made the
    // first second after every resume count as zero, so the clock lost a second per pause.
    last.current = Date.now();
    const t = window.setInterval(() => {
      const now = Date.now();
      const prev = last.current ?? now;
      last.current = now;
      setShown((v) => v + Math.round((now - prev) / 1000));
    }, 1000);
    return () => window.clearInterval(t);
  }, [paused]);
  if (!startedAt) return null;
  const h = Math.floor(shown / 3600);
  const m = Math.floor((shown % 3600) / 60);
  return (
    <span
      className="mr-auto font-mono text-[11.5px] tabular-nums text-muted-foreground"
      title={paused ? "Working time — stopped while the run waits on you" : "Working time"}
    >
      elapsed {h > 0 ? `${h}h ` : ""}{m}m {shown % 60}s{paused ? " · paused" : ""}
    </span>
  );
}
