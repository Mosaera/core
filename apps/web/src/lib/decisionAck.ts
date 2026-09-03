/* Acknowledging a decision — the only durable state the notification surface needs.
 *
 * ADR-0105 §1 keeps decisions DERIVED, never stored: the condition is recomputed on every read, so
 * when the MR unsticks the card disappears rather than rotting into a lie. Nothing here changes
 * that. What persists is only the HUMAN'S RESPONSE, which is what turns a recomputed list into an
 * inbox rather than permanent furniture.
 *
 * TWO RULES, both load-bearing:
 *
 * 1. A BLOCKING DECISION CAN NEVER BE ACKNOWLEDGED. `gate:{run_id}` is one id for a run that can
 *    park at SEVERAL different gates over its life — acknowledging the first question would
 *    silence the second, invisibly, with no record. That is an unrecorded suppression of an ask,
 *    which ADR-0107 forbids outright. Rather than trying to detect the collision, the surface
 *    removes the capability: only `standing` advisories can be dismissed, and a blocking condition
 *    is cleared by DOING something, never by hiding it.
 *
 * 2. THE ACK IS KEYED TO THE PAYLOAD, NOT JUST THE ID. `backlog-health` and `delivered-no-mr` are
 *    CONSTANT ids whose contents grow — dismiss "12 delivered items have no MR" and it must come
 *    back when a 13th lands. The digest covers the text the operator actually read, so a changed
 *    finding re-raises itself. This fails OPEN by construction: any doubt re-raises the card
 *    rather than hiding it. */

import type { Decision } from "../api/delivery";

// Named ACK_STORE, not KEY: gitleaks' `generic-api-key` rule matches a high-entropy string
// assigned to an identifier containing "key", and flagged this localStorage name as a credential
// (entropy 3.77) — failing the `secrets` job on the staging->main MR. The value is a storage
// namespace, so the honest fix is a name that says what it is, not an allowlist entry that teaches
// the scanner to ignore a real rule. Verified against gitleaks 8.30.1: STORAGE_KEY still trips.
const ACK_STORE = "mosaera.decision-acks.v1";

/** Cheap, stable, non-cryptographic digest (FNV-1a). This is a cache key, not a security control —
 *  a collision re-shows a card, which is the safe direction. */
function digest(text: string): string {
  let h = 0x811c9dc5;
  for (let i = 0; i < text.length; i += 1) {
    h ^= text.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return (h >>> 0).toString(36);
}

/** What the operator actually read. If any of it changes, the acknowledgment no longer applies. */
export function ackKey(projectId: string, d: Decision): string {
  return `${projectId}:${d.id}:${digest(`${d.title}\n${d.summary}`)}`;
}

/** Blocking conditions are never dismissible — see rule 1. */
export function canAcknowledge(d: Decision): boolean {
  return d.tier === "standing";
}

function read(): Record<string, number> {
  try {
    const raw = localStorage.getItem(ACK_STORE);
    const parsed: unknown = raw ? JSON.parse(raw) : {};
    return typeof parsed === "object" && parsed !== null ? (parsed as Record<string, number>) : {};
  } catch {
    return {}; // unreadable store ⇒ nothing is acknowledged ⇒ every card shows. Fails open.
  }
}

export function isAcknowledged(projectId: string, d: Decision): boolean {
  if (!canAcknowledge(d)) return false; // blocking: the question is never "already answered"
  return ackKey(projectId, d) in read();
}

export function acknowledge(projectId: string, d: Decision, at: number): void {
  if (!canAcknowledge(d)) return;
  try {
    const acks = read();
    acks[ackKey(projectId, d)] = at;
    localStorage.setItem(ACK_STORE, JSON.stringify(acks));
  } catch {
    /* storage unavailable (private mode, quota): the card simply stays. Fails open. */
  }
}

export function unacknowledge(projectId: string, d: Decision): void {
  try {
    const acks = read();
    delete acks[ackKey(projectId, d)];
    localStorage.setItem(ACK_STORE, JSON.stringify(acks));
  } catch {
    /* see above */
  }
}

/** What the operator still has to look at: every blocking condition, plus standing ones they
 *  have not dismissed. */
export function liveDecisions(projectId: string, decisions: Decision[]): Decision[] {
  return decisions.filter((d) => !isAcknowledged(projectId, d));
}
