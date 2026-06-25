"""FFS command-line interface: discover, build, list, audit, install-browser."""

import argparse
import getpass
import sys
from pathlib import Path

import requests

from . import __version__
from .client import LoginError, TriumphClient
from .config import (
    API_BASE,
    DEFAULT_DOC_TYPE,
    DEFAULT_LANGUAGE,
    ManualConfig,
    credentials_from_env_and_dotenv,
    load_config_file,
    save_config_file,
)
from .document import assemble_document, manual_title
from .pdf import install_browser, render_pdf
from .render import HtmlRenderer

HTML_NAME = "manual.html"


# --- small interactive helpers ---------------------------------------------

def interactive() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def menu(prompt: str, labels: list[str]) -> int:
    print(prompt)
    for i, label in enumerate(labels, 1):
        print(f"  {i}. {label}")
    while True:
        raw = input(f"Enter 1-{len(labels)}: ").strip()
        if raw.isdigit() and 1 <= int(raw) <= len(labels):
            return int(raw) - 1
        print("Invalid selection.")


def confirm(prompt: str, default=True) -> bool:
    if not interactive():
        return default
    suffix = " [Y/n] " if default else " [y/N] "
    ans = input(prompt + suffix).strip().lower()
    if not ans:
        return default
    return ans.startswith("y")


def _systitle(doc: dict):
    return ((doc.get("metadata") or {}).get("docType") or {}).get("systemTitle")


# --- resolution pipeline ----------------------------------------------------

def resolve_credentials(args, cfg_file) -> tuple[str, str]:
    email, password = args.email, args.password
    if not (email and password):
        env_email, env_pw = credentials_from_env_and_dotenv()
        email = email or env_email
        password = password or env_pw
    email = email or cfg_file.get("email")
    if not email:
        if interactive():
            email = input("Triumph email: ").strip()
        else:
            sys.exit("ERROR: no email. Set TTI_EMAIL, --email, or a config file.")
    if not password:
        if interactive():
            password = getpass.getpass("Triumph password: ")
        else:
            sys.exit("ERROR: no password. Set TTI_PASSWORD or --password.")
    return email, password


def make_client(args, cfg_file) -> TriumphClient:
    email, password = resolve_credentials(args, cfg_file)
    try:
        return TriumphClient(
            email, password,
            cache_dir=Path(args.cache_dir),
            verbose=args.verbose,
            use_cache=not args.no_cache,
            api_base=args.api_base,
        )
    except LoginError as err:
        sys.exit(f"ERROR: {err}")


def resolve_vin(client: TriumphClient, args, cfg_file) -> str:
    if args.vin:
        return args.vin
    if cfg_file.get("vin"):
        return cfg_file["vin"]
    vins = client.subscribed_vins()
    if len(vins) == 1:
        client.log(0, f"Auto-detected VIN from your subscription: {vins[0]}")
        return vins[0]
    if len(vins) > 1:
        if not interactive():
            sys.exit("ERROR: multiple VINs on this account; pass --vin.")
        labels = []
        for v in vins:
            try:
                p = client.product_search(v)
                labels.append(f"{v}  —  {p.get('modelYear', '')} {p.get('modelName', '')}".strip())
            except requests.HTTPError:
                labels.append(v)
        return vins[menu("Select your motorcycle:", labels)]
    if interactive():
        return input("Enter your VIN (frame/registration/key tag): ").strip()
    sys.exit("ERROR: no VIN found on your account; pass --vin.")


def select_document(client: TriumphClient, product_context, language, args):
    """Return (root_id, title). Defaults to the single Service Manual."""
    if args.root_id:
        return args.root_id, None
    docs = client.list_documents(product_context)
    in_lang = [d for d in docs if d.get("language") == language]
    if not in_lang:
        sys.exit(f"ERROR: no documents found for language {language!r}.")

    if args.all_types:
        candidates = in_lang
    else:
        candidates = [d for d in in_lang if _systitle(d) == args.doc_type]
        if not candidates:
            print(f"No {args.doc_type!r} document for language {language!r}; "
                  "showing all available documents.")
            candidates = in_lang

    if len(candidates) == 1:
        d = candidates[0]
        client.log(0, f"Selected document: {d.get('title')} [{d['_id']}]")
        return d["_id"], d.get("title")
    if not interactive():
        sys.exit("ERROR: multiple documents match; pass --root-id "
                 "(run `ffs discover` to list them).")
    labels = [f"{d.get('title')}  [{_systitle(d)}]" for d in candidates]
    d = candidates[menu("Select a document:", labels)]
    return d["_id"], d.get("title")


def build_manual_config(client: TriumphClient, args, cfg_file) -> ManualConfig:
    language = (args.language or cfg_file.get("language")
                or client.default_language() or DEFAULT_LANGUAGE)

    # Full power-user override: explicit root + product context from flags.
    if args.root_id and args.model_code and args.serial:
        pc = {
            "modelCode": args.model_code,
            "modelYear": args.model_year or "",
            "serial": args.serial,
            "engineNo": args.engine_no or "",
            "market": args.market or "",
            "state": "published",
            "onlyValid": "true",
        }
        return ManualConfig(root_id=args.root_id, language=language,
                            api_base=args.api_base, product_context=pc)

    vin = resolve_vin(client, args, cfg_file)
    product = client.product_search(vin)
    cfg = ManualConfig.from_product(product, language=language,
                                    api_base=args.api_base,
                                    root_id=args.root_id or cfg_file.get("root_id"))
    # individual flag overrides of product-context fields
    for flag, key in (("model_code", "modelCode"), ("model_year", "modelYear"),
                      ("serial", "serial"), ("engine_no", "engineNo"),
                      ("market", "market")):
        val = getattr(args, flag)
        if val:
            cfg.product_context[key] = val
    if not cfg.root_id:
        cfg.root_id, _ = select_document(client, cfg.product_context, language, args)
    cfg.vin = vin
    return cfg


def maybe_save(args, cfg_file, email, cfg: ManualConfig):
    if args.no_save or not interactive():
        return
    proposed = {"email": email, "vin": cfg.vin, "root_id": cfg.root_id,
                "language": cfg.language}
    if all(cfg_file.get(k) == v for k, v in proposed.items()):
        return  # nothing new
    if confirm("Save these settings for next time?"):
        path = save_config_file(proposed)
        print(f"Saved settings to {path} (password not stored).")


# --- subcommands ------------------------------------------------------------

def cmd_build(args):
    cfg_file = load_config_file()
    client = make_client(args, cfg_file)
    email, _ = resolve_credentials(args, cfg_file)  # already validated; for save
    cfg = build_manual_config(client, args, cfg_file)
    client.config = cfg
    maybe_save(args, cfg_file, email, cfg)

    out_dir = Path(args.output_path)
    out_dir.mkdir(parents=True, exist_ok=True)
    renderer = HtmlRenderer(client, inline_images=args.inline_images,
                            image_out_dir=out_dir / "images")
    document, leaf_count = assemble_document(
        client, renderer, start_topic=args.topic, limit=args.limit)

    html_path = out_dir / HTML_NAME
    html_path.write_text(document, encoding="utf-8")
    print(f"Wrote {html_path} ({leaf_count} topics, {len(document):,} bytes)")

    if renderer.unhandled:
        print("\nWARNING: unhandled node types fell through to the generic fallback:")
        for nt, cnt in sorted(renderer.unhandled.items(), key=lambda kv: -kv[1]):
            print(f"  {cnt:5d}  {nt}")
    else:
        print("Coverage: all node types handled.")

    if args.html_only:
        return
    doc_title = manual_title(client)
    pdf_path = out_dir / f"{cfg.slug()}.pdf"
    render_pdf(html_path, pdf_path, doc_title)
    print(f"Wrote {pdf_path}")


def cmd_list(args):
    cfg_file = load_config_file()
    client = make_client(args, cfg_file)
    client.config = build_manual_config(client, args, cfg_file)
    for node, depth in client.iter_toc(args.topic):
        children = node.get("children") or []
        is_leaf = node.get("selectable") and not children
        marker = "-" if is_leaf else "#"
        print(f"{'  ' * depth}{marker} [{node.get('id')}] {node.get('title') or ''}")


def cmd_audit(args):
    cfg_file = load_config_file()
    client = make_client(args, cfg_file)
    client.config = build_manual_config(client, args, cfg_file)
    leaves = client.leaf_topics(args.topic, args.limit)
    print(f"Selectable leaf topics in toc: {len(leaves)}")
    errors, empty, fetched = [], [], 0
    for nid, title, _ in leaves:
        try:
            topic = client.get_topic(nid)
        except requests.HTTPError as err:
            errors.append((nid, title, str(err)))
            continue
        fetched += 1
        if not (topic.get("content") or []):
            empty.append((nid, title))
        if str(topic.get("id")) != nid:
            errors.append((nid, title, f"returned id {topic.get('id')!r} != requested"))
    print(f"Fetched OK: {fetched} / {len(leaves)}")
    print(f"Empty content: {len(empty)}")
    print(f"Errors/mismatches: {len(errors)}")
    for nid, title, msg in errors[:20]:
        print(f"  ERROR {nid} {title!r}: {msg}")
    for nid, title in empty[:20]:
        print(f"  EMPTY {nid} {title!r}")


def cmd_discover(args):
    cfg_file = load_config_file()
    client = make_client(args, cfg_file)
    language = (args.language or cfg_file.get("language")
                or client.default_language() or DEFAULT_LANGUAGE)
    vins = [args.vin] if args.vin else client.subscribed_vins()
    if not vins:
        print("No VINs found on this account. Pass --vin to inspect one.")
        return
    chosen_root = None
    for vin in vins:
        product = client.product_search(vin)
        cfg = ManualConfig.from_product(product, language=language, api_base=args.api_base)
        print(f"\nVIN {vin}: {product.get('modelYear', '')} {product.get('modelName', '')}")
        print(f"  product context: {cfg.product_context}")
        docs = client.list_documents(cfg.product_context)
        in_lang = [d for d in docs if d.get("language") == language]
        print(f"  documents ({language}): {len(in_lang)}")
        for d in sorted(in_lang, key=lambda d: (_systitle(d) or "", d.get("title", ""))):
            mark = "*" if _systitle(d) == DEFAULT_DOC_TYPE else " "
            print(f"   {mark} [{d['_id']}] {_systitle(d)!r:24} {d.get('title')}")
            if _systitle(d) == DEFAULT_DOC_TYPE and chosen_root is None:
                chosen_root = d["_id"]
    if args.write_config:
        path = save_config_file({"email": client.auth().get("user", {}).get("email"),
                                 "vin": vins[0], "root_id": chosen_root,
                                 "language": language})
        print(f"\nWrote starter config to {path} (* = default Service Manual).")


def cmd_install_browser(args):
    return install_browser()


# --- argument parser --------------------------------------------------------

def _add_common(sp):
    sp.add_argument("--email", help="Triumph account email (else env TTI_EMAIL / prompt)")
    sp.add_argument("--password", help="Triumph password (else env TTI_PASSWORD / prompt)")
    sp.add_argument("--vin", help="Motorcycle VIN (else auto-detected from subscription)")
    sp.add_argument("--root-id", help="Document id to use (skips document selection)")
    sp.add_argument("--doc-type", default=DEFAULT_DOC_TYPE,
                    help=f"docType systemTitle to pick (default: {DEFAULT_DOC_TYPE!r})")
    sp.add_argument("--all-types", action="store_true",
                    help="Don't filter by document type when selecting")
    sp.add_argument("--language", help="Document language (default: account/en-gb)")
    sp.add_argument("--model-code", help="Override product context modelCode")
    sp.add_argument("--model-year", help="Override product context modelYear")
    sp.add_argument("--serial", help="Override product context serial")
    sp.add_argument("--engine-no", help="Override product context engineNo")
    sp.add_argument("--market", help="Override product context market")
    sp.add_argument("--api-base", default=API_BASE, help="API base URL")
    sp.add_argument("--cache-dir", default=".cache",
                    help="Directory for cached topics/images (default: .cache)")
    sp.add_argument("--no-cache", action="store_true",
                    help="Ignore cached topics/images (still writes cache)")
    sp.add_argument("--no-save", action="store_true",
                    help="Don't offer to save settings to a config file")
    sp.add_argument("--verbose", "-v", action="count", default=0)


def get_argparser():
    p = argparse.ArgumentParser(
        prog="ffs",
        description="FFS — Full-manual Fetcher & Stitcher: turn a Triumph "
                    "Technical Information service manual into an offline PDF.")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = p.add_subparsers(dest="command")

    b = sub.add_parser("build", help="Fetch a manual and render it to PDF")
    b.add_argument("output_path", help="Directory for manual.html + the PDF")
    b.add_argument("--topic", help="Only this topic id's subtree (dev/preview)")
    b.add_argument("--limit", type=int, help="Render at most N leaf topics")
    b.add_argument("--html-only", action="store_true", help="Skip PDF rendering")
    b.add_argument("--inline-images", action="store_true",
                   help="Embed images as base64 in one large portable HTML file "
                        "(default: write to OUTPUT/images/; the PDF is self-contained "
                        "either way)")
    _add_common(b)
    b.set_defaults(func=cmd_build)

    le = sub.add_parser("list", help="Print the table of contents with topic IDs")
    le.add_argument("--topic", help="Only this topic id's subtree")
    _add_common(le)
    le.set_defaults(func=cmd_list)

    a = sub.add_parser("audit", help="Verify every topic fetches with content")
    a.add_argument("--topic", help="Only this topic id's subtree")
    a.add_argument("--limit", type=int, help="Check at most N topics")
    _add_common(a)
    a.set_defaults(func=cmd_audit)

    d = sub.add_parser("discover",
                        help="List your VIN(s), product context and available documents")
    d.add_argument("--write-config", action="store_true",
                   help="Write a starter config file from the discovered values")
    _add_common(d)
    d.set_defaults(func=cmd_discover)

    ib = sub.add_parser("install-browser",
                         help="Download the Chromium build needed for PDF rendering")
    ib.set_defaults(func=cmd_install_browser)

    return p


def main(argv=None):
    parser = get_argparser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 2
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
