"""Authenticated client for the Triumph Technical Information documents API."""

import json
import sys
import time
from pathlib import Path
from urllib.parse import urlencode

import requests

from .config import API_BASE, ManualConfig

REQUEST_DELAY = 0.15  # seconds, polite pause between network requests


class LoginError(RuntimeError):
    """Raised when authentication fails."""


class TriumphClient:
    """Logs in and fetches account, product, document, topic and image data.

    Credentials are passed in explicitly (the CLI resolves them from env/.env/
    prompt). A :class:`ManualConfig` supplies the manual's root id, language and
    product context; it may be set after construction (e.g. after VIN discovery).
    """

    def __init__(self, email: str, password: str, *, config: ManualConfig | None = None,
                 cache_dir: Path = Path(".cache"), verbose: int = 0,
                 use_cache: bool = True, api_base: str = API_BASE):
        self.verbose = verbose
        self.use_cache = use_cache
        self.api_base = api_base
        self.config = config
        self.cache_dir = Path(cache_dir)
        self.topic_cache = self.cache_dir / "topics"
        self.image_cache = self.cache_dir / "images"
        self.topic_cache.mkdir(parents=True, exist_ok=True)
        self.image_cache.mkdir(parents=True, exist_ok=True)

        self.session = requests.Session()
        self._auth = None
        self._root = None
        self._image_mem = {}  # href -> bytes
        self._login(email, password)

    def log(self, level, *args):
        if self.verbose >= level:
            print(*args, file=sys.stderr)

    def _login(self, email, password):
        resp = self.session.post(
            f"{self.api_base}/users/login",
            data={"email": email, "password": password, "remember": True},
        )
        if resp.status_code != 200:
            raise LoginError(f"Login failed ({resp.status_code}). Check email/password.")
        self.log(1, "Logged in OK")

    # -- account / product / document discovery ----------------------------

    def auth(self) -> dict:
        """Fetch (and memoize) the /auth payload (account, subscriptions, prefs)."""
        if self._auth is None:
            r = self.session.get(f"{self.api_base}/auth")
            r.raise_for_status()
            self._auth = r.json()
        return self._auth

    def default_language(self) -> str | None:
        return self.auth().get("user", {}).get("preferences", {}).get("documentLang")

    def subscribed_vins(self) -> list[str]:
        """VIN(s) the account is entitled to, from subscription serial restrictions.

        Active subscriptions are preferred; if none are active, fall back to all.
        """
        subs = self.auth().get("organisationSubscriptions") or []

        def serials(only_active):
            out = []
            for s in subs:
                if only_active and s.get("state") != "active":
                    continue
                for entry in (s.get("restrictions") or {}).get("serial") or []:
                    vin = entry.get("serial")
                    if vin and vin not in out:
                        out.append(vin)
            return out

        return serials(True) or serials(False)

    def product_search(self, vin: str) -> dict:
        """Look up a VIN's product record (model code/year, serial, engine, market)."""
        r = self.session.get(f"{self.api_base}/products/search/{vin}")
        r.raise_for_status()
        return r.json()

    def list_documents(self, product_context: dict) -> list[dict]:
        """List documents available for a product context."""
        r = self.session.get(f"{self.api_base}/documents?{urlencode(product_context)}")
        r.raise_for_status()
        return r.json()

    # -- raw document/topic/image fetches ----------------------------------

    def _ctx(self) -> ManualConfig:
        if self.config is None or not self.config.root_id:
            raise RuntimeError("No manual selected (ManualConfig.root_id is unset).")
        return self.config

    def get_root(self):
        """Fetch (and memoize) the root document, which carries the toc tree."""
        if self._root is None:
            cfg = self._ctx()
            resp = self.session.get(f"{self.api_base}/documents/{cfg.root_id}")
            resp.raise_for_status()
            self._root = resp.json()
            if self._root.get("language") != cfg.language:
                self.log(0, f"WARNING: root language is {self._root.get('language')!r}, "
                            f"expected {cfg.language!r}")
        return self._root

    def get_topic(self, topic_id):
        """Fetch one topic's full record (including its `content` AST)."""
        cfg = self._ctx()
        cache_file = self.topic_cache / f"{topic_id}.json"
        if self.use_cache and cache_file.exists():
            return json.loads(cache_file.read_text())

        time.sleep(REQUEST_DELAY)
        url = (f"{self.api_base}/documents/{cfg.root_id}/{topic_id}"
               f"?{urlencode(cfg.product_context)}")
        resp = self.session.get(url)
        resp.raise_for_status()
        data = resp.json()
        cache_file.write_text(json.dumps(data))
        return data

    def get_image(self, href):
        """Fetch one image asset's bytes."""
        if href in self._image_mem:
            return self._image_mem[href]
        cache_file = self.image_cache / href
        if self.use_cache and cache_file.exists():
            data = cache_file.read_bytes()
            self._image_mem[href] = data
            return data

        cfg = self._ctx()
        time.sleep(REQUEST_DELAY)
        resp = self.session.get(f"{self.api_base}/documents/{cfg.root_id}/images/{href}")
        resp.raise_for_status()
        data = resp.content
        cache_file.write_bytes(data)
        self._image_mem[href] = data
        return data

    # -- toc traversal -----------------------------------------------------

    def iter_toc(self, start_topic=None):
        """Yield (node, depth) for every toc entry, depth-first.

        If start_topic is given, only that node's subtree is yielded.
        """
        root = self.get_root()
        toc = root.get("toc", [])

        def walk(nodes, depth):
            for node in nodes:
                yield node, depth
                yield from walk(node.get("children") or [], depth + 1)

        if start_topic is None:
            yield from walk(toc, 0)
            return

        def find(nodes, depth):
            for node in nodes:
                if str(node.get("id")) == str(start_topic):
                    return node, depth
                hit = find(node.get("children") or [], depth + 1)
                if hit:
                    return hit
            return None

        hit = find(toc, 0)
        if not hit:
            sys.exit(f"ERROR: topic id {start_topic} not found in table of contents")
        node, depth = hit
        yield node, depth
        yield from walk(node.get("children") or [], depth + 1)

    def leaf_topics(self, start_topic=None, limit=None):
        """Return ordered list of (id, title, depth) for selectable leaf topics."""
        leaves = []
        for node, depth in self.iter_toc(start_topic):
            children = node.get("children") or []
            if node.get("selectable") and not children:
                leaves.append((str(node["id"]), node.get("title", ""), depth))
                if limit and len(leaves) >= limit:
                    break
        return leaves
