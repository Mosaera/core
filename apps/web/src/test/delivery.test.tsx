import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AuthProvider } from "../api/authContext";
import type { BacklogItem, Project } from "../api/client";
import { DeliveryWorkspace } from "../components/delivery/DeliveryWorkspace";

const mocks = vi.hoisted(() => ({
  projectDiff: vi.fn(),
  projectMrStatus: vi.fn(),
  projectDeliveryCapability: vi.fn(),
  openItemMr: vi.fn(),
  mergeProject: vi.fn(),
  listBranches: vi.fn(),
  pruneMergedBranches: vi.fn(),
  deleteBranch: vi.fn(),
  getGeneralSettings: vi.fn(),
  setItemMrState: vi.fn(),
  itemMergeReadiness: vi.fn(),
  mergeItemMr: vi.fn(),
}));

vi.mock("../api/client", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../api/client")>();
  return {
    ...mod,
    api: {
      ...mod.api,
      projectDiff: mocks.projectDiff,
      projectMrStatus: mocks.projectMrStatus,
      projectDeliveryCapability: mocks.projectDeliveryCapability,
      openItemMr: mocks.openItemMr,
      mergeProject: mocks.mergeProject,
      listBranches: mocks.listBranches,
      pruneMergedBranches: mocks.pruneMergedBranches,
      deleteBranch: mocks.deleteBranch,
      getGeneralSettings: mocks.getGeneralSettings,
      setItemMrState: mocks.setItemMrState,
      itemMergeReadiness: mocks.itemMergeReadiness,
      mergeItemMr: mocks.mergeItemMr,
    },
  };
});

function item(over: Partial<BacklogItem> = {}): BacklogItem {
  return {
    id: 1, project_id: "p1", title: "Hero item", description: "", acceptance: "",
    status: "in_review", position: 0, iteration: null, created_at: null, ...over,
  };
}

function project(over: Partial<Project> = {}): Project {
  return {
    id: "p1", name: "Demo", source_repo: "https://gitlab.rengifo.me/m/d.git", goal: "g",
    brief: "b", status: "active", branch: "mosaera/x", mr_url: "", autonomous: false,
    has_gitlab_token: true, gitlab_token_masked: "…ab12", error: "",
    created_at: "2026-07-01T00:00:00Z", backlog: [item()], runs: [], ...over,
  };
}

function renderDelivery(p: Project) {
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <AuthProvider>
        <MemoryRouter initialEntries={[`/projects/${p.id}/delivery`]}>
          <Routes>
            <Route path="/projects/:id/delivery" element={<DeliveryWorkspace project={p} />} />
            <Route path="/projects/:id/settings" element={<div>settings page</div>} />
          </Routes>
        </MemoryRouter>
      </AuthProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  mocks.projectDiff.mockResolvedValue({
    base: "main", diff: "d", has_changes: true, files: ["a"], remote_synced: false,
  });
  mocks.projectMrStatus.mockResolvedValue({ state: null, url: "", items: [] });
  mocks.projectDeliveryCapability.mockResolvedValue({
    provider: "gitlab", can_finish: true, reason: null, detail: "",
    item_requests_supported: true, has_gitlab_token: true, has_gitlab_api_token: false,
    merge_state_readable: true,
  });
  mocks.listBranches.mockResolvedValue({ branches: [] });
  // Branch destruction is admin-only by default; these tests assert MECHANICS, so they run with
  // it allowed. The gated state has its own test below.
  mocks.getGeneralSettings.mockResolvedValue({
    knobs: {
      member_branch_delete: {
        value: true, source: "stored", kind: "bool",
        env: "MOSAERA_MEMBER_BRANCH_DELETE", choices: null,
      },
    },
  });
});

describe("DeliveryWorkspace", () => {
  it("says delivered-unpushed plainly and composes an item MR before sending", async () => {
    mocks.openItemMr.mockResolvedValue({ opened: true, url: "https://gl/mr/1" });
    renderDelivery(project());
    // The pipeline verdict: honest about local-only work (remote_synced=false).
    expect(await screen.findByText(/NOT on the remote yet/)).toBeInTheDocument();
    expect(screen.getByText(/branch tip is NOT on the remote/)).toBeInTheDocument();
    // Open MR now opens the compose Sheet prefilled — no send yet (ADR-0103).
    fireEvent.click(await screen.findByRole("button", { name: "Open MR" }));
    expect(await screen.findByText(/Compose merge request/)).toBeInTheDocument();
    expect(mocks.openItemMr).not.toHaveBeenCalled();
    // No api token → the caveat shows and the body edit is ignored; submit sends the toggles.
    expect(screen.getByText(/can't survive the push-options transport/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Open merge request" }));
    await waitFor(() =>
      expect(mocks.openItemMr).toHaveBeenCalledWith("p1", 1, expect.objectContaining({ target_branch: "main" })),
    );
  });

  it("with an api token the compose Sheet sends the FULL edited body faithfully", async () => {
    mocks.openItemMr.mockResolvedValue({ opened: true, url: "https://gl/mr/1" });
    renderDelivery(project({ has_gitlab_api_token: true }));
    fireEvent.click(await screen.findByRole("button", { name: "Open MR" }));
    const body = await screen.findByRole("textbox", { name: "Description" });
    fireEvent.change(body, { target: { value: "line one\n\nline two" } });
    fireEvent.click(screen.getByRole("button", { name: "Open merge request" }));
    await waitFor(() =>
      expect(mocks.openItemMr).toHaveBeenCalledWith(
        "p1",
        1,
        expect.objectContaining({ body: "line one\n\nline two" }),
      ),
    );
  });

  it("an untouched labels field is OMITTED, so re-composing never clears the MR's labels", async () => {
    // The sheet used to send `labels: []` on every submit, which the server reads as "clear" —
    // silently wiping the labels off an already-open MR. Omission is the only honest default.
    mocks.openItemMr.mockResolvedValue({ opened: true, url: "https://gl/mr/1" });
    renderDelivery(project({ has_gitlab_api_token: true }));
    fireEvent.click(await screen.findByRole("button", { name: "Open MR" }));
    fireEvent.click(await screen.findByRole("button", { name: "Open merge request" }));
    await waitFor(() => expect(mocks.openItemMr).toHaveBeenCalled());
    expect(mocks.openItemMr.mock.calls[0][2]).not.toHaveProperty("labels");
  });

  it("typed labels are sent parsed; emptying the field after typing clears them", async () => {
    mocks.openItemMr.mockResolvedValue({ opened: true, url: "https://gl/mr/1" });
    renderDelivery(project({ has_gitlab_api_token: true }));
    fireEvent.click(await screen.findByRole("button", { name: "Open MR" }));
    fireEvent.change(await screen.findByRole("textbox", { name: "Labels" }), {
      target: { value: " backend , urgent ,, " },
    });
    fireEvent.click(screen.getByRole("button", { name: "Open merge request" }));
    await waitFor(() =>
      expect(mocks.openItemMr).toHaveBeenCalledWith(
        "p1",
        1,
        expect.objectContaining({ labels: ["backend", "urgent"] }),
      ),
    );
  });

  it("a deleted branch leaves the list immediately, without waiting for a refetch", async () => {
    // The server returns 200 only after the remote delete succeeded, so that response IS the
    // validation. Relying on the refetch alone was not enough: the list comes from GitLab, which
    // can still report a just-deleted branch, putting the row back until a manual page reload.
    mocks.listBranches.mockResolvedValue({
      source: "gitlab",
      branches: [
        { name: "mosaera/item-7", merged: true, protected: false },
        { name: "mosaera/item-8", merged: false, protected: false },
      ],
    });
    mocks.deleteBranch.mockResolvedValue({ deleted: "mosaera/item-7" });
    renderDelivery(project());
    fireEvent.click((await screen.findAllByRole("button", { name: "Delete" }))[0]);
    fireEvent.click(await screen.findByRole("button", { name: "Delete branch" }));
    await waitFor(() => expect(mocks.deleteBranch).toHaveBeenCalled());
    // Gone from the UI even though the (mocked) refetch still returns it.
    await waitFor(() => expect(screen.queryByText("mosaera/item-7")).not.toBeInTheDocument());
    expect(screen.getByText("mosaera/item-8")).toBeInTheDocument();
  });

  it("renders merged badges from the live poll and links open MRs", async () => {
    mocks.projectMrStatus.mockResolvedValue({
      state: null,
      url: "",
      items: [{ id: 1, state: "merged", url: "https://gl/mr/1" }],
    });
    renderDelivery(
      project({
        backlog: [item({ branch: "mosaera/item-1", mr_url: "https://gl/mr/1", mr_state: "opened" })],
      }),
    );
    expect(await screen.findByText("merged")).toBeInTheDocument();
    // Base-UI's render-prop <a> keeps the button role; assert the real href.
    expect(screen.getByRole("button", { name: /View MR/ })).toHaveAttribute(
      "href",
      "https://gl/mr/1",
    );
    // Already-opened item never re-offers the opener.
    expect(screen.queryByRole("button", { name: "Open MR" })).not.toBeInTheDocument();
  });

  it("surfaces a base-drift pause and the credentials posture", async () => {
    renderDelivery(project({ error: "autonomous failed to start: base drift: split history" }));
    expect(await screen.findByText(/base drift: split history/)).toBeInTheDocument();
    expect(screen.getByText(/never the global token/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Manage GitLab" })).toHaveAttribute(
      "href", "/projects/p1/settings?pane=integration",
    );
  });

  it("prunes merged branches from the branches panel (ADR-0103 Phase 4)", async () => {
    mocks.projectMrStatus.mockResolvedValue({
      state: null,
      url: "",
      items: [{ id: 1, state: "merged", url: "https://gl/mr/1" }],
    });
    mocks.pruneMergedBranches.mockResolvedValue({ pruned: ["mosaera/item-1"] });
    renderDelivery(
      project({
        backlog: [item({ branch: "mosaera/item-1", mr_url: "https://gl/mr/1", mr_state: "merged" })],
      }),
    );
    fireEvent.click(await screen.findByRole("button", { name: "Prune merged branches" }));
    // A bulk REMOTE delete must not fire off its own button: the confirm names what goes first.
    expect(mocks.pruneMergedBranches).not.toHaveBeenCalled();
    expect(await screen.findByText("Prune merged branches?")).toBeInTheDocument();
    fireEvent.click(await screen.findByRole("button", { name: "Prune branches" }));
    await waitFor(() => expect(mocks.pruneMergedBranches).toHaveBeenCalledWith("p1"));
    expect(await screen.findByText(/pruned mosaera\/item-1/)).toBeInTheDocument();
  });

  it("cancelling the prune confirm sends nothing", async () => {
    mocks.projectMrStatus.mockResolvedValue({
      state: null,
      url: "",
      items: [{ id: 1, state: "merged", url: "https://gl/mr/1" }],
    });
    renderDelivery(
      project({
        backlog: [item({ branch: "mosaera/item-1", mr_url: "https://gl/mr/1", mr_state: "merged" })],
      }),
    );
    fireEvent.click(await screen.findByRole("button", { name: "Prune merged branches" }));
    fireEvent.click(await screen.findByRole("button", { name: "Cancel" }));
    await waitFor(() =>
      expect(screen.queryByText("Prune merged branches?")).not.toBeInTheDocument(),
    );
    // The assertion that catches a confirm wired as decoration.
    expect(mocks.pruneMergedBranches).not.toHaveBeenCalled();
  });

  it("deleting a branch names it in the confirm and only then calls the API", async () => {
    mocks.listBranches.mockResolvedValue({
      branches: [{ name: "mosaera/item-7", merged: false, protected: false }],
    });
    mocks.deleteBranch.mockResolvedValue({ deleted: "mosaera/item-7" });
    renderDelivery(project());
    fireEvent.click(await screen.findByRole("button", { name: "Delete" }));
    expect(mocks.deleteBranch).not.toHaveBeenCalled();
    const dialog = await screen.findByLabelText("Delete this branch on GitLab?");
    // Echoed INSIDE the confirm — not merely present somewhere on the page (it's in the row too).
    expect(within(dialog).getByText("mosaera/item-7")).toBeInTheDocument();
    fireEvent.click(await screen.findByRole("button", { name: "Delete branch" }));
    await waitFor(() => expect(mocks.deleteBranch).toHaveBeenCalledWith("p1", "mosaera/item-7"));
  });

  it("without a token it says MRs cannot open", async () => {
    renderDelivery(project({ has_gitlab_token: false, gitlab_token_masked: "" }));
    expect(
      await screen.findByText(/No project GitLab token — merge requests can't be opened/),
    ).toBeInTheDocument();
  });
});


describe("DeliveryWorkspace — branch destruction is opt-in", () => {
  it("a member sees the controls disabled and is told why", async () => {
    // The server refuses this for a member unless an admin opted them in, so the surface must not
    // offer it — a button that 403s is the defect this review keeps finding.
    mocks.getGeneralSettings.mockResolvedValue({
      knobs: {
        member_branch_delete: {
          value: false, source: "default", kind: "bool",
          env: "MOSAERA_MEMBER_BRANCH_DELETE", choices: null,
        },
      },
    });
    mocks.listBranches.mockResolvedValue({
      source: "gitlab",
      branches: [{ name: "mosaera/item-7", merged: true, protected: false }],
    });
    mocks.projectMrStatus.mockResolvedValue({
      state: null, url: "",
      items: [{ id: 1, state: "merged", url: "https://gl/mr/1" }],
    });
    renderDelivery(
      project({
        backlog: [item({ branch: "mosaera/item-1", mr_url: "https://gl/mr/1", mr_state: "merged" })],
      }),
    );
    expect(await screen.findByRole("button", { name: "Delete" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Prune merged branches" })).toBeDisabled();
    expect(screen.getByText(/admin-only on this instance/i)).toBeInTheDocument();
  });
});

describe("the merge-request lifecycle", () => {
  // Until now the product could only ever OPEN an MR: an obsolete one stayed live here forever,
  // and `closed` was a state nothing could produce or clear. The row offers only the transition
  // GitLab would accept, so the surface never proposes an action the server refuses.
  it("offers Close on an open MR and sends the lifecycle verb", async () => {
    mocks.setItemMrState.mockResolvedValue({ opened: true, url: "https://gl/mr/2" });
    mocks.projectMrStatus.mockResolvedValue({
      state: null, url: "", items: [{ id: 1, state: "opened", url: "https://gl/mr/2" }],
    });
    renderDelivery(project({ backlog: [item({ status: "in_review" })] }));
    fireEvent.click(await screen.findByRole("button", { name: "Close MR" }));
    await waitFor(() => expect(mocks.setItemMrState).toHaveBeenCalledWith("p1", 1, "close"));
    expect(screen.queryByRole("button", { name: "Reopen MR" })).not.toBeInTheDocument();
  });

  it("offers Reopen on a closed MR — closing is only safe because it is reversible", async () => {
    mocks.setItemMrState.mockResolvedValue({ opened: true, url: "https://gl/mr/2" });
    mocks.projectMrStatus.mockResolvedValue({
      state: null, url: "", items: [{ id: 1, state: "closed", url: "https://gl/mr/2" }],
    });
    renderDelivery(project({ backlog: [item({ status: "in_review" })] }));
    fireEvent.click(await screen.findByRole("button", { name: "Reopen MR" }));
    await waitFor(() => expect(mocks.setItemMrState).toHaveBeenCalledWith("p1", 1, "reopen"));
  });

  it("offers neither on a merged MR — merged has no lifecycle left", async () => {
    mocks.projectMrStatus.mockResolvedValue({
      state: null, url: "", items: [{ id: 1, state: "merged", url: "https://gl/mr/2" }],
    });
    renderDelivery(project({ backlog: [item({ status: "done" })] }));
    // Scoped to the item row's own badge. The old page-wide /merged/ query was timing-dependent:
    // it resolved on the header summary BEFORE the async branches query landed, and any change to
    // the page's query count (2026-08-22: the settings KnobForm left this page) flipped it to a
    // multi-match. The behaviour under test — no lifecycle buttons on a merged MR — is unchanged.
    const row = (await screen.findByText(/#1 ·/)).closest("li") as HTMLElement;
    expect(within(row).getByText("merged")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Close MR" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Reopen MR" })).not.toBeInTheDocument();
  });
});

describe("merging an item MR from the console (#109)", () => {
  /* Driving LedgerCLI to completion needed NINE merges and every one happened in GitLab, because
     the console could open and close an MR and not merge one. The confirmation is where the
     honesty lives: it reads GitLab's verdict at the moment it asks, and offers a merge only when
     GitLab says the MR is actually mergeable. */

  const openMr = () =>
    project({
      has_gitlab_api_token: true,
      backlog: [item({ status: "done", mr_url: "https://gl/m/d/-/merge_requests/7" })],
    });

  const ready = {
    status: "mergeable", sha: "deadbeef", source_branch: "mosaera/item-1",
    target_branch: "main", web_url: "https://gl/m/d/-/merge_requests/7", error: null,
  };

  beforeEach(() => {
    mocks.projectMrStatus.mockResolvedValue({
      state: "opened",
      items: [{ id: 1, state: "opened", url: "https://gl/m/d/-/merge_requests/7" }],
    });
  });

  it("names the actual branches in the confirmation, never 'this item'", async () => {
    mocks.itemMergeReadiness.mockResolvedValue(ready);
    renderDelivery(openMr());
    fireEvent.click(await screen.findByRole("button", { name: /^Merge$/ }));
    const dialog = await screen.findByRole("dialog", { name: /merge this merge request/i });
    // The SPECIFIC branches, per ConfirmDialog's own rule: a generic "this cannot be undone"
    // teaches the operator to click through.
    expect(await within(dialog).findByText("mosaera/item-1")).toBeTruthy();
    expect(within(dialog).getByText("main")).toBeTruthy();
    expect(within(dialog).getByText(/cannot be undone from here/i)).toBeTruthy();
  });

  it("offers the merge only when GitLab says mergeable", async () => {
    mocks.itemMergeReadiness.mockResolvedValue(ready);
    mocks.mergeItemMr.mockResolvedValue({ merged: true, queued: false });
    renderDelivery(openMr());
    fireEvent.click(await screen.findByRole("button", { name: /^Merge$/ }));
    fireEvent.click(await screen.findByRole("button", { name: /Merge into main/i }));
    await waitFor(() =>
      expect(mocks.mergeItemMr).toHaveBeenCalledWith("p1", 1, expect.objectContaining({ sha: "deadbeef" })),
    );
  });

  it("a running pipeline offers auto-merge, NOT a plain merge", async () => {
    mocks.itemMergeReadiness.mockResolvedValue({ ...ready, status: "ci_still_running" });
    renderDelivery(openMr());
    fireEvent.click(await screen.findByRole("button", { name: /^Merge$/ }));
    expect(await screen.findByText(/pipeline is still running/i)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Merge into main/i })).toBeNull();
    expect(screen.getByRole("button", { name: /when the pipeline passes/i })).toBeTruthy();
  });

  it("a hard blocker names itself and offers NO merge at all", async () => {
    mocks.itemMergeReadiness.mockResolvedValue({ ...ready, status: "conflict" });
    renderDelivery(openMr());
    fireEvent.click(await screen.findByRole("button", { name: /^Merge$/ }));
    expect(await screen.findByText(/conflicts with the target branch/i)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Merge into|pipeline passes/i })).toBeNull();
  });

  it("AN UNREADABLE VERDICT OFFERS NOTHING — a failed read is not permission", async () => {
    mocks.itemMergeReadiness.mockResolvedValue({ ...ready, status: "", error: "503: down" });
    renderDelivery(openMr());
    fireEvent.click(await screen.findByRole("button", { name: /^Merge$/ }));
    expect(await screen.findByText(/has not said whether this can merge/i)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Merge into|pipeline passes/i })).toBeNull();
  });

  it("no Merge action on a row whose MR is not open", async () => {
    mocks.projectMrStatus.mockResolvedValue({
      state: "merged",
      items: [{ id: 1, state: "merged", url: "https://gl/m/d/-/merge_requests/7" }],
    });
    renderDelivery(openMr());
    await screen.findByText(/Hero item/);
    expect(screen.queryByRole("button", { name: /^Merge$/ })).toBeNull();
  });
});

describe("the api-token bit that decides whether a project can finish (#98)", () => {
  /* F64: the operator could not see whether an api-scoped token existed, and that bit alone decides
     whether a project ever reads as delivered — `status=merged` is written only by the MR REST
     poll, which needs `api` scope. The absence warning existed; the CONSEQUENCE and the positive
     case did not, so a stalled delivery and a missing credential looked identical. */

  it("names what is unavailable AND why the project will never read as delivered", async () => {
    renderDelivery(project({ has_gitlab_api_token: false }));
    const creds = await screen.findByLabelText("Delivery credentials");
    expect(within(creds).getByText(/merging from this page/i)).toBeTruthy();
    expect(within(creds).getByText(/will not show as delivered/i)).toBeTruthy();
  });

  it("confirms the token when it IS set, so merging is known to work", async () => {
    renderDelivery(project({ has_gitlab_api_token: true }));
    const creds = await screen.findByLabelText("Delivery credentials");
    expect(within(creds).getByText(/api-scoped token is set|scoped token is set/i)).toBeTruthy();
  });
});
