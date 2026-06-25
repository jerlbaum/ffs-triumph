"""FFS — Full-manual Fetcher & Stitcher.

Turn a Triumph Technical Information service manual (a JavaScript SPA) into a
single, self-contained, paginated PDF for offline viewing and printing.
"""

__version__ = "0.1.0"

from .client import LoginError, TriumphClient
from .config import ManualConfig
from .render import HtmlRenderer

__all__ = ["TriumphClient", "LoginError", "ManualConfig", "HtmlRenderer", "__version__"]
