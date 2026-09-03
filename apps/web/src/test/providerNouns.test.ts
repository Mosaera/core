import { describe, expect, it } from "vitest";

import { providerNouns } from "../lib/providerNouns";

describe("providerNouns", () => {
  it("names GitLab's vocabulary", () => {
    const n = providerNouns("gitlab");
    expect(n).toEqual({
      request: "merge request",
      Request: "Merge request",
      short: "MR",
      hostName: "GitLab",
    });
  });

  it("names GitHub's vocabulary", () => {
    const n = providerNouns("github");
    expect(n).toEqual({
      request: "pull request",
      Request: "Pull request",
      short: "PR",
      hostName: "GitHub",
    });
  });

  it("falls back to neutral copy for unknown/null/undefined — never guesses a real forge", () => {
    for (const provider of ["unknown", null, undefined] as const) {
      const n = providerNouns(provider);
      expect(n.hostName).toBe("the remote");
      expect(n.request).toBe("change request");
      expect(n.short).toBe("request");
    }
  });
});
