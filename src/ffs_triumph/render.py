"""Convert a topic's content AST into HTML, recording node-type coverage."""

import base64
import html

import requests

# Block-level semantic wrappers rendered as <div class="<node>">.
_BLOCK_DIVS = {
    "instruction", "instructions", "procedural-instructions",
    "consequence", "intermediateresult", "textmodule",
}
# Inline semantic wrappers rendered as <span class="<node>">.
_INLINE_SPANS = {"variable"}

# Hazard triangle (black triangle, white "!") for Warning/Caution/Danger bars.
_SAFETY_ICON = (
    '<svg class="safety-icon" width="15" height="15" viewBox="0 0 24 24" aria-hidden="true">'
    '<path d="M12 2L23 21H1L12 2Z" fill="#111"/>'
    '<rect x="11" y="8.5" width="2" height="6.5" fill="#fff"/>'
    '<rect x="11" y="16.5" width="2" height="2" fill="#fff"/>'
    "</svg>"
)
_HAZARD = {"danger", "warning", "caution"}


def _safe(node_type):
    """Map a node type to a python-identifier suffix for handler lookup."""
    return str(node_type).replace("-", "_") if node_type else "none"


class HtmlRenderer:
    """Converts a topic's content AST into HTML, recording coverage stats."""

    def __init__(self, client, inline_images=False, image_out_dir=None):
        self.client = client
        self.unhandled = {}        # node type -> count (fell through to fallback)
        self.handled_types = set()
        # inline -> base64 data URIs (single portable file, large);
        # otherwise write images to image_out_dir and reference them relatively.
        self.inline_images = inline_images
        self.image_out_dir = image_out_dir
        if not inline_images and image_out_dir:
            image_out_dir.mkdir(parents=True, exist_ok=True)
        self._written = set()
        self._toc_titles = None  # lazy id -> title map for resolving bare links

    # public ---------------------------------------------------------------

    def render_topic(self, topic, base_level):
        """Render a topic's `content` list. `base_level` sets the <h{n}> for titles."""
        parts = []
        for node in topic.get("content") or []:
            parts.append(self._render_node(node, base_level))
        return "".join(parts)

    def plain_text(self, nodes):
        """Concatenate every `text` node's string (for completeness checks)."""
        out = []

        def walk(n):
            if isinstance(n, dict):
                if n.get("node") == "text" and isinstance(n.get("body"), str):
                    out.append(n["body"])
                b = n.get("body")
                if isinstance(b, list):
                    for c in b:
                        walk(c)
            elif isinstance(n, list):
                for c in n:
                    walk(c)

        walk(nodes)
        return "".join(out)

    # internals ------------------------------------------------------------

    def _children_html(self, node, level):
        body = node.get("body")
        if isinstance(body, str):
            return html.escape(body)
        if isinstance(body, list):
            return "".join(self._render_node(c, level) for c in body)
        return ""

    def _render_node(self, node, level):
        if not isinstance(node, dict):
            return ""
        nt = node.get("node")
        self.handled_types.add(nt)
        handler = getattr(self, f"_n_{_safe(nt)}", None)
        if handler:
            return handler(node, level)
        # known structural passthroughs handled generically
        if nt in _BLOCK_DIVS:
            return f'<div class="{html.escape(nt)}">{self._children_html(node, level)}</div>'
        if nt in _INLINE_SPANS:
            return f'<span class="{html.escape(nt)}">{self._children_html(node, level)}</span>'
        # unknown: keep content, flag for the coverage report
        self.unhandled[nt] = self.unhandled.get(nt, 0) + 1
        return f'<div class="unknown-node" data-node="{html.escape(str(nt))}">' \
               f'{self._children_html(node, level)}</div>'

    # leaf text
    def _n_text(self, node, level):
        body = node.get("body")
        return html.escape(body) if isinstance(body, str) else self._children_html(node, level)

    # headings
    def _n_title(self, node, level):
        return f"<h{level} class=\"topic-title\">{self._children_html(node, level)}</h{level}>"

    def _n_subheading(self, node, level):
        lv = min(level + 1, 6)
        return f"<h{lv} class=\"subheading\">{self._children_html(node, lv)}</h{lv}>"

    # inline emphasis
    def _n_b(self, node, level):
        return f"<strong>{self._children_html(node, level)}</strong>"

    def _n_i(self, node, level):
        return f"<em>{self._children_html(node, level)}</em>"

    def _n_sup(self, node, level):
        return f"<sup>{self._children_html(node, level)}</sup>"

    def _n_sub(self, node, level):
        return f"<sub>{self._children_html(node, level)}</sub>"

    # paragraphs
    def _n_p(self, node, level):
        cls = "p"
        if node.get("type"):
            cls += " " + html.escape(str(node["type"]))
        return f'<p class="{cls}">{self._children_html(node, level)}</p>'

    # lists
    def _n_ol(self, node, level):
        t = node.get("type")
        attr = f' type="{html.escape(str(t))}"' if t and str(t) in "1aAiI" else ""
        cls = f' class="ol-{html.escape(str(t))}"' if t else ""
        return f"<ol{attr}{cls}>{self._children_html(node, level)}</ol>"

    def _n_ul(self, node, level):
        cls = f' class="ul-{html.escape(str(node["type"]))}"' if node.get("type") else ""
        return f"<ul{cls}>{self._children_html(node, level)}</ul>"

    def _n_li(self, node, level):
        return f"<li>{self._children_html(node, level)}</li>"

    # tables
    def _n_table_container(self, node, level):
        cls = "table-container"
        if node.get("type"):
            cls += " tc-" + html.escape(str(node["type"]))
        return f'<div class="{cls}">{self._children_html(node, level)}</div>'

    def _n_table_title(self, node, level):
        return f'<div class="table-title">{self._children_html(node, level)}</div>'

    def _n_table(self, node, level):
        colgroup = ""
        widths = node.get("widths")
        if widths:
            try:
                vals = [float(w) for w in str(widths).split()]
                total = sum(vals) or 1.0
                cols = "".join(
                    f'<col style="width:{w / total * 100:.3f}%">' for w in vals
                )
                colgroup = f"<colgroup>{cols}</colgroup>"
            except ValueError:
                colgroup = ""
        cls = "tbl"
        if node.get("type"):
            cls += " tbl-" + html.escape(str(node["type"]))
        return f'<table class="{cls}">{colgroup}{self._children_html(node, level)}</table>'

    def _n_thead(self, node, level):
        return f"<thead>{self._children_html(node, level)}</thead>"

    def _n_tbody(self, node, level):
        return f"<tbody>{self._children_html(node, level)}</tbody>"

    def _n_tr(self, node, level):
        return f"<tr>{self._children_html(node, level)}</tr>"

    def _cell(self, tag, node, level):
        attrs = ""
        for k in ("colspan", "rowspan"):
            if node.get(k):
                attrs += f' {k}="{html.escape(str(node[k]))}"'
        return f"<{tag}{attrs}>{self._children_html(node, level)}</{tag}>"

    def _n_th(self, node, level):
        return self._cell("th", node, level)

    def _n_td(self, node, level):
        return self._cell("td", node, level)

    # safety callouts
    def _n_safety(self, node, level):
        sev = str(node.get("severity") or "note").lower()
        label = sev.capitalize()
        icon = _SAFETY_ICON if sev in _HAZARD else ""
        return (
            f'<div class="safety severity-{html.escape(sev)}">'
            f'<div class="safety-bar">{icon}'
            f'<span class="safety-label">{html.escape(label)}</span></div>'
            f'<div class="safety-body">{self._children_html(node, level)}</div>'
            f"</div>"
        )

    # cross references
    def _topic_title(self, target):
        """Resolve a topic id to its toc title (for links with no text body)."""
        if not target:
            return ""
        if self._toc_titles is None:
            self._toc_titles = {}
            get_root = getattr(self.client, "get_root", None)
            try:
                root = get_root() if get_root else {}
            except Exception:  # noqa: BLE001
                root = {}

            def walk(nodes):
                for n in nodes:
                    self._toc_titles[str(n.get("id"))] = n.get("title", "")
                    walk(n.get("children") or [])

            walk((root or {}).get("toc", []))
        return self._toc_titles.get(str(target), "")

    def _n_link(self, node, level):
        target = node.get("target-base-id") or node.get("target-id")
        href = f"#topic-{html.escape(str(target))}" if target else "#"
        inner = self._children_html(node, level)
        if not inner.strip():  # bare link (common in linklist): use the target's title
            title = self._topic_title(node.get("target-base-id"))
            inner = html.escape(title) if title else "Related topic"
        return f'<a class="xref" href="{href}">{inner}</a>'

    def _n_linklist(self, node, level):
        items = "".join(
            f"<li>{self._render_node(c, level)}</li>"
            for c in (node.get("body") or []) if isinstance(c, dict)
        )
        return f'<ul class="linklist">{items}</ul>'

    def _n_br(self, node, level):
        return "<br>"

    # images
    def _n_image(self, node, level):
        return f'<figure class="image">{self._children_html(node, level)}</figure>'

    def _n_image_container(self, node, level):
        cls = "image-container"
        if node.get("type"):
            cls += " ic-" + html.escape(str(node["type"]))
        return f'<div class="{cls}">{self._children_html(node, level)}</div>'

    def _n_img(self, node, level):
        return self._image_html(node, css_class="figure-img")

    def _n_inline_img(self, node, level):
        return self._image_html(node, css_class="inline-img")

    def _image_html(self, node, css_class):
        href = node.get("href")
        name = node.get("name") or ""
        if not href:
            return ""
        try:
            data = self.client.get_image(href)
        except requests.HTTPError as err:
            self.client.log(0, f"WARNING: image {href} failed: {err}")
            return f'<span class="img-missing">[missing image: {html.escape(href)}]</span>'
        alt = html.escape(name)
        src = self._image_src(href, data)
        return f'<img class="{css_class}" alt="{alt}" title="{alt}" src="{src}">'

    def _image_src(self, href, data):
        """Return an <img> src: base64 data URI (inline) or a relative file path."""
        if self.inline_images or not self.image_out_dir:
            mime = "image/svg+xml" if href.lower().endswith(".svg") else "image/png"
            b64 = base64.b64encode(data).decode("ascii")
            return f"data:{mime};base64,{b64}"
        if href not in self._written:
            (self.image_out_dir / href).write_bytes(data)
            self._written.add(href)
        return f"images/{href}"
