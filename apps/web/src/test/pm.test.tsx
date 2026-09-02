import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { BacklogItem, Project, ProjectMessage } from "../api/client";
import { PmWorkspace } from "../components/pm/PmWorkspace";

const mocks = vi.hoisted(() => ({
  projectMessages: vi.fn(),
  sendMessage: vi.fn(),
  listSessions: vi.fn(),
  createSession: vi.fn(),
  patchSession: vi.fn(),
  addBacklogItem: vi.fn(),
  applyChangeset: vi.fn(),
  projectMrStatus: vi.fn(),
  uploadAttachment: vi.fn(),
  deleteAttachment: vi.fn(),
  getAttachment: vi.fn(),
  patchAttachmentScope: vi.fn(),
  attachmentContent: vi.fn(),
  transcribeStatus: vi.fn(),
  transcribeAudio: vi.fn(),
  resolveProposal: vi.fn(),
}));

vi.mock("../api/client", async (importOriginal) => {
  const mod = await importOriginal<typeof import("../api/client")>();
  return {
    ...mod,
    api: {
      ...mod.api,
      projectMessages: mocks.projectMessages,
      sendMessage: mocks.sendMessage,
      addBacklogItem: mocks.addBacklogItem,
      applyChangeset: mocks.applyChangeset,
      resolveProposal: mocks.resolveProposal,
      projectMrStatus: mocks.projectMrStatus,
      uploadAttachment: mocks.uploadAttachment,
      deleteAttachment: mocks.deleteAttachment,
      getAttachment: mocks.getAttachment,
      patchAttachmentScope: mocks.patchAttachmentScope,
      attachmentThumbnailUrl: (id: string, attId: string) =>
        `/api/projects/${id}/attachments/${attId}/thumbnail`,
      attachmentImageUrl: (id: string, attId: string) =>
        `/api/projects/${id}/attachments/${attId}/image`,
      attachmentFileUrl: (id: string, attId: string) =>
        `/api/projects/${id}/attachments/${attId}/file`,
      attachmentContent: mocks.attachmentContent,
      transcribeStatus: mocks.transcribeStatus,
      transcribeAudio: mocks.transcribeAudio,
    },
  };
});

vi.mock("../api/sessions", () => ({
  sessionsApi: {
    list: mocks.listSessions,
    create: mocks.createSession,
    patch: mocks.patchSession,
  },
}));

/** A session summary (server shape). By default the workspace opens on "sess-1". */
function pmSession(over: Record<string, unknown> = {}) {
  return {
    id: "sess-1", project_id: "p1", title: "", created_at: null, updated_at: null,
    archived: false, archived_at: null, message_count: 0,
    ...over,
  };
}

/** A ready server attachment payload (4B shape). */
function serverAtt(over: Record<string, unknown> = {}) {
  return {
    id: "att-1", filename: "notes.md", mime_type: "text/markdown", size_bytes: 10,
    status: "ready", error_message: "", token_estimate: 3, scope: "message_only",
    created_at: "t", large: false, summary: "",
    ...over,
  };
}

function item(id: number, status: string, title = `item ${id}`): BacklogItem {
  return {
    id, project_id: "p1", title, description: "d", acceptance: "",
    status, position: id, iteration: null, created_at: "2026-07-01T10:00:00Z",
  };
}

function project(over: Partial<Project> = {}): Project {
  return {
    id: "p1", name: "Demo", source_repo: "/tmp/demo", goal: "g", brief: "## brief",
    status: "active", branch: "mosaera/x", mr_url: "", autonomous: false,
    has_gitlab_token: false, gitlab_token_masked: "", error: "",
    created_at: "2026-07-01T00:00:00Z", backlog: [], runs: [], ...over,
  };
}

function renderPm(p: Project) {
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <MemoryRouter initialEntries={[`/projects/${p.id}/pm`]}>
        <PmWorkspace project={p} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  mocks.projectMessages.mockResolvedValue({ messages: [] });
  mocks.listSessions.mockResolvedValue({ sessions: [pmSession()] });
  mocks.createSession.mockResolvedValue(pmSession({ id: "sess-2" }));
  mocks.patchSession.mockResolvedValue(pmSession({ archived: true }));
  mocks.projectMrStatus.mockResolvedValue({ state: null, url: "" });
  mocks.addBacklogItem.mockResolvedValue(item(99, "todo"));
  mocks.applyChangeset.mockResolvedValue([]);
  mocks.resolveProposal.mockResolvedValue({ ok: true });
  mocks.deleteAttachment.mockResolvedValue({ deleted: "x" });
  mocks.transcribeStatus.mockResolvedValue({
    enabled: true, state: "ready", model: "base", prefer: "browser_first",
  });
});

const HISTORY: ProjectMessage[] = [
  { role: "user", content: "hello pm", created_at: "2026-07-05T10:00:00Z" },
  { role: "pm", content: "Hello! Here is the plan.", created_at: "2026-07-05T10:01:00Z" },
];

describe("PM workspace", () => {
  it("empty state shows starter chips that populate (not send) the composer; no quick commands", async () => {
    renderPm(project());
    expect(await screen.findByText("What should we work on next?")).toBeInTheDocument();
    const starter = screen.getByRole("button", { name: "Plan next sprint" });
    fireEvent.click(starter);
    const composer = screen.getByPlaceholderText(/Ask the PM to plan/);
    expect((composer as HTMLTextAreaElement).value).toBe(
      "Plan the next sprint based on the current backlog.",
    );
    expect(mocks.sendMessage).not.toHaveBeenCalled();
    // Guardrail 6: exactly one set of chips in the empty state.
    expect(screen.getAllByRole("button", { name: "Plan next sprint" })).toHaveLength(1);
  });

  it("renders history with a clean composer — no suggestion chips, no context control", async () => {
    mocks.projectMessages.mockResolvedValue({ messages: HISTORY });
    renderPm(project());
    expect(await screen.findByText("hello pm")).toBeInTheDocument();
    expect(screen.getByText("Hello! Here is the plan.")).toBeInTheDocument();
    // Suggestions and the Context disclosure were removed from the dock. The
    // rail that briefly owned that information is gone too (2026-08-20); each
    // reply's "Used context" line reports what it actually drew on.
    expect(screen.queryByRole("button", { name: "Summarize progress" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "What the PM can see" })).not.toBeInTheDocument();
  });

  it("changeset card: approve applies the whole changeset once and locks the card", async () => {
    mocks.projectMessages.mockResolvedValue({ messages: HISTORY });
    mocks.sendMessage.mockResolvedValue({
      reply: "Proposal below.",
      changeset: [
        { op: "add", title: "A", description: "da", why: "needed" },
        { op: "add", title: "B", description: "db", why: "needed" },
      ],
    });
    renderPm(project());
    await screen.findByText("hello pm");
    fireEvent.change(screen.getByPlaceholderText(/Ask the PM/), { target: { value: "plan it" } });
    fireEvent.click(screen.getByRole("button", { name: "Send message to the PM" }));
    expect(await screen.findByText("Proposed changes · 2")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    await waitFor(() => expect(screen.getByText(/Approved — 2 changes applied/)).toBeInTheDocument());
    expect(mocks.applyChangeset).toHaveBeenCalledTimes(1);
    expect(mocks.applyChangeset).toHaveBeenCalledWith("p1", [
      { op: "add", title: "A", description: "da", why: "needed" },
      { op: "add", title: "B", description: "db", why: "needed" },
    ]);
    // Decision actions are gone; re-approval impossible.
    expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Deny" })).not.toBeInTheDocument();
  });

  it("changeset card renders curation ops (reorder/lock) against the live backlog", async () => {
    mocks.projectMessages.mockResolvedValue({ messages: HISTORY });
    mocks.sendMessage.mockResolvedValue({
      reply: "Reprioritizing.",
      changeset: [
        { op: "reorder", ordered_ids: [2, 1], why: "schema first" },
        { op: "lock", id: 1, reason: "wait for the schema item" },
      ],
    });
    renderPm(project({ backlog: [item(1, "todo", "auth"), item(2, "todo", "schema")] }));
    await screen.findByText("hello pm");
    fireEvent.change(screen.getByPlaceholderText(/Ask the PM/), { target: { value: "reprioritize" } });
    fireEvent.click(screen.getByRole("button", { name: "Send message to the PM" }));
    expect(await screen.findByText("Proposed changes · 2")).toBeInTheDocument();
    expect(screen.getByText("Reorder 2 items")).toBeInTheDocument();
    expect(screen.getByText("Lock auth")).toBeInTheDocument();
  });

  it("request edits autofocuses, sends feedback, and locks into revision state", async () => {
    mocks.projectMessages.mockResolvedValue({ messages: HISTORY });
    mocks.sendMessage.mockResolvedValue({
      reply: "Proposal.",
      changeset: [{ op: "add", title: "A", why: "needed" }],
    });
    renderPm(project());
    await screen.findByText("hello pm");
    fireEvent.change(screen.getByPlaceholderText(/Ask the PM/), { target: { value: "plan" } });
    fireEvent.click(screen.getByRole("button", { name: "Send message to the PM" }));
    await screen.findByText("Proposed change · 1");

    fireEvent.click(screen.getByRole("button", { name: "Request edits" }));
    const ta = screen.getByLabelText("What should change before approval?");
    expect(ta).toHaveFocus();
    fireEvent.change(ta, { target: { value: "smaller scope" } });
    mocks.sendMessage.mockResolvedValue({ reply: "ok", changeset: [] });
    fireEvent.click(screen.getByRole("button", { name: "Send feedback" }));
    expect(await screen.findByText(/Revision requested/)).toBeInTheDocument();
    await waitFor(() =>
      expect(mocks.sendMessage).toHaveBeenLastCalledWith(
        "p1",
        "Please revise this proposal: smaller scope",
        [],
        "sess-1",
      ),
    );
    expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
  });

  it("deny sends the reason and shows the declined state", async () => {
    mocks.projectMessages.mockResolvedValue({ messages: HISTORY });
    mocks.sendMessage.mockResolvedValue({
      reply: "Proposal.",
      changeset: [{ op: "add", title: "A", why: "needed" }],
    });
    renderPm(project());
    await screen.findByText("hello pm");
    fireEvent.change(screen.getByPlaceholderText(/Ask the PM/), { target: { value: "plan" } });
    fireEvent.click(screen.getByRole("button", { name: "Send message to the PM" }));
    await screen.findByText("Proposed change · 1");

    fireEvent.click(screen.getByRole("button", { name: "Deny" }));
    mocks.sendMessage.mockResolvedValue({ reply: "understood", changeset: [] });
    fireEvent.click(screen.getByRole("button", { name: "Not aligned" }));
    expect(await screen.findByText(/Declined — not aligned/)).toBeInTheDocument();
    await waitFor(() =>
      expect(mocks.sendMessage).toHaveBeenLastCalledWith(
        "p1",
        "I'm declining this proposal. Reason: not aligned.",
        [],
        "sess-1",
      ),
    );
    expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
  });


  it("composer: attach and mic are both live now", async () => {
    mocks.projectMessages.mockResolvedValue({ messages: HISTORY });
    renderPm(project());
    await screen.findByText("hello pm");
    expect(screen.getByRole("button", { name: "Attach files" })).toBeEnabled();
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Start voice input" })).toBeEnabled(),
    );
  });

  it("upload flow: chip appears, send carries the attachment id, strip clears", async () => {
    mocks.projectMessages.mockResolvedValue({ messages: HISTORY });
    mocks.uploadAttachment.mockResolvedValue(serverAtt());
    mocks.sendMessage.mockResolvedValue({ reply: "got it", changeset: [] });
    const { container } = renderPm(project());
    await screen.findByText("hello pm");

    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(["# notes"], "notes.md", { type: "text/markdown" });
    fireEvent.change(input, { target: { files: [file] } });
    expect(await screen.findByText("notes.md")).toBeInTheDocument();
    expect(mocks.uploadAttachment).toHaveBeenCalledWith("p1", file, "message_only");
    // Scope chip shows the default and is toggleable pre-send.
    expect(screen.getByText("This message")).toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText(/Ask the PM/), { target: { value: "use it" } });
    fireEvent.click(screen.getByRole("button", { name: "Send message to the PM" }));
    await waitFor(() =>
      expect(mocks.sendMessage).toHaveBeenCalledWith("p1", "use it", ["att-1"], "sess-1"),
    );
    await waitFor(() => expect(screen.queryByText("notes.md")).not.toBeInTheDocument());
  });

  it("upload flow: scope toggle PATCHes the server (no re-upload)", async () => {
    mocks.projectMessages.mockResolvedValue({ messages: HISTORY });
    mocks.uploadAttachment.mockResolvedValue(serverAtt({ filename: "brand.md" }));
    mocks.patchAttachmentScope.mockResolvedValue(
      serverAtt({ filename: "brand.md", scope: "project_context" }),
    );
    const { container } = renderPm(project());
    await screen.findByText("hello pm");
    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, {
      target: { files: [new File(["b"], "brand.md", { type: "text/markdown" })] },
    });
    const scopeBtn = await screen.findByRole("button", { name: /Scope for brand.md/ });
    fireEvent.click(scopeBtn);
    await waitFor(() => expect(screen.getByText("Project context")).toBeInTheDocument());
    expect(mocks.patchAttachmentScope).toHaveBeenCalledWith("p1", "att-1", "project_context");
    expect(mocks.uploadAttachment).toHaveBeenCalledTimes(1); // no re-upload
    expect(mocks.deleteAttachment).not.toHaveBeenCalled();
  });

  it("processing flow: chip polls to ready, send blocked meanwhile, large note shows", async () => {
    vi.useFakeTimers();
    try {
      mocks.projectMessages.mockResolvedValue({ messages: HISTORY });
      mocks.uploadAttachment.mockResolvedValue(
        serverAtt({ filename: "big.pdf", mime_type: "application/pdf", status: "processing" }),
      );
      mocks.getAttachment.mockResolvedValue(
        serverAtt({ filename: "big.pdf", mime_type: "application/pdf", large: true }),
      );
      const { container } = renderPm(project());
      await vi.waitFor(() => expect(screen.getByText("hello pm")).toBeInTheDocument());
      const input = container.querySelector('input[type="file"]') as HTMLInputElement;
      fireEvent.change(input, {
        target: { files: [new File(["%PDF-"], "big.pdf", { type: "application/pdf" })] },
      });
      await vi.waitFor(() => expect(screen.getByText("Processing…")).toBeInTheDocument());
      // Guardrail 13: send blocked with honest copy while processing.
      const send = screen.getByRole("button", { name: "Send message to the PM" });
      expect(send).toBeDisabled();
      expect(send).toHaveAttribute("title", "Processing attachment…");
      // Poll tick → ready with the large-file note (guardrail 14).
      await vi.advanceTimersByTimeAsync(1600);
      await vi.waitFor(() =>
        expect(mocks.getAttachment).toHaveBeenCalledWith("p1", "att-1"),
      );
      await vi.waitFor(() =>
        expect(screen.queryByText("Processing…")).not.toBeInTheDocument(),
      );
      expect(
        screen.getByText("Large file. The PM will use a summary and relevant excerpts."),
      ).toBeInTheDocument();
      expect(send).toBeEnabled();
    } finally {
      vi.useRealTimers();
    }
  });

  it("upload flow: failed upload shows the server reason and never sends its id", async () => {
    mocks.projectMessages.mockResolvedValue({ messages: HISTORY });
    mocks.uploadAttachment.mockRejectedValue(new Error("422 Unprocessable: Unsupported file type"));
    mocks.sendMessage.mockResolvedValue({ reply: "ok", changeset: [] });
    const { container } = renderPm(project());
    await screen.findByText("hello pm");
    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, {
      target: { files: [new File(["x"], "evil.exe", { type: "text/plain" })] },
    });
    expect(await screen.findByText(/Unsupported file type/)).toBeInTheDocument();
    fireEvent.change(screen.getByPlaceholderText(/Ask the PM/), { target: { value: "go" } });
    fireEvent.click(screen.getByRole("button", { name: "Send message to the PM" }));
    await waitFor(() => expect(mocks.sendMessage).toHaveBeenCalledWith("p1", "go", [], "sess-1"));
  });

  it("attachment-only send: file with blank text is sendable, no empty bubble", async () => {
    mocks.projectMessages.mockResolvedValue({ messages: HISTORY });
    mocks.uploadAttachment.mockResolvedValue(
      serverAtt({ filename: "instructions.txt", mime_type: "text/plain" }),
    );
    // Hold the send open so the optimistic pending state is observable.
    let resolveSend: (v: unknown) => void = () => {};
    mocks.sendMessage.mockImplementation(() => new Promise((r) => (resolveSend = r)));
    const { container } = renderPm(project());
    await screen.findByText("hello pm");

    const send = screen.getByRole("button", { name: "Send message to the PM" });
    expect(send).toBeDisabled(); // nothing to send yet
    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, {
      target: { files: [new File(["do X"], "instructions.txt", { type: "text/plain" })] },
    });
    await screen.findByText("instructions.txt");
    // A ready file alone enables send; text stays blank.
    expect(send).toBeEnabled();
    fireEvent.click(send);
    await waitFor(() => expect(mocks.sendMessage).toHaveBeenCalledWith("p1", "", ["att-1"], "sess-1"));
    // Optimistic echo while pending: file card shows, but no empty grey bubble.
    expect(screen.getAllByText("instructions.txt").length).toBeGreaterThan(0);
    const bubbles = [...document.querySelectorAll(".rounded-br-md")];
    expect(bubbles.some((b) => (b.textContent ?? "").trim() === "")).toBe(false);
    resolveSend({ reply: "reviewing the file", changeset: [] });
  });

  it("transcript: image attachments render as big square thumbnails with filename alt", async () => {
    mocks.projectMessages.mockResolvedValue({
      messages: [
        {
          role: "user",
          content: "look at this",
          created_at: "t",
          attachments: [
            {
              id: "att-9", filename: "mockup.png", scope: "project_context",
              size_bytes: 900, mime_type: "image/png",
            },
          ],
        },
      ],
    });
    renderPm(project());
    const img = await screen.findByAltText("mockup.png");
    expect(img).toHaveAttribute("src", "/api/projects/p1/attachments/att-9/thumbnail");
    expect(img.className).toContain("size-28"); // big square, not a tiny icon
    expect(screen.getByText("Context")).toBeInTheDocument(); // scope badge overlay

    // Click → preview overlay with the ORIGINAL image; backdrop click closes.
    fireEvent.click(screen.getByRole("button", { name: "Expand mockup.png" }));
    const dialog = screen.getByRole("dialog", { name: "Preview: mockup.png" });
    const full = dialog.querySelector("img") as HTMLImageElement;
    expect(full.getAttribute("src")).toBe("/api/projects/p1/attachments/att-9/image");
    fireEvent.click(full); // clicking the picture itself does NOT close
    expect(screen.getByRole("dialog", { name: /Preview/ })).toBeInTheDocument();
    fireEvent.click(dialog); // the backdrop does
    expect(screen.queryByRole("dialog", { name: /Preview/ })).not.toBeInTheDocument();
    // Escape closes too.
    fireEvent.click(screen.getByRole("button", { name: "Expand mockup.png" }));
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: /Preview/ })).not.toBeInTheDocument();
  });

  it("transcript: text file cards expand to a document preview overlay", async () => {
    mocks.projectMessages.mockResolvedValue({
      messages: [
        {
          role: "user",
          content: "read this",
          created_at: "t",
          attachments: [
            {
              id: "att-7", filename: "spec.md", scope: "message_only",
              size_bytes: 40, mime_type: "text/markdown",
            },
          ],
        },
      ],
    });
    mocks.attachmentContent.mockResolvedValue({ text: "## The spec body", note: "" });
    renderPm(project());
    fireEvent.click(await screen.findByRole("button", { name: "Expand spec.md" }));
    const dialog = await screen.findByRole("dialog", { name: "Preview: spec.md" });
    expect(mocks.attachmentContent).toHaveBeenCalledWith("p1", "att-7");
    // Rendered as TEXT (never executed markup), inside the overlay.
    expect(await screen.findByText("## The spec body")).toBeInTheDocument();
    fireEvent.click(dialog); // backdrop closes
    expect(screen.queryByRole("dialog", { name: /Preview/ })).not.toBeInTheDocument();
  });

  it("transcript: attachments stay visible on sent messages (chips on the bubble)", async () => {
    mocks.projectMessages.mockResolvedValue({
      messages: [
        {
          role: "user",
          content: "use the brand guide",
          created_at: "2026-07-06T10:00:00Z",
          attachments: [{ id: "att-1", filename: "brand.md", scope: "project_context" }],
        },
        { role: "pm", content: "Done.", created_at: "2026-07-06T10:01:00Z", attachments: [] },
      ],
    });
    renderPm(project());
    expect(await screen.findByText("use the brand guide")).toBeInTheDocument();
    // The file that rode on the message never disappears from the transcript.
    expect(screen.getByText("brand.md")).toBeInTheDocument();
    expect(screen.getByText("Project context")).toBeInTheDocument();
  });

  it("transcript: PM markdown renders (bold + table), user text stays plain", async () => {
    mocks.projectMessages.mockResolvedValue({
      messages: [
        { role: "user", content: "**not markdown**", created_at: "t", attachments: [] },
        {
          role: "pm",
          content: "Here is the **plan**.\n\n| Step | Owner |\n|---|---|\n| Build | PM |",
          created_at: "t",
          attachments: [],
        },
      ],
    });
    renderPm(project());
    // PM reply: bold becomes <strong>, the GFM table becomes a real table.
    expect(await screen.findByText("plan")).toBeInTheDocument();
    expect(screen.getByText("plan").tagName).toBe("STRONG");
    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(screen.getByText("Owner")).toBeInTheDocument();
    // User text is never rendered as markdown.
    expect(screen.getByText("**not markdown**")).toBeInTheDocument();
  });

  it("4D: PM replies show a quiet Used-context line with honest inclusion modes", async () => {
    mocks.projectMessages.mockResolvedValue({
      messages: [
        { role: "user", content: "use the guide", created_at: "t", attachments: [], context_sources: [] },
        {
          role: "pm",
          content: "Done per the guide.",
          created_at: "t",
          attachments: [],
          context_sources: [
            { source_type: "brief", source_id: "", title: "Project brief", included_as: "included_raw", token_count: 0 },
            { source_type: "attachment", source_id: "att-1", title: "brand.md", included_as: "summary", token_count: 40 },
          ],
        },
      ],
    });
    renderPm(project());
    expect(await screen.findByText("Used:")).toBeInTheDocument();
    expect(screen.getByText(/brand\.md/)).toBeInTheDocument();
    expect(screen.getByText(/\(summary\)/)).toBeInTheDocument(); // honest mode label
    // Always-on sources (brief/backlog) stay in the tooltip, not the line.
    expect(screen.queryByText(/Project brief/)).not.toBeInTheDocument();
    expect(screen.getByText("Used:").closest("p")).toHaveAttribute(
      "title",
      "Also used: Project brief",
    );
    // User messages never get the line.
    expect(screen.getAllByText("Used:")).toHaveLength(1);
  });

  it("4D: replies that used no files show no Used line at all", async () => {
    mocks.projectMessages.mockResolvedValue({
      messages: [
        {
          role: "pm",
          content: "Plain answer.",
          created_at: "t",
          attachments: [],
          context_sources: [
            { source_type: "brief", source_id: "", title: "Project brief", included_as: "included_raw", token_count: 0 },
            { source_type: "backlog", source_id: "", title: "Backlog", included_as: "included_raw", token_count: 0 },
          ],
        },
      ],
    });
    renderPm(project());
    expect(await screen.findByText("Plain answer.")).toBeInTheDocument();
    expect(screen.queryByText("Used:")).not.toBeInTheDocument();
  });

  it("backlog handoff: router-state prefill populates the composer, never sends", async () => {
    render(
      <QueryClientProvider
        client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
      >
        <MemoryRouter
          initialEntries={[
            { pathname: "/projects/p1/pm", state: { pmPrefill: "About item X" } },
          ]}
        >
          <PmWorkspace project={project()} />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    const ta = screen.getByPlaceholderText(/Ask the PM/) as HTMLTextAreaElement;
    await waitFor(() => expect(ta).toHaveValue("About item X"));
    expect(mocks.sendMessage).not.toHaveBeenCalled();
    // F73 (#96): the prefill is a sentence STEM the operator finishes, so the caret must sit at
    // the end. Left at 0, typing splices the message into the middle of the stem — which is
    // exactly what happened on the first PM message while driving LedgerCLI (case study #2).
    await waitFor(() => {
      expect(ta.selectionStart).toBe("About item X".length);
      expect(ta.selectionEnd).toBe("About item X".length);
    });
  });

  it("deep-dive: PM messages expose a copy action", async () => {
    mocks.projectMessages.mockResolvedValue({ messages: HISTORY });
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });
    renderPm(project());
    await screen.findByText("Hello! Here is the plan.");
    fireEvent.click(screen.getByRole("button", { name: "Copy message" }));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith("Hello! Here is the plan."));
  });
});

/* --- MR 4C: voice input state machine (guardrail 14's required set) --- */

class FakeRecorder {
  static instances: FakeRecorder[] = [];
  state = "inactive";
  stream = { getTracks: () => [{ stop: vi.fn() }] };
  mimeType = "audio/webm";
  ondataavailable: ((e: { data: Blob }) => void) | null = null;
  onstop: (() => void) | null = null;
  constructor(_s: unknown) {
    FakeRecorder.instances.push(this);
  }
  start() {
    this.state = "recording";
  }
  stop() {
    this.state = "inactive";
    this.ondataavailable?.({ data: new Blob(["aud"], { type: "audio/webm" }) });
    this.onstop?.();
  }
}

class FakeSpeech {
  static last: FakeSpeech | null = null;
  continuous = false;
  interimResults = false;
  onresult: ((e: unknown) => void) | null = null;
  onerror: ((e: unknown) => void) | null = null;
  onend: (() => void) | null = null;
  constructor() {
    FakeSpeech.last = this;
  }
  start() {}
  stop() {
    this.onend?.();
  }
  abort() {}
}

function speechEvent(text: string, isFinal: boolean) {
  return {
    resultIndex: 0,
    results: [Object.assign([{ transcript: text }], { isFinal })],
  };
}

describe("PM voice input", () => {
  beforeEach(() => {
    FakeRecorder.instances = [];
    FakeSpeech.last = null;
    delete (window as unknown as Record<string, unknown>)["webkitSpeechRecognition"];
    vi.stubGlobal("MediaRecorder", FakeRecorder);
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: { getUserMedia: vi.fn().mockResolvedValue({ getTracks: () => [] }) },
    });
    mocks.projectMessages.mockResolvedValue({ messages: HISTORY });
  });

  async function micReady() {
    renderPm(project());
    await screen.findByText("hello pm");
    return await screen.findByRole("button", { name: "Start voice input" });
  }

  it("server route: record → stop → transcript inserted, NEVER auto-sent", async () => {
    mocks.transcribeAudio.mockResolvedValue({
      text: "plan the next sprint", duration_seconds: 3, model: "base", language: "en",
    });
    const mic = await micReady();
    fireEvent.click(mic);
    expect(await screen.findByText(/Recording…/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Stop recording and transcribe" }));
    await waitFor(() => expect(mocks.transcribeAudio).toHaveBeenCalledTimes(1));
    await waitFor(() =>
      expect(screen.getByPlaceholderText(/Ask the PM/)).toHaveValue("plan the next sprint"),
    );
    // Guardrail 6: inserted, editable, never sent.
    expect(mocks.sendMessage).not.toHaveBeenCalled();
  });

  it("Escape during recording cancels cleanly — no transcription request", async () => {
    const mic = await micReady();
    fireEvent.click(mic);
    await screen.findByText(/Recording…/);
    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Start voice input" })).toBeInTheDocument(),
    );
    expect(mocks.transcribeAudio).not.toHaveBeenCalled(); // guardrail 4
    expect(screen.queryByText(/Recording…/)).not.toBeInTheDocument();
  });

  it("browser route: live interim text streams into the takeover preview, finals accepted", async () => {
    (window as unknown as Record<string, unknown>)["webkitSpeechRecognition"] = FakeSpeech;
    const mic = await micReady();
    fireEvent.click(mic);
    await screen.findByText(/Recording…/);
    // Recording takes over the dock: no textarea, a live preview instead.
    expect(screen.queryByPlaceholderText(/Ask the PM/)).not.toBeInTheDocument();
    expect(screen.getByText("Listening…")).toBeInTheDocument();
    const speech = FakeSpeech.last as FakeSpeech;
    act(() => speech.onresult?.(speechEvent("prioritize the", false)));
    expect(screen.getByText("prioritize the")).toBeInTheDocument();
    act(() => speech.onresult?.(speechEvent("prioritize the backlog", true)));
    expect(screen.getByText("prioritize the backlog")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Stop recording and transcribe" }));
    // Textarea returns carrying the dictated text, editable.
    expect(screen.getByPlaceholderText(/Ask the PM/)).toHaveValue("prioritize the backlog");
    expect(mocks.transcribeAudio).not.toHaveBeenCalled(); // text arrived live
    expect(mocks.sendMessage).not.toHaveBeenCalled();
  });

  it("browser speech failure keeps accepted text and falls back for next time", async () => {
    (window as unknown as Record<string, unknown>)["webkitSpeechRecognition"] = FakeSpeech;
    const mic = await micReady();
    fireEvent.click(mic);
    await screen.findByText(/Recording…/);
    const speech = FakeSpeech.last as FakeSpeech;
    act(() => speech.onresult?.(speechEvent("review the homepage", true)));
    act(() => speech.onerror?.({ error: "network" }));
    // Guardrail 3: dictated text preserved; calm fallback notice shown.
    expect(screen.getByPlaceholderText(/Ask the PM/)).toHaveValue("review the homepage");
    expect(await screen.findByText(/next recording will use server transcription/)).toBeInTheDocument();
    // Next recording uses the server route (MediaRecorder), not speech.
    mocks.transcribeAudio.mockResolvedValue({
      text: "and the footer", duration_seconds: 2, model: "base", language: "en",
    });
    fireEvent.click(screen.getByRole("button", { name: "Start voice input" }));
    await screen.findByText(/Recording…/);
    expect(FakeRecorder.instances.length).toBe(1);
  });

  it("disabled status: mic disabled with honest tooltip", async () => {
    mocks.transcribeStatus.mockResolvedValue({
      enabled: false, state: "disabled", model: "base", prefer: "browser_first",
    });
    renderPm(project());
    await screen.findByText("hello pm");
    const mic = await screen.findByRole("button", { name: "Voice input unavailable" });
    expect(mic).toBeDisabled();
    expect(mic).toHaveAttribute("title", "Voice input is not enabled on this instance");
  });

  it("preparing status: honest preparing tooltip, mic still usable", async () => {
    mocks.transcribeStatus.mockResolvedValue({
      enabled: true, state: "preparing", model: "base", prefer: "browser_first",
    });
    renderPm(project());
    await screen.findByText("hello pm");
    const mic = await screen.findByRole("button", { name: "Start voice input" });
    await waitFor(() =>
      expect(mic).toHaveAttribute(
        "title",
        "Voice model is being prepared. This can take a few minutes the first time.",
      ),
    );
  });

  it("whisper failure shows the calm approved copy", async () => {
    mocks.transcribeAudio.mockRejectedValue(new Error("503 model kaboom"));
    const mic = await micReady();
    fireEvent.click(mic);
    await screen.findByText(/Recording…/);
    fireEvent.click(screen.getByRole("button", { name: "Stop recording and transcribe" }));
    expect(
      await screen.findByText("Could not transcribe audio. Try again or type your message."),
    ).toBeInTheDocument();
    // Never the raw error (guardrail 12).
    expect(screen.queryByText(/kaboom/)).not.toBeInTheDocument();
  });

  it("whisper_first never attempts browser speech (guardrail 10)", async () => {
    (window as unknown as Record<string, unknown>)["webkitSpeechRecognition"] = FakeSpeech;
    mocks.transcribeStatus.mockResolvedValue({
      enabled: true, state: "ready", model: "base", prefer: "whisper_first",
    });
    mocks.transcribeAudio.mockResolvedValue({
      text: "hi", duration_seconds: 1, model: "base", language: "en",
    });
    const mic = await micReady();
    fireEvent.click(mic);
    await screen.findByText(/Recording…/);
    expect(FakeSpeech.last).toBeNull(); // speech never constructed
    expect(FakeRecorder.instances.length).toBe(1);
  });
});

describe("PM sessions (issue #30)", () => {
  function renderPmAt(entry: string) {
    return render(
      <QueryClientProvider
        client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
      >
        <MemoryRouter initialEntries={[entry]}>
          <PmWorkspace project={project()} />
        </MemoryRouter>
      </QueryClientProvider>,
    );
  }

  it("opens on the project's most-recent session and scopes the transcript to it", async () => {
    renderPm(project()); // one session: sess-1
    await waitFor(() => expect(mocks.projectMessages).toHaveBeenCalledWith("p1", "sess-1"));
  });

  it("the URL session selects and scopes the transcript (switching preserves per-session context)", async () => {
    mocks.listSessions.mockResolvedValue({
      sessions: [pmSession(), pmSession({ id: "sess-2", title: "Second" })],
    });
    renderPmAt("/projects/p1/pm?session=sess-2");
    // The named session is loaded — not the default — so its history is what shows.
    await waitFor(() => expect(mocks.projectMessages).toHaveBeenCalledWith("p1", "sess-2"));
    expect(mocks.projectMessages).not.toHaveBeenCalledWith("p1", "sess-1");
  });

  it("a stale URL session self-heals to the most-recent live one", async () => {
    // ?session=gone isn't in the list → fall back to sess-1 (no crash, no empty void).
    renderPmAt("/projects/p1/pm?session=gone");
    await waitFor(() => expect(mocks.projectMessages).toHaveBeenCalledWith("p1", "sess-1"));
  });

  it("New session creates a fresh thread", async () => {
    mocks.listSessions.mockResolvedValue({ sessions: [] });
    renderPm(project());
    await screen.findByText("What should we work on next?");
    fireEvent.click(screen.getByRole("button", { name: "New" }));
    await waitFor(() => expect(mocks.createSession).toHaveBeenCalledWith("p1"));
  });

  it("Archive archives the current session (soft — history preserved)", async () => {
    renderPm(project()); // sess-1 selected once the sessions query resolves
    fireEvent.click(await screen.findByRole("button", { name: "Archive session" }));
    await waitFor(() =>
      expect(mocks.patchSession).toHaveBeenCalledWith("p1", "sess-1", { archived: true }),
    );
  });
});


describe("a proposal survives a reload", () => {
  // The defect: the changeset lived only in the send RESPONSE, so a refresh destroyed it — and
  // because the agent strips the proposal out of the reply before storing it, what survived was a
  // bare "Here's what I'd suggest." with nothing under it. The server now stores proposals beside
  // their turn (0031) and the panel rebuilds the card from the transcript.
  const RELOADED: ProjectMessage[] = [
    { role: "user", content: "tidy the backlog", created_at: "2026-07-05T10:00:00Z" },
    {
      id: 42,
      role: "pm",
      content: "Here's what I'd suggest.",
      created_at: "2026-07-05T10:01:00Z",
      proposals: [
        { id: 7, kind: "changeset", payload: [{ op: "enhance", id: 1, title: "Homepage hero" }] },
      ],
    },
  ];

  it("rebuilds the card from the stored proposal, with no send in this session", async () => {
    mocks.projectMessages.mockResolvedValue({ messages: RELOADED });
    renderPm(project({ backlog: [item(1, "todo", "Homepage hero")] }));

    await screen.findByText("Here's what I'd suggest.");
    // The card is back and actionable — not just the meaningless sentence.
    expect(await screen.findByRole("button", { name: /approve/i })).toBeTruthy();
    expect(mocks.sendMessage).not.toHaveBeenCalled();
  });

  it("records the outcome so the card does not come back", async () => {
    mocks.projectMessages.mockResolvedValue({ messages: RELOADED });
    renderPm(project({ backlog: [item(1, "todo", "Homepage hero")] }));

    fireEvent.click(await screen.findByRole("button", { name: /approve/i }));

    await waitFor(() => expect(mocks.applyChangeset).toHaveBeenCalled());
    // Applying is what changes the backlog; this call only RECORDS that the card was settled.
    await waitFor(() => expect(mocks.resolveProposal).toHaveBeenCalledWith("p1", 7, "accepted"));
  });

  it("shows no card when the transcript carries no proposal", async () => {
    mocks.projectMessages.mockResolvedValue({ messages: HISTORY });
    renderPm(project());

    await screen.findByText("Hello! Here is the plan.");
    expect(screen.queryByRole("button", { name: /approve/i })).toBeNull();
  });
});

describe("a turn that didn't complete", () => {
  const WITH_FAILURE: ProjectMessage[] = [
    { role: "user", content: "what should we do about 87?", created_at: "2026-07-05T10:00:00Z" },
    { role: "note", content: "model_failed", created_at: "2026-07-05T10:01:00Z" },
  ];

  it("renders as an engine note, never as the operator's own words", async () => {
    // The panel's role ternary used to be two-way: anything that was not `pm` went down the
    // else-branch into the USER bubble. A failure note landing there would show an engine
    // failure as something the operator had said — the worst rendering available.
    mocks.projectMessages.mockResolvedValue({ messages: WITH_FAILURE });
    renderPm(project());
    const note = await screen.findByRole("note");
    expect(note).toHaveAttribute("data-turn-failure", "model_failed");
    expect(note.textContent).toMatch(/couldn't be reached/);
  });

  it("never renders the bare cause token as a message body", async () => {
    // The row's content is the record (`model_failed`); the sentence is the reading. A generic
    // renderer would put the token on screen as if Quincy had typed it.
    mocks.projectMessages.mockResolvedValue({ messages: WITH_FAILURE });
    renderPm(project());
    await screen.findByRole("note");
    // The token appears only in its labelled slot inside the note, never as prose elsewhere.
    for (const el of screen.getAllByText("model_failed")) {
      expect(el.closest("[data-turn-failure]")).not.toBeNull();
    }
  });

  it("shows no failure note on a healthy thread", async () => {
    mocks.projectMessages.mockResolvedValue({ messages: HISTORY });
    renderPm(project());
    await screen.findByText("Hello! Here is the plan.");
    expect(screen.queryByRole("note")).not.toBeInTheDocument();
  });
});
