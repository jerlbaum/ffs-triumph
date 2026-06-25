"""Configuration: API defaults, the ManualConfig model, credential + config I/O.

The config file is a small, hand-readable TOML subset (flat ``key = "value"``
lines). We read/write it ourselves so the package needs no TOML dependency and
works on Python 3.10 (where ``tomllib`` is unavailable).
"""

import os
from dataclasses import dataclass, field
from pathlib import Path

API_BASE = "https://api.triumphtechnicalinformation.com"
DEFAULT_LANGUAGE = "en-gb"
DEFAULT_DOC_TYPE = "Service Manual"

# Env var names for credentials.
ENV_EMAIL = "TTI_EMAIL"
ENV_PASSWORD = "TTI_PASSWORD"


@dataclass
class ManualConfig:
    """Everything needed to fetch one manual: where it is and which bike it's for."""

    root_id: str | None = None
    language: str = DEFAULT_LANGUAGE
    api_base: str = API_BASE
    # Query params the content endpoint requires (403 without them).
    product_context: dict = field(default_factory=dict)
    # For display / output filename only.
    model_name: str | None = None
    model_year: str | None = None
    vin: str | None = None
    # Optional motorcycle image (PNG) shown on the PDF cover.
    product_image_url: str | None = None

    @classmethod
    def from_product(cls, product: dict, language: str = DEFAULT_LANGUAGE,
                     api_base: str = API_BASE, root_id: str | None = None):
        """Build from a ``/products/search/{VIN}`` response."""
        return cls(
            root_id=root_id,
            language=language,
            api_base=api_base,
            product_context={
                "modelCode": product.get("modelCode", ""),
                "modelYear": str(product.get("modelYear", "")),
                "serial": product.get("serialNumberStub", ""),
                "engineNo": product.get("engineNo", ""),
                "market": product.get("marketSpec", ""),
                "state": "published",
                "onlyValid": "true",
            },
            model_name=product.get("modelName"),
            model_year=str(product.get("modelYear", "")) or None,
            vin=product.get("serialNumber"),
            product_image_url=product.get("productImageUrl"),
        )

    def slug(self) -> str:
        """A filesystem-safe base name for output files (includes the year)."""
        base = self.model_name or "triumph service manual"
        if self.model_year and str(self.model_year) not in base:
            base = f"{self.model_year} {base}"
        out = "".join(c if c.isalnum() else "_" for c in base.lower())
        while "__" in out:
            out = out.replace("__", "_")
        return out.strip("_") or "manual"


# --- credential + config file helpers --------------------------------------

def _parse_kv(text: str) -> dict:
    """Parse flat ``key = value`` / ``key=value`` lines (quotes optional)."""
    data = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("[") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        data[key.strip()] = val.strip().strip('"').strip("'")
    return data


def read_dotenv(start: Path | None = None) -> dict:
    """Read a ``.env`` from the current directory (if present)."""
    path = (start or Path.cwd()) / ".env"
    return _parse_kv(path.read_text()) if path.exists() else {}


def user_config_path() -> Path:
    """`$XDG_CONFIG_HOME/ffs-triumph/config.toml` (default ~/.config/...)."""
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "ffs-triumph" / "config.toml"


def load_config_file() -> dict:
    """Merge user config then local ./ffs.toml (local wins)."""
    data: dict = {}
    up = user_config_path()
    if up.exists():
        data.update(_parse_kv(up.read_text()))
    local = Path.cwd() / "ffs.toml"
    if local.exists():
        data.update(_parse_kv(local.read_text()))
    return data


def save_config_file(values: dict, path: Path | None = None) -> Path:
    """Write a small TOML config (never includes the password)."""
    path = path or user_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# ffs-triumph saved settings (password is never stored here)"]
    for key in ("email", "vin", "root_id", "language"):
        if values.get(key):
            lines.append(f'{key} = "{values[key]}"')
    path.write_text("\n".join(lines) + "\n")
    return path


def credentials_from_env_and_dotenv() -> tuple[str | None, str | None]:
    """Return (email, password) from env or a local .env, if available."""
    env = dict(read_dotenv())
    env.update(os.environ)  # real env wins over .env
    return env.get(ENV_EMAIL), env.get(ENV_PASSWORD)
