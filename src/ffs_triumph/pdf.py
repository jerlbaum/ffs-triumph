"""Render an assembled HTML document to a paginated PDF via headless Chromium."""

import html
import subprocess
import sys
from pathlib import Path

_NO_PLAYWRIGHT = (
    "ERROR: Playwright's Chromium is not available. Install it with:\n"
    "    ffs install-browser\n"
    "(or: python -m playwright install chromium). "
    "Use --html-only to skip PDF rendering."
)


def install_browser() -> int:
    """Download the Chromium build Playwright needs. Returns an exit code."""
    try:
        import playwright  # noqa: F401
    except ImportError:
        print("ERROR: the 'playwright' package is not installed.", file=sys.stderr)
        return 1
    return subprocess.call([sys.executable, "-m", "playwright", "install", "chromium"])


def render_pdf(html_path: Path, pdf_path: Path, doc_title: str):
    """Render an HTML file to a paginated PDF via headless Chromium (Playwright)."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        sys.exit(_NO_PLAYWRIGHT)

    footer = (
        '<div style="font-size:7px; width:100%; text-align:center; color:#888; '
        'line-height:1.5; font-family:Arial, sans-serif; padding:0 12mm;">'
        '<div>Created by the Full-manual Fetcher &amp; Stitcher. For more information '
        'about this free tool, go to https://github.com/jerlbaum/ffs-triumph</div>'
        '<div>Page <span class="pageNumber"></span> of '
        '<span class="totalPages"></span></div>'
        '</div>'
    )
    header = (
        '<div style="font-size:8px; width:100%; text-align:center; color:#999;">'
        f'{html.escape(doc_title)}</div>'
    )

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            page.goto(html_path.resolve().as_uri(), wait_until="networkidle")
            page.pdf(
                path=str(pdf_path),
                format="A4",
                print_background=True,
                prefer_css_page_size=True,
                display_header_footer=True,
                header_template=header,
                footer_template=footer,
                margin={"top": "22mm", "bottom": "24mm", "left": "16mm", "right": "16mm"},
                # Build a tagged PDF with a heading-based outline so viewers
                # (e.g. macOS Preview) show a table of contents in the sidebar.
                tagged=True,
                outline=True,
            )
            browser.close()
    except Exception as err:  # most commonly: Chromium not installed
        if "Executable doesn't exist" in str(err) or "playwright install" in str(err):
            sys.exit(_NO_PLAYWRIGHT)
        raise
