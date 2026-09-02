/* Parsing server-sent frames out of a byte stream.
 *
 * Separate from the network on purpose: a parser that owns no fetch can be tested with a string,
 * and the awkward cases here are all about chunk boundaries — a frame arriving in two pieces, a
 * heartbeat comment, a trailing partial that must NOT be emitted until it is whole. Those are
 * cheap to get wrong and cheap to pin, but only if the parser is reachable on its own. */

export type SseFrame = { event: string; data: unknown };

/** Accumulates bytes and hands back whole frames.
 *
 *  Frames are separated by a blank line, so anything after the last one is an incomplete frame
 *  and is held for the next chunk. Splitting on single newlines instead would emit half a JSON
 *  payload the moment a message crossed a packet boundary — which happens exactly when the reply
 *  is long, i.e. when it matters. */
export function createSseParser(): (chunk: string) => SseFrame[] {
  let buffer = "";
  return (chunk: string): SseFrame[] => {
    buffer += chunk;
    const frames: SseFrame[] = [];
    let cut = buffer.indexOf("\n\n");
    while (cut !== -1) {
      const block = buffer.slice(0, cut);
      buffer = buffer.slice(cut + 2);
      const frame = parseBlock(block);
      if (frame) frames.push(frame);
      cut = buffer.indexOf("\n\n");
    }
    return frames;
  };
}

function parseBlock(block: string): SseFrame | null {
  let event = "message";
  const dataLines: string[] = [];
  for (const line of block.split("\n")) {
    // A line starting with ':' is a comment — the heartbeat that keeps a proxy from buffering
    // the connection closed. It carries nothing and must not become a frame.
    if (!line || line.startsWith(":")) continue;
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
  }
  if (!dataLines.length) return null;
  try {
    return { event, data: JSON.parse(dataLines.join("\n")) };
  } catch {
    // A frame we cannot read is dropped, not thrown: one malformed payload must not end a turn
    // that is otherwise going fine.
    return null;
  }
}
