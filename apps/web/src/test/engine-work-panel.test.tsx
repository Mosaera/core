import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { AgentId, AgentState } from "../lib/engine";
import type { WorkModel } from "../lib/engineWork";
import { WorkPanel } from "../components/runs/engine/WorkPanel";

const agent = (id: AgentId, status: AgentState["status"]): AgentState => ({
  id,
  name: id.charAt(0).toUpperCase() + id.slice(1),
  role: "r",
  status,
  caption: "c",
});

const model = (agent: AgentId, sections: WorkModel["sections"]): WorkModel => ({
  agent,
  name: agent.charAt(0).toUpperCase() + agent.slice(1),
  role: "does things",
  sections,
});

describe("WorkPanel — the selected agent, and only the selected agent", () => {
  it("renders the header with the agent's status chip", () => {
    render(
      <WorkPanel
        work={model("rook", [{ kind: "prose", title: "Review", text: "VERDICT: APPROVE" }])}
        agent={agent("rook", "current")}
      />,
    );
    expect(screen.getByRole("region", { name: "Rook's work" })).toBeInTheDocument();
    expect(screen.getByText("working now")).toBeInTheDocument();
    expect(screen.getByText("VERDICT: APPROVE")).toBeInTheDocument();
  });

  it("a live chain-of-thought marks its tail active and the rest done", () => {
    render(
      <WorkPanel
        work={model("forge", [
          {
            kind: "cot",
            title: "Chain of thought",
            live: true,
            items: [
              { text: "read the failing test", state: "done" },
              { text: "normalizing both sides", state: "active" },
            ],
          },
        ])}
        agent={agent("forge", "current")}
      />,
    );
    expect(document.querySelectorAll('[data-step="done"]')).toHaveLength(1);
    expect(document.querySelectorAll('[data-step="active"]')).toHaveLength(1);
    expect(screen.getByText("thinking")).toBeInTheDocument();
  });

  it("check runs show green and red counts with per-run honesty", () => {
    render(
      <WorkPanel
        work={model("vera", [
          {
            kind: "tests",
            title: "Check runs",
            passed: 1,
            failed: 1,
            rows: [
              { passed: false, label: "run 1", sub: "failed — sent back to be fixed" },
              { passed: true, label: "run 2", sub: "all green" },
            ],
          },
        ])}
        agent={agent("vera", "done")}
      />,
    );
    const panel = screen.getByText("Check runs").closest("section")!;
    expect(within(panel).getByText("1 green")).toBeInTheDocument();
    expect(within(panel).getByText("1 failed")).toBeInTheDocument();
    expect(within(panel).getByText("failed — sent back to be fixed")).toBeInTheDocument();
  });

  it("an unfinished tool call renders unsettled, a finished one settled", () => {
    render(
      <WorkPanel
        work={model("forge", [
          {
            kind: "tools",
            title: "Tool calls",
            items: [
              { title: "wrote notes.py", detail: "42 chars", settled: true },
              { title: "read tests/test_notes.py", settled: false },
            ],
          },
        ])}
        agent={agent("forge", "current")}
      />,
    );
    expect(document.querySelectorAll('[data-settled="true"]')).toHaveLength(1);
    expect(document.querySelectorAll('[data-settled="false"]')).toHaveLength(1);
  });

  it("a pending agent shows its honest reason and nothing else", () => {
    render(
      <WorkPanel
        work={model("critic", [
          { kind: "empty", reason: "Waits for Rook's verdict — it judges only the final evidence." },
        ])}
        agent={agent("critic", "pending")}
      />,
    );
    expect(screen.getByText(/judges only the final evidence/)).toBeInTheDocument();
    expect(screen.getByText("not started")).toBeInTheDocument();
    expect(document.querySelectorAll("pre")).toHaveLength(0);
  });
});
