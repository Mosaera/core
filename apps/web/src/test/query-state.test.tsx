import { render, screen, fireEvent } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { QueryState, summarizeError } from "../components/QueryState";

describe("QueryState", () => {
  it("renders children on success, nothing from loading/error chrome", () => {
    render(
      <QueryState query={{ isLoading: false, isError: false, refetch: vi.fn() }}>
        <p>the real content</p>
      </QueryState>,
    );
    expect(screen.getByText("the real content")).toBeInTheDocument();
  });

  it("shows a loading skeleton, not the children, while loading", () => {
    render(
      <QueryState query={{ isLoading: true, isError: false, refetch: vi.fn() }}>
        <p>the real content</p>
      </QueryState>,
    );
    expect(screen.queryByText("the real content")).not.toBeInTheDocument();
  });

  it("shows a plain-English error and a Retry wired to refetch — never a raw dump", () => {
    const refetch = vi.fn();
    render(
      <QueryState
        query={{ isLoading: false, isError: true, error: new Error("502 Bad Gateway"), refetch }}
        errorLabel="Couldn't load the thing"
      >
        <p>the real content</p>
      </QueryState>,
    );
    expect(screen.getByText("Couldn't load the thing")).toBeInTheDocument();
    expect(screen.getByText("502 Bad Gateway")).toBeInTheDocument();
    expect(screen.queryByText("the real content")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Retry/ }));
    expect(refetch).toHaveBeenCalledTimes(1);
  });
});

describe("summarizeError", () => {
  it("uses an Error's message", () => {
    expect(summarizeError(new Error("timed out"))).toBe("timed out");
  });
  it("falls back for anything that isn't a real error message", () => {
    expect(summarizeError({ some: "object" })).toBe("Something went wrong loading this.");
    expect(summarizeError(undefined)).toBe("Something went wrong loading this.");
  });
});
