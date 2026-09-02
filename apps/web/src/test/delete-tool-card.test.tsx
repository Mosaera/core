import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DeleteToolCard } from "../components/settings/DeleteToolCard";

const mocks = vi.hoisted(() => ({
  features: vi.fn(),
  setDeleteTool: vi.fn(),
}));

vi.mock("../api/client", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../api/client")>();
  return { ...mod, api: { ...mod.api, features: mocks.features, setDeleteTool: mocks.setDeleteTool } };
});

function renderCard() {
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <DeleteToolCard />
    </QueryClientProvider>,
  );
}

describe("DeleteToolCard", () => {
  beforeEach(() => {
    mocks.features.mockReset();
    mocks.setDeleteTool.mockReset();
  });

  it("defaults to disabled and enables via the admin endpoint", async () => {
    mocks.features.mockResolvedValue({ delete_tool_enabled: false });
    mocks.setDeleteTool.mockResolvedValue({ delete_tool_enabled: true });
    renderCard();
    await waitFor(() => expect(screen.getByText("disabled")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /Enable deletion/ }));
    await waitFor(() => expect(mocks.setDeleteTool).toHaveBeenCalledWith(true));
    await waitFor(() => expect(screen.getByText("enabled")).toBeInTheDocument());
  });

  it("reflects the enabled state when the flag is already on", async () => {
    mocks.features.mockResolvedValue({ delete_tool_enabled: true });
    renderCard();
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /Disable deletion/ })).toBeInTheDocument(),
    );
  });
});
