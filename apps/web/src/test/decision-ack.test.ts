import { beforeEach, describe, expect, it } from "vitest";

import type { Decision } from "../api/delivery";
import {
  acknowledge,
  ackKey,
  canAcknowledge,
  isAcknowledged,
  liveDecisions,
  unacknowledge,
} from "../lib/decisionAck";

const standing = (over: Partial<Decision> = {}): Decision => ({
  id: "delivered-no-mr", kind: "delivered_no_mr", tier: "standing",
  title: "12 delivered items have no merge request",
  summary: "Twelve items are delivered locally.", requires_admin: false, actions: [], ...over,
});
const blocking = (over: Partial<Decision> = {}): Decision => ({
  id: "gate:run-1", kind: "gate_pending", tier: "blocking",
  title: "A run is waiting for your decision", summary: "Parked at the delivery gate.",
  requires_admin: false, actions: [], run_id: "run-1", ...over,
}) as Decision;

beforeEach(() => localStorage.clear());

describe("acknowledgment", () => {
  it("REFUSES to acknowledge a blocking decision (ADR-0107)", () => {
    // `gate:{run_id}` is ONE id for a run that can park at several different gates. Acking the
    // first question would silence the second invisibly, with no record — an unrecorded
    // suppression of an ask. The capability is removed rather than the collision detected.
    const d = blocking();
    expect(canAcknowledge(d)).toBe(false);
    acknowledge("p1", d, 1);
    expect(isAcknowledged("p1", d)).toBe(false);
    expect(liveDecisions("p1", [d])).toHaveLength(1);
  });

  it("acknowledges a standing advisory and keeps it dismissed", () => {
    const d = standing();
    acknowledge("p1", d, 1);
    expect(isAcknowledged("p1", d)).toBe(true);
    expect(liveDecisions("p1", [d])).toHaveLength(0);
    unacknowledge("p1", d);
    expect(liveDecisions("p1", [d])).toHaveLength(1);
  });

  it("RE-RAISES when the payload changes under a constant id", () => {
    // `delivered-no-mr` and `backlog-health` have constant ids and growing contents. Dismissing
    // "12 delivered items" must not silence "13 delivered items".
    const twelve = standing();
    acknowledge("p1", twelve, 1);
    const thirteen = standing({ title: "13 delivered items have no merge request" });
    expect(isAcknowledged("p1", thirteen)).toBe(false);
    expect(liveDecisions("p1", [thirteen])).toHaveLength(1);
  });

  it("scopes acknowledgments per project", () => {
    const d = standing();
    acknowledge("p1", d, 1);
    expect(isAcknowledged("p2", d)).toBe(false);
    expect(ackKey("p1", d)).not.toBe(ackKey("p2", d));
  });

  it("fails OPEN when storage is unavailable — a card shows rather than hides", () => {
    const original = Storage.prototype.setItem;
    Storage.prototype.setItem = () => {
      throw new Error("quota");
    };
    const d = standing();
    expect(() => acknowledge("p1", d, 1)).not.toThrow();
    expect(isAcknowledged("p1", d)).toBe(false);
    Storage.prototype.setItem = original;
  });
});
