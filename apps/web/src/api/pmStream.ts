/* Sending a PM message and watching the turn happen.
 *
 * Lives outside `client.ts` for two reasons: that file is held at its recorded size by the
 * god-file ratchet, and this is a different shape of call — everything there resolves once with
 * a parsed body, where this one reports as it goes.
 *
 * The runs stream uses `EventSource`, which is GET-only; a chat turn is a POST with a body, so it
 * reads its own streamed response instead. Auth needs nothing special — a normal same-origin POST
 * carries the session cookie, where EventSource forced the `?token=` arrangement on the run path.
 */

import { api } from "./client";
import { apiFetch } from "./auth";
import { createSseParser } from "@/lib/sse";

/** One lookup Quincy made, live or as stored with the finished turn. */
export type PmStep = { kind: string; tool: string; arg: string; duration_ms?: number };

/** What a watcher is told while the turn runs. `text` is prose he produced mid-turn; the FINAL
 *  reply never arrives this way, because the transcript renders it. */
export type PmStreamEvent =
  | { event: "step"; data: { id?: string; kind: string; detail: string } }
  | { event: "text"; data: { text: string } }
  | { event: "done"; data: PmTurnResult }
  | { event: "error"; data: { detail: string } };

export type PmTurnResult = Awaited<ReturnType<typeof api.sendMessage>> & { steps?: PmStep[] };

/** Send a message and report the turn as it happens; resolves with the same result the plain
 *  endpoint returns.
 *
 *  Falls back to that plain endpoint whenever streaming is not actually available — no body
 *  reader, or a response that is not an event stream. The fallback is why the existing chat tests
 *  keep passing unchanged, and they are therefore its regression guard.
 *
 *  A watcher that throws is not allowed to lose the turn: the reply matters more than the
 *  animation, which is the same rule the server applies to its own step listener. */
export async function sendMessageStreaming(
  projectId: string,
  text: string,
  attachmentIds: string[],
  sessionId: string | undefined,
  onEvent: (event: PmStreamEvent) => void,
): Promise<PmTurnResult> {
  let response: Response;
  try {
    response = await apiFetch(`/api/projects/${projectId}/messages/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        text,
        attachments: attachmentIds.map((attachment_id) => ({ attachment_id })),
        session_id: sessionId ?? null,
      }),
    });
  } catch {
    // The request never landed — an older server without this route, a proxy in the way. Nothing
    // ran, so sending again on the plain endpoint is safe and is the whole point of the fallback.
    //
    // Note where this catch ENDS: once bytes have been read the turn is underway on the server,
    // and retrying then would risk a second turn from one message. A failure after that point is
    // reported, never retried.
    return api.sendMessage(projectId, text, attachmentIds, sessionId);
  }

  const streaming = response.body && response.headers.get("content-type")?.includes("event-stream");
  if (!streaming) {
    return api.sendMessage(projectId, text, attachmentIds, sessionId);
  }

  const reader = response.body!.getReader();
  const decoder = new TextDecoder();
  const parse = createSseParser();
  let result: PmTurnResult | null = null;

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    for (const frame of parse(decoder.decode(value, { stream: true }))) {
      const typed = frame as PmStreamEvent;
      if (typed.event === "done") result = typed.data;
      if (typed.event === "error") throw new Error(typed.data.detail);
      try {
        onEvent(typed);
      } catch {
        // Watching is decoration. Losing it costs the status line; letting it throw here would
        // cost the answer.
      }
    }
  }

  if (!result) {
    // The stream ended without saying how the turn went. The work itself runs on the server and
    // finished or will; the transcript is the authority, so ask it rather than inventing a reply.
    throw new Error("the connection ended before the turn finished");
  }
  return result;
}
