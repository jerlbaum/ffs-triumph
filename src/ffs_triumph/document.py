"""Assemble rendered topics into one paginated, print-ready HTML document."""

import html

PRINT_CSS = """
@page { size: A4; margin: 18mm 16mm 20mm 16mm; }
* { box-sizing: border-box; }
body { font-family: "Helvetica Neue", Arial, sans-serif; font-size: 10.5pt;
       line-height: 1.4; color: #111; }
h1, h2, h3, h4, h5, h6 { font-family: Arial, sans-serif; color: #15171a;
       break-after: avoid; margin: 0.8em 0 0.3em; }
h1 { font-size: 20pt; } h2 { font-size: 15pt; } h3 { font-size: 12.5pt; }
p { margin: 0.35em 0; }
strong { font-weight: 700; }
a.xref { color: #0b5394; text-decoration: none; }
.variable { font-family: "SFMono-Regular", Menlo, monospace; }

/* chapters start on a new page */
.chapter { break-before: page; }
.chapter:first-of-type { break-before: avoid; }
section.topic { break-inside: auto; margin-bottom: 0.6em; }

/* tables */
table.tbl { border-collapse: collapse; width: 100%; margin: 0.5em 0;
            break-inside: avoid; font-size: 9.5pt; }
table.tbl th, table.tbl td { border: 0.5pt solid #999; padding: 3pt 5pt;
            vertical-align: top; text-align: left; }
table.tbl thead { display: table-header-group; }
table.tbl th { background: #eef1f4; }
.table-container { break-inside: avoid; margin: 0.6em 0; }

/* figures */
.image-container, figure.image { break-inside: avoid; margin: 0.6em 0; text-align: center; }
/* Cap figure height so a heading + its figure always fit together on one page.
   A4 printable height is ~255mm; reserving ~40mm for heading(s) keeps the figure
   from being pushed to the next page and orphaning its title. */
.figure-img { max-width: 100%; max-height: 215mm; height: auto; }
.img-missing { color: #b00; font-style: italic; }

/* safety callouts */
.safety { break-inside: avoid; border: 1pt solid; border-radius: 4px;
          padding: 6pt 9pt; margin: 0.6em 0; }
.safety-label { font-weight: 700; font-size: 9pt; letter-spacing: 0.05em;
          margin-bottom: 3pt; }
.severity-warning, .severity-caution { border-color: #c47f00; background: #fff7e6; }
.severity-warning .safety-label, .severity-caution .safety-label { color: #9a5b00; }
.severity-danger { border-color: #b00; background: #fdecec; }
.severity-danger .safety-label { color: #900; }
.severity-note, .safety { border-color: #999; background: #f5f7f9; }

/* lists */
ol, ul { margin: 0.35em 0; padding-left: 1.6em; }
li { margin: 0.15em 0; }
li > p { margin: 0; }              /* keep marker aligned with first line */
li > p ~ p { margin-top: 0.3em; }  /* but space multiple paragraphs in one item */
ul.ul-dash { list-style-type: "\\2013\\00a0\\00a0"; }

/* table of contents */
.toc { break-after: page; }
.toc ul { list-style: none; padding-left: 1.1em; }
.toc a { text-decoration: none; color: #111; }
.toc .toc-leaf { color: #333; }
.titlepage { text-align: center; padding-top: 28%; break-after: page; }
.titlepage h1 { font-size: 30pt; }
.titlepage .sub { font-size: 13pt; color: #555; margin-top: 0.5em; }
"""


def build_toc_html(client, start_topic=None):
    """Build a nested HTML table of contents from the toc tree."""
    root = client.get_root()
    toc = root.get("toc", [])

    def render(nodes):
        items = []
        for node in nodes:
            nid = str(node.get("id"))
            title = html.escape(node.get("title", ""))
            children = node.get("children") or []
            is_leaf = node.get("selectable") and not children
            anchor = f"topic-{nid}" if is_leaf else f"sec-{nid}"
            cls = "toc-leaf" if is_leaf else "toc-sec"
            sub = render(children) if children else ""
            items.append(f'<li class="{cls}"><a href="#{anchor}">{title}</a>{sub}</li>')
        return f"<ul>{''.join(items)}</ul>" if items else ""

    if start_topic is not None:
        # restrict the TOC to the requested subtree (its root is the first yield)
        subtree_root = next(client.iter_toc(start_topic))[0]
        return render([subtree_root])
    return render(toc)


def assemble_document(client, renderer, start_topic=None, limit=None,
                      title="Service Manual"):
    """Crawl the toc, render every leaf, and return (html_string, leaf_count)."""
    root = client.get_root()
    doc_title = html.escape(root.get("title", title))

    body_parts = []
    leaf_count = 0
    for node, depth in client.iter_toc(start_topic):
        nid = str(node.get("id"))
        node_title = html.escape(node.get("title", ""))
        children = node.get("children") or []
        is_leaf = node.get("selectable") and not children

        if not is_leaf:
            chapter_cls = "chapter" if depth == 0 else ""
            level = min(depth + 1, 6)
            body_parts.append(
                f'<div class="section {chapter_cls}" id="sec-{nid}">'
                f'<h{level}>{node_title}</h{level}></div>'
            )
            continue

        topic = client.get_topic(nid)
        base_level = min(depth + 1, 6)
        chapter_cls = "chapter" if depth == 0 else ""
        rendered = renderer.render_topic(topic, base_level)
        # If the content has no title node, fall back to the toc title.
        if "topic-title" not in rendered:
            rendered = (f'<h{base_level} class="topic-title">{node_title}'
                        f'</h{base_level}>') + rendered
        body_parts.append(
            f'<section class="topic {chapter_cls}" id="topic-{nid}">{rendered}</section>'
        )
        leaf_count += 1
        client.log(1, f"  rendered [{leaf_count}] {node.get('title', '')}")
        if limit and leaf_count >= limit:
            break

    titlepage = (
        f'<div class="titlepage"><h1>{doc_title}</h1>'
        f'<div class="sub">Offline edition &middot; generated for personal use</div></div>'
    )
    toc_html = (f'<div class="toc"><h1>Table of Contents</h1>'
                f'{build_toc_html(client, start_topic)}</div>')

    document = (
        '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
        f"<title>{doc_title}</title><style>{PRINT_CSS}</style></head><body>"
        f"{titlepage}{toc_html}{''.join(body_parts)}"
        "</body></html>"
    )
    return document, leaf_count
