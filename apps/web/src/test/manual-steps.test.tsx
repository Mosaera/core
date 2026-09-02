import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { Project } from "../api/client";
import { ManualStepsCard } from "../components/overview/ManualStepsCard";
import { extractManualSteps } from "../lib/manualSteps";

const BRIEF = [
  "## Goals",
  "Build a password generator",
  "",
  "## Manual steps (outside the delivery agent's capability)",
  "- Delete the file: `git rm passwords.txt`",
  "- Add `passwords.txt` to .gitignore",
  "",
  "## Requirements",
  "- a --length flag",
].join("\n");

describe("extractManualSteps", () => {
  it("extracts the section body, stopping at the next heading", () => {
    const steps = extractManualSteps(BRIEF) ?? "";
    expect(steps).toContain("git rm passwords.txt");
    expect(steps).toContain(".gitignore");
    expect(steps).not.toContain("Requirements"); // stopped at the next ## heading
    expect(steps).not.toContain("Build a password"); // did not reach back into Goals
  });

  it("returns null when the section is absent, empty, or the brief is missing", () => {
    expect(extractManualSteps("## Goals\nx")).toBeNull();
    expect(extractManualSteps("")).toBeNull();
    expect(extractManualSteps(null)).toBeNull();
    expect(extractManualSteps(undefined)).toBeNull();
  });
});

describe("ManualStepsCard", () => {
  const proj = (brief: string) => ({ brief }) as unknown as Project;

  it("renders the prominent card + the exact manual steps when present", () => {
    const { container } = render(<ManualStepsCard project={proj(BRIEF)} />);
    expect(screen.getByText(/Needs your hands/)).toBeInTheDocument();
    expect(container.textContent).toContain("git rm passwords.txt");
  });

  it("renders nothing when the brief has no manual steps", () => {
    const { container } = render(<ManualStepsCard project={proj("## Goals\nx")} />);
    expect(container.firstChild).toBeNull();
  });
});
