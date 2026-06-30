"""Authenticated client for the Triumph Technical Information documents API."""

import json
import sys
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlencode

import requests

from .config import API_BASE, ManualConfig

REQUEST_DELAY = 0.15  # seconds, polite pause between network requests


class LoginError(RuntimeError):
    """Raised when authentication fails."""
    
class RequestRetryFailure(RuntimeError):
    """Out of retries. Giving up."""


def _parse_retry_after(value):
    """Parse a Retry-After header into seconds (float), or None if absent/unparseable.

    Supports both RFC 7231 forms: an integer number of seconds, or an HTTP-date.
    Past/negative dates clamp to 0.
    """
    if not value:
        return None
    value = value.strip()
    if value.isdigit():
        return float(value)
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when is None:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return max(0.0, (when - datetime.now(timezone.utc)).total_seconds())


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
            r = self._get_with_backoff_retry(f"{self.api_base}/auth")
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
        r = self._get_with_backoff_retry(f"{self.api_base}/products/search/{vin}")
        return r.json()

    def list_documents(self, product_context: dict) -> list[dict]:
        """List documents available for a product context."""
        r = self._get_with_backoff_retry(f"{self.api_base}/documents?{urlencode(product_context)}")
        return r.json()

    def get_product_image(self) -> tuple[bytes | None, str]:
        """Fetch the motorcycle cover image, if the config has its URL.

        Returns (bytes, content_type), or (None, "") on any failure.
        """
        url = self.config.product_image_url if self.config else None
        if not url:
            return None, ""
        try:
            r = self._get_with_backoff_retry(url)
        except (requests.RequestException, RequestRetryFailure) as err:
            self.log(0, f"WARNING: cover image fetch failed: {err}")
            return None, ""
        return r.content, r.headers.get("content-type", "image/png")

    # -- raw document/topic/image fetches ----------------------------------

    def _ctx(self) -> ManualConfig:
        if self.config is None or not self.config.root_id:
            raise RuntimeError("No manual selected (ManualConfig.root_id is unset).")
        return self.config
    
    def _get_with_backoff_retry(self, url, params=None, retries=4, backoff_base=3, **kwargs):
        """
        Do a self-session.get(), and retry N times with an exponential backoff between failures.

        Args:
            url: Passed to requests.get()
            params: Passed to requests.get(). Defaults to None.
            retries: Number of retries before giving up. Defaults to 4.
            backoff_base: Seconds to backoff**N, where N is the number of the retry. Defaults to 3.
            **kwargs: Passed to requests.get()
            
        NOTES:
        The backoff (sleep) time is calculated as follows (for example), given parameters:
        
        - REQUEST_DELAY: 0.15
        - retries: 4
        - backoff_base: 3
        
        Try #0: sleep_time 0.15 seconds [Use REQUEST_DELAY: 0.15 sec]
        Try #1: sleep_time 3 seconds    [backoff_base**retry N: 3**1=3 sec]
        Try #2: sleep_time 9 seconds    [backoff_base**retry N: 3**2=9 sec]
        Try #3: sleep_time 27 seconds   [backoff_base**retry N: 3**3=27 sec]
        Try #4: sleep_time 81 seconds   [backoff_base**retry N: 3**4=81 sec]
        """
        self.log(2, f"Getting URL: {url}")
        
        retry_count = 0
        sleep_time = REQUEST_DELAY
        while True:
            if retry_count>retries:
                raise RequestRetryFailure(f'Unable to retrieve URL after retrying {retries} times: {url}')

            if retry_count:
                self.log(0, f"Sleeping {sleep_time} seconds and retrying ({retry_count}/{retries})")
                
            time.sleep(sleep_time)
            
            retry_after = None
            try:
                resp = self.session.get(url, params=params, **kwargs)
                resp.raise_for_status()
            except requests.exceptions.HTTPError as e:
                status_code = e.response.status_code
                if status_code != 429:
                    # Something else. Reraise
                    raise
                retry_after = _parse_retry_after(e.response.headers.get("Retry-After"))
                if retry_after is not None:
                    self.log(0, f"WARNING: 429 Client Error (Too Many Requests). "
                                f"Server asked to wait {retry_after} seconds.")
                else:
                    self.log(0, "WARNING: 429 Client Error (Too Many Requests).")
            else:
                # Successful request
                break
            
            # Back off and (maybe) try again. Honor Retry-After when the server
            # sent it; otherwise fall back to the exponential schedule.
            retry_count += 1
            sleep_time = retry_after if retry_after is not None else backoff_base**retry_count
                
        return resp


    def get_root(self):
        """Fetch (and memoize) the root document, which carries the toc tree."""
        if self._root is None:
            cfg = self._ctx()
            resp = self._get_with_backoff_retry(f"{self.api_base}/documents/{cfg.root_id}")
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

        url = (f"{self.api_base}/documents/{cfg.root_id}/{topic_id}"
               f"?{urlencode(cfg.product_context)}")
        resp = self._get_with_backoff_retry(url)

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
        url = f"{self.api_base}/documents/{cfg.root_id}/images/{href}"
        resp = self._get_with_backoff_retry(url)

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
