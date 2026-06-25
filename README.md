# FFS — Full-manual Fetcher & Stitcher

*For F***'s Sake, just let me print my own service manual.*

`ffs-triumph` turns a [Triumph Technical Information](https://triumphtechnicalinformation.com)
service manual — delivered as a JavaScript single-page app you can't download or
print — into a single, self-contained, **paginated PDF** for offline use.

It logs in with your account, finds your motorcycle from your subscription,
crawls the whole manual, converts the site's structured content into HTML,
inlines the diagrams, and renders a clean PDF with a title page, table of
contents, page numbers, and proper page breaks.

> **Disclaimer.** This tool is for owners with **legitimate, licensed access**
> archiving **their own** manual for **personal, offline** use. You need a valid
> Triumph Technical Information subscription; it only ever fetches content your
> account is already entitled to. It is **not affiliated with or endorsed by
> Triumph**, and you are responsible for complying with the site's terms of use.

## Motivation

_HAVE YOU EVER TRIED TO USE A **COMPUTER** WHILE WEARING **OILY GLOVES?**_ 

I've owned a lot of motorcycles. I've even owned Triumph motorcycles before. Every time I buy a new motorcycle, the first thing I do (right after making the _"vroom-vroom"_ sounds in my garage) is to **BUY A PDF OF THE SERVICE MANUAL.**

I was *shocked* that there was no PDF available from Triumph. I'm sure it was just an oversight on your part. I was perfectly willing to pay for it. I can't imagine Triumph would make a crippled product on purpose. Especially not to make a sad US$8.33 per month, at the cost of alienating your most enthusiastic customers. That would be crazy.

Anyway: Here you go. I've fixed the gaps in your offering. Any subscriber to the [Triumph Technical Information](https://triumphtechnicalinformation.com) site can now make a nice printed paper copy of whatever bit they need. You're welcome, Triumph! :beer:


## Install

```bash
pip install ffs-triumph
ffs install-browser          # one-time: downloads the Chromium build for PDF rendering
```

(`install-browser` runs `python -m playwright install chromium`. You can skip it
if you only use `--html-only`.)

## Quick start

```bash
# Provide credentials (or you'll be prompted):
export TTI_EMAIL="you@example.com"
export TTI_PASSWORD="..."

ffs build out/
```

That's it. With one motorcycle on your account and one service manual in your
language, **no other input is needed** — `ffs` auto-detects your VIN from your
subscription, picks the Service Manual, and writes the PDF to `out/`.

Not sure what's available? Inspect your account first:

```bash
ffs discover                 # lists your VIN(s), product context, and documents
```

## How it figures things out

From just your **email + password**:

1. **Your bike** — read from your subscription's VIN(s). One → used automatically;
   several → you pick from a menu showing year/model. (Override with `--vin`.)
2. **Product context** — model code/year, serial, engine number and market are
   looked up from the VIN automatically.
3. **The manual** — the single `Service Manual` document for your language is
   selected automatically. Use `--doc-type "Owner Handbook"` for a different type,
   `--all-types` to browse everything, or `--root-id <id>` to pick exactly.

After a successful run it offers to remember your email + bike + manual in
`~/.config/ffs-triumph/config.toml` (your password is **never** saved), so the
next run is just `ffs build out/`.

## Commands

| Command | Purpose |
|---------|---------|
| `ffs build OUTPUT` | Fetch the manual and render `OUTPUT/manual.html` + the PDF |
| `ffs discover` | List your VIN(s), product context, and available documents |
| `ffs list` | Print the manual's table of contents with topic IDs |
| `ffs audit` | Verify every topic fetches with non-empty content |
| `ffs install-browser` | Download the Chromium build needed for PDF rendering |

### Useful `build` options

| Flag | Purpose |
|------|---------|
| `--html-only` | Assemble HTML but skip PDF rendering (no Chromium needed) |
| `--topic ID` | Only that topic's subtree — fast for previewing |
| `--limit N` | Render at most N topics |
| `--inline-images` | Embed images as base64 in one large portable HTML file (default: write to `OUTPUT/images/`; the PDF is self-contained either way) |
| `--cache-dir DIR` | Where fetched topics/images are cached (default `.cache`) |
| `--no-cache` | Ignore the cache (still writes it) |
| `-v` | Verbose progress |

Credentials come from `--email`/`--password`, the `TTI_EMAIL`/`TTI_PASSWORD`
environment variables, a local `.env`, the saved config, or interactive prompts —
in that order. Every prompt has a corresponding flag, so the tool is fully
scriptable / CI-friendly.

## Use as a library

```python
from ffs_triumph import TriumphClient, ManualConfig

client = TriumphClient("you@example.com", "password")
vin = client.subscribed_vins()[0]
client.config = ManualConfig.from_product(client.product_search(vin), root_id="<doc id>")
root = client.get_root()          # the manual's table-of-contents tree
```

## Changelog

See [HISTORY.md](HISTORY.md).

## License

MIT — see [LICENSE](LICENSE).
