# History

All notable changes to **ffs-triumph** (FFS — Full-manual Fetcher & Stitcher).

## 0.2.0 — 2026-06-30

- Retry on HTTP 429 (Too Many Requests) with exponential backoff, so large
  manual downloads survive the API's rate limiting instead of aborting.
- Honor the server's `Retry-After` header (seconds or HTTP-date) when present,
  waiting exactly as long as asked rather than guessing.
- Route all document, image, and discovery requests through the shared
  backoff/retry helper for consistent handling.
- Add offline unit tests for the retry logic and `Retry-After` parsing.

## 0.1.4 — 2026-06-25

- Render more of the content vocabulary found across Triumph documents:
  - `table-title` — table captions.
  - `linklist` — "related topics" link lists; bare links with no text now show the
    target topic's title (resolved from the table of contents).
  - `br` — line breaks.
- Restyle Danger / Warning / Caution callouts to match the official handbook: a
  solid colored title bar (red / orange / yellow) with a hazard-triangle icon over
  a bordered body. Notes use a plain grey bar with no icon.
- Add this changelog.

## 0.1.3 — 2026-06-25

- Add the motorcycle's photo to the PDF cover page (fetched from the account).
- Match the official handbook more closely: geometric headings (Avenir/Futura,
  echoing Triumph's brand font), UPPERCASE section headers, and justified +
  hyphenated body text.
- Include the vehicle year in the document title and the output filename.

## 0.1.2 — 2026-06-25

- Add a per-page footer crediting FFS with the project URL.
- Produce a tagged PDF with a heading-based outline, so viewers (e.g. macOS
  Preview) show a table of contents in the sidebar.

## 0.1.1 — 2026-06-25

- Documentation: add a "Motivation" section to the README.

## 0.1.0 — 2026-06-25

Initial release.

- Log in with a Triumph Technical Information account and **auto-detect the
  motorcycle** from the subscription VIN (menu when several), then **auto-select
  the Service Manual** for the chosen language.
- Crawl the whole manual, convert the site's structured content (a JSON AST, not
  HTML) to HTML, inline the SVG figures, and render a paginated, self-contained
  **PDF** with a title page, table of contents, and page breaks.
- CLI: `build`, `discover`, `list`, `audit`, `install-browser`; credentials from
  flags / env / `.env` / config / prompts. Usable as a library, too.
