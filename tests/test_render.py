"""Offline unit tests for the AST -> HTML renderer (no network, no Chromium)."""

import base64

from ffs_triumph.render import HtmlRenderer


class StubClient:
    """Minimal stand-in for TriumphClient: returns fixed bytes for any image."""

    SVG = b'<svg xmlns="http://www.w3.org/2000/svg"></svg>'

    def get_image(self, href):
        return self.SVG

    def log(self, level, *args):
        pass


def render(content, base_level=2, **kw):
    r = HtmlRenderer(StubClient(), inline_images=True, **kw)
    html = r.render_topic({"content": content}, base_level)
    return html, r


def test_paragraph_and_escaping():
    html, r = render([{"node": "p", "body": [{"node": "text", "body": "a < b & c"}]}])
    assert '<p class="p">a &lt; b &amp; c</p>' == html
    assert r.unhandled == {}


def test_title_uses_base_level():
    html, _ = render([{"node": "title", "body": [{"node": "text", "body": "Hi"}]}],
                     base_level=3)
    assert html == '<h3 class="topic-title">Hi</h3>'


def test_nested_lists():
    content = [{"node": "ul", "type": "dash", "body": [
        {"node": "li", "body": [{"node": "p", "body": [{"node": "text", "body": "x"}]}]},
    ]}]
    html, r = render(content)
    assert 'class="ul-dash"' in html
    assert "<li><p class=\"p\">x</p></li>" in html
    assert r.unhandled == {}


def test_table_widths_and_colspan():
    content = [{"node": "table", "widths": "1 3", "type": "scaled", "body": [
        {"node": "tbody", "body": [
            {"node": "tr", "body": [
                {"node": "td", "colspan": "2", "body": [{"node": "text", "body": "c"}]},
            ]},
        ]},
    ]}]
    html, r = render(content)
    assert "<colgroup>" in html and "width:25.000%" in html and "width:75.000%" in html
    assert '<td colspan="2">c</td>' in html
    assert r.unhandled == {}


def test_safety_severity():
    content = [{"node": "safety", "severity": "warning",
                "body": [{"node": "text", "body": "Careful"}]}]
    html, _ = render(content)
    assert 'class="safety severity-warning"' in html
    assert ">WARNING<" in html and "Careful" in html


def test_link_uses_anchor():
    content = [{"node": "link", "target-base-id": "999",
                "body": [{"node": "text", "body": "see"}]}]
    html, _ = render(content)
    assert '<a class="xref" href="#topic-999">see</a>' == html


def test_inline_emphasis_and_scripts():
    content = [
        {"node": "i", "body": [{"node": "text", "body": "it"}]},
        {"node": "sup", "body": [{"node": "text", "body": "2"}]},
        {"node": "sub", "body": [{"node": "text", "body": "n"}]},
        {"node": "b", "body": [{"node": "text", "body": "B"}]},
    ]
    html, r = render(content)
    assert "<em>it</em><sup>2</sup><sub>n</sub><strong>B</strong>" == html
    assert r.unhandled == {}


def test_image_inlined_as_data_uri():
    content = [{"node": "img", "href": "x__Web.svg", "name": "Fig 1", "body": []}]
    html, _ = render(content)
    b64 = base64.b64encode(StubClient.SVG).decode()
    assert f'src="data:image/svg+xml;base64,{b64}"' in html
    assert 'alt="Fig 1"' in html and 'class="figure-img"' in html


def test_unknown_node_is_flagged_but_keeps_content():
    content = [{"node": "mystery", "body": [{"node": "text", "body": "kept"}]}]
    html, r = render(content)
    assert "kept" in html and 'data-node="mystery"' in html
    assert r.unhandled == {"mystery": 1}


def test_plain_text_extraction():
    content = [{"node": "p", "body": [{"node": "text", "body": "one "},
                                      {"node": "b", "body": [{"node": "text", "body": "two"}]}]}]
    r = HtmlRenderer(StubClient(), inline_images=True)
    assert r.plain_text(content) == "one two"
