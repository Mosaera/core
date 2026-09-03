/** The capability-aware PM (packages/agents) appends this exact section to a brief
 *  when a request needs work the delivery agent can't do (deleting/renaming files,
 *  git, installs…). We surface it prominently instead of leaving it buried in the
 *  brief markdown. Keep the heading in sync with `_UNDERSTANDING_CAPABILITY_CLAUSE`. */
const MANUAL_STEPS_HEADING = "## Manual steps (outside the delivery agent's capability)";

/** The body of the manual-steps section of a brief, or null when there isn't one.
 *  The section runs from its heading to the next `## ` heading (or end of brief). */
export function extractManualSteps(brief?: string | null): string | null {
  if (!brief) return null;
  const start = brief.indexOf(MANUAL_STEPS_HEADING);
  if (start === -1) return null;
  const after = brief.slice(start + MANUAL_STEPS_HEADING.length);
  const nextHeading = after.search(/\n##\s/);
  const body = (nextHeading === -1 ? after : after.slice(0, nextHeading)).trim();
  return body || null;
}
