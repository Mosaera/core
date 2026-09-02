import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { NewProjectPage } from "../pages/NewProjectPage";

const mocks = vi.hoisted(() => ({ createProject: vi.fn() }));

vi.mock("../api/client", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../api/client")>();
  return { ...mod, api: { ...mod.api, ...mocks } };
});

function renderPage() {
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <MemoryRouter>
        <NewProjectPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  mocks.createProject.mockResolvedValue({ id: "proj-x", status: "draft" });
});

describe("New project", () => {
  // ADR-0122. Requiring a source is what made "create a project, then publish it" impossible,
  // and why nothing on an instance could exercise repository creation.
  it("can be submitted with a name alone", async () => {
    renderPage();
    const cta = screen.getByRole("button", { name: "Create project" });
    expect(cta).toBeDisabled();

    fireEvent.change(screen.getByLabelText("Project name"), { target: { value: "Ledger" } });
    expect(cta).toBeEnabled();

    fireEvent.click(cta);
    await waitFor(() => expect(mocks.createProject).toHaveBeenCalled());
    expect(mocks.createProject.mock.calls[0][0]).toMatchObject({
      name: "Ledger",
      source_repo: "",
    });
  });

  it("says where the code lives when no repository is imported", () => {
    renderPage();
    expect(screen.getByText(/starts as a fresh repository on this server/)).toBeInTheDocument();
    // The durability consequence is stated, not discovered after a loss.
    expect(screen.getByText(/its code lives only here/)).toBeInTheDocument();
  });

  it("switches to the import explanation once a source is given", () => {
    renderPage();
    fireEvent.change(screen.getByLabelText("Source repository"), {
      target: { value: "https://gitlab.example.com/g/p.git" },
    });
    expect(screen.getByText(/merge requests still go back to it/)).toBeInTheDocument();
    expect(screen.queryByText(/its code lives only here/)).not.toBeInTheDocument();
  });
});
