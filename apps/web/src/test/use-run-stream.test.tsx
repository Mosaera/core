import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { act } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { RunSnapshot } from "../api/client";
import { useRunStream } from "../hooks/useRunStream";

// jsdom has no EventSource; a no-op stub lets the enrichment effect mount.
// The point of MR-2a is that correctness never depends on this stream.
class FakeEventSource {
  static instances: FakeEventSource[] = [];
  listeners: Record<string, (e: unknown) => void> = {};
  constructor(public url: string) {
    FakeEventSource.instances.push(this);
  }
  addEventListener(type: string, cb: (e: unknown) => void) {
    this.listeners[type] = cb;
  }
  close() {}
}

const getRun = vi.fn();
vi.mock("../api/client", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../api/client")>();
  return { ...mod, api: { ...mod.api, getRun: (id: string) => getRun(id) } };
});

function snap(over: Partial<RunSnapshot> = {}): RunSnapshot {
  return {
    run_id: "r1",
    status: "running",
    phase: "implement",
    started_at: 1,
    pending_interrupt: null,
    approved: null,
    report_path: null,
    commit_sha: null,
    ...over,
  };
}

function wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  FakeEventSource.instances = [];
  (globalThis as unknown as { EventSource: unknown }).EventSource = FakeEventSource;
  getRun.mockReset();
});

afterEach(() => vi.clearAllMocks());

describe("useRunStream", () => {
  it("derives the gate and status from the authoritative poll snapshot", async () => {
    getRun.mockResolvedValue(
      snap({ status: "awaiting_approval", pending_interrupt: { id: "i1", value: { action: "deliver" } } }),
    );
    const { result } = renderHook(() => useRunStream("r1"), { wrapper });
    await waitFor(() => expect(result.current.status).toBe("awaiting_approval"));
    // The gate comes from getRun, never from an SSE event.
    expect(result.current.gate?.value.action).toBe("deliver");
  });

  it("clearing the gate is a poll refetch (resync), not a stream event", async () => {
    getRun
      .mockResolvedValueOnce(
        snap({ status: "awaiting_approval", pending_interrupt: { id: "i1", value: { action: "deliver" } } }),
      )
      .mockResolvedValue(snap({ status: "completed", pending_interrupt: null, approved: true }));
    const { result } = renderHook(() => useRunStream("r1"), { wrapper });
    await waitFor(() => expect(result.current.gate).not.toBeNull());
    // Simulate what RunPage.decide() does after api.approve resolves.
    act(() => result.current.resync());
    await waitFor(() => expect(result.current.status).toBe("completed"));
    expect(result.current.gate).toBeNull();
    expect(result.current.final?.status).toBe("completed");
  });

  it("collects coder activity milestones from the stream", async () => {
    getRun.mockResolvedValue(snap({ status: "running" }));
    const { result } = renderHook(() => useRunStream("r1"), { wrapper });
    await waitFor(() => expect(result.current.status).toBe("running"));
    const es = FakeEventSource.instances[0];
    act(() =>
      es.listeners["activity"]?.({
        data: JSON.stringify({ kind: "file_read", detail: "x.py", node: "implement" }),
      }),
    );
    act(() => es.listeners["activity"]?.({ data: JSON.stringify({ kind: "running_validation" }) }));
    await waitFor(() => expect(result.current.activities).toHaveLength(2));
    // The owning node rides through for correct actor attribution.
    expect(result.current.activities[0]).toEqual({ kind: "file_read", detail: "x.py", node: "implement" });
  });

  it("builds an ordered transcript from activities and node updates (with results)", async () => {
    getRun.mockResolvedValue(snap({ status: "running" }));
    const { result } = renderHook(() => useRunStream("r1"), { wrapper });
    await waitFor(() => expect(result.current.status).toBe("running"));
    const es = FakeEventSource.instances[0];
    act(() =>
      es.listeners["activity"]?.({
        data: JSON.stringify({ kind: "file_written", detail: "a.py", result: "42 chars", node: "implement", ts: 111 }),
      }),
    );
    act(() =>
      es.listeners["update"]?.({ data: JSON.stringify({ node: "plan", update: { plan: "1. do X" }, ts: 222 }) }),
    );
    // activity → 1 item; update → a phase item + a body item (plan has text).
    await waitFor(() => expect(result.current.transcript).toHaveLength(3));
    const t = result.current.transcript;
    expect(t[0]).toMatchObject({ kind: "activity", node: "implement" });
    expect(t[0].activity?.result).toBe("42 chars"); // the tool result is carried
    expect(t[0].ts).toBe(111); // the SERVER timestamp is used, not client receive-time
    expect(t[1]).toMatchObject({ kind: "phase", node: "plan", ts: 222 });
    expect(t[2]).toMatchObject({ kind: "body", node: "plan", body: "1. do X", ts: 222 });
    // Monotonic seq preserves arrival order for interleaving.
    expect(t[0].seq < t[1].seq && t[1].seq < t[2].seq).toBe(true);
  });

  it("surfaces the widened node payloads live (shared NODE_TEXT — design/critic)", async () => {
    getRun.mockResolvedValue(snap({ status: "running" }));
    const { result } = renderHook(() => useRunStream("r1"), { wrapper });
    await waitFor(() => expect(result.current.status).toBe("running"));
    const es = FakeEventSource.instances[0];
    act(() =>
      es.listeners["update"]?.({
        data: JSON.stringify({ node: "design", update: { design: "one seam, no API change" }, ts: 1 }),
      }),
    );
    act(() =>
      es.listeners["update"]?.({
        data: JSON.stringify({
          node: "critic",
          update: { outcome_verdict: { vetoed: true, reason: "claim unbound" } },
          ts: 2,
        }),
      }),
    );
    await waitFor(() =>
      expect(result.current.transcript.filter((i) => i.kind === "body")).toHaveLength(2),
    );
    const bodies = result.current.transcript.filter((i) => i.kind === "body");
    expect(bodies[0]).toMatchObject({ node: "design", body: "one seam, no API change" });
    expect(bodies[1]).toMatchObject({ node: "critic", body: "vetoed: claim unbound" });
  });

  it("streams an agent's reasoning into the transcript as a thought item", async () => {
    getRun.mockResolvedValue(snap({ status: "running" }));
    const { result } = renderHook(() => useRunStream("r1"), { wrapper });
    await waitFor(() => expect(result.current.status).toBe("running"));
    const es = FakeEventSource.instances[0];
    act(() =>
      es.listeners["thought"]?.({
        data: JSON.stringify({ node: "implement", text: "I'll read the config first.", ts: 333 }),
      }),
    );
    // Empty text is ignored (a pure tool-call turn produces no thought).
    act(() => es.listeners["thought"]?.({ data: JSON.stringify({ node: "implement", text: "" }) }));
    await waitFor(() => expect(result.current.transcript).toHaveLength(1));
    expect(result.current.transcript[0]).toMatchObject({
      kind: "thought",
      node: "implement",
      text: "I'll read the config first.",
      ts: 333,
    });
  });

  it("a native stream disconnect does not freeze the UI — it flips connected, poll carries on", async () => {
    getRun.mockResolvedValue(snap({ status: "running" }));
    const { result } = renderHook(() => useRunStream("r1"), { wrapper });
    await waitFor(() => expect(result.current.status).toBe("running"));
    const es = FakeEventSource.instances[0];
    // Native connection-drop error events carry no data — the old code no-op'd here.
    act(() => es.listeners["error"]?.({ data: undefined }));
    await waitFor(() => expect(result.current.connected).toBe(false));
    // Still usable: the authoritative snapshot is intact.
    expect(result.current.status).toBe("running");
  });
});
