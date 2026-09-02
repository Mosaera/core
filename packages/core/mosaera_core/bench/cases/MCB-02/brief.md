# Build a static landing page (HTML + CSS)

Build a small, self-contained static website — a single landing page — from an
empty repository. Plain HTML and CSS only: no JavaScript framework, no build
step, no external CDNs. Everything must be local files that open directly in a
browser.

## Files

- `index.html` — the landing page.
- `style.css` — the stylesheet, linked from `index.html` with
  `<link rel="stylesheet" href="style.css">`.
- `logo.svg` — a simple inline-drawable SVG logo you author as a text file
  (e.g. a circle or a monogram), referenced from the page with
  `<img src="logo.svg" alt="...">`.

## Page requirements

- A single top-level `<h1>` with a real product/site name (non-empty text).
- A `<nav>` containing at least three in-page anchor links (`href="#about"`,
  `href="#features"`, `href="#contact"`). Every anchor target must correspond to
  an element on the page with that `id`.
- Three `<section>` elements with matching `id="about"`, `id="features"`, and
  `id="contact"`, each with a heading and a sentence or two of real content.
- The `<img>` referencing `logo.svg`.
- A `<footer>` with a copyright line.
- Valid, well-formed HTML: every non-void tag closed, and every local asset the
  page references (`href`/`src`) must exist in the repository.

## Quality

- Keep the markup semantic and the CSS clean; style the nav and sections.
- No broken local links or missing assets.
