/* One way to say how long something took.
 *
 * Lifted out of `AgentStatus` so the PM chat's clock and the run pages' agree. There are two
 * other near-duplicates in the codebase (`PortraitCard`'s `fmtWorked`, `overview`'s `timeAgo`);
 * they format different things for different places and folding them in is its own cleanup, not
 * a thing to do quietly while adding a feature. */

/** `11s`, `1m 5s`. Seconds in, never negative out. */
export function fmtDuration(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  const m = Math.floor(s / 60);
  return m > 0 ? `${m}m ${s % 60}s` : `${s}s`;
}
