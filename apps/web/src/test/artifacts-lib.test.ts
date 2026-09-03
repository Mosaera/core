import { describe, expect, it } from "vitest";

import {
  artifactsSummary,
  clipPreview,
  groupPathsByFolder,
  previewKind,
  TEXT_PREVIEW_LIMIT,
} from "../lib/artifacts";

describe("groupPathsByFolder", () => {
  it("groups by top-level folder with (root) for bare files, ordered by size then name", () => {
    const groups = groupPathsByFolder([
      "pages/index.html",
      "pages/about.html",
      "README.md",
      "css/style.css",
    ]);
    expect(groups.map((g) => g.name)).toEqual(["pages", "(root)", "css"]);
    expect(groups[0].files).toEqual(["pages/index.html", "pages/about.html"]);
    expect(groupPathsByFolder([])).toEqual([]);
  });
});

describe("previewKind", () => {
  it("classifies by extension, case-insensitive", () => {
    expect(previewKind("a/logo.SVG")).toBe("image");
    expect(previewKind("shot.png")).toBe("image");
    expect(previewKind("doc.pdf")).toBe("pdf");
    expect(previewKind("src/app.tsx")).toBe("text");
    expect(previewKind("README.md")).toBe("text");
    expect(previewKind("index.html")).toBe("text");
    expect(previewKind("font.woff2")).toBe("none");
    expect(previewKind("Makefile")).toBe("none"); // no extension
  });
});

describe("artifactsSummary", () => {
  it("counts only what is honestly knowable; patch only when files exist", () => {
    expect(artifactsSummary(5, true)).toBe("5 files · patch available · brief");
    expect(artifactsSummary(1, false)).toBe("1 file · patch available");
    expect(artifactsSummary(0, true)).toBe("0 files · brief");
    expect(artifactsSummary(0, false)).toBe("0 files");
  });
});

describe("clipPreview", () => {
  it("passes small text through and truncates past the limit", () => {
    expect(clipPreview("hello")).toEqual({ text: "hello", truncated: false });
    const big = "x".repeat(TEXT_PREVIEW_LIMIT + 10);
    const clipped = clipPreview(big);
    expect(clipped.truncated).toBe(true);
    expect(clipped.text).toHaveLength(TEXT_PREVIEW_LIMIT);
  });
});
