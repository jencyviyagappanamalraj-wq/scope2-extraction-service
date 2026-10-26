"""Task 2/3 web benchmark: the SAME slice of each web page goes to every tool.

    python app/azure_web_benchmark.py

A web page has no "pages", and the full Wikipedia pages are huge. So each page is cleaned (menus,
footers removed, as in web_converters.py) and cut at a paragraph/table boundary after about
SLICE_CHARS characters. That slice is saved as data/input/web/<name>_slice.html and given to
open-source requests+bs4 ("opensource"), Docling, MarkItDown and Azure, so the numbers
are comparable.

Every tool is timed the same way: RUNS runs, the FASTEST is reported (run 1 warms up Docling).

Azure is OPTIONAL. It runs only if AZURE_DI_ENDPOINT and AZURE_DI_KEY are set in .env, or if you
saved Azure's Markdown by hand as data/output/azure_manual/<name>_slice.md. Otherwise it is skipped.

Results: data/output/web_markdown_slice/web_benchmark_slice.csv
"""
import csv
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")        # before importing benchmark / web_converters

import web_converters as wc
import webscraper
from benchmark import md_metrics

HAS_AZURE = bool(os.getenv("AZURE_DI_ENDPOINT") and os.getenv("AZURE_DI_KEY"))
if HAS_AZURE:
    import azure_web as aw
    SLICE_CHARS = aw.SLICE_CHARS
else:
    SLICE_CHARS = 6000            # about 2 "pages" of 3,000 characters (same as azure_web.SLICE_CHARS)
    try:                          # reuse the exact slicing function when azure_web.py is importable
        import azure_web as aw
        SLICE_CHARS = aw.SLICE_CHARS
    except Exception:
        aw = None

OUT = ROOT / "data" / "output" / "web_markdown_slice"
MANUAL = ROOT / "data" / "output" / "azure_manual"


def slice_html(content, limit):
    """Use azure_web.slice_html if available, else fall back to a simple cut."""
    if aw is not None:
        return aw.slice_html(content, limit)
    text = content[:limit]
    return text, len(text)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    wc.OUT = OUT                                       # errors.log goes here
    (OUT / "errors.log").unlink(missing_ok=True)
    rows = []
    for name, url in wc.PAGES.items():
        start = len(rows)
        html = wc.fetch_html(name, url).read_text(encoding="utf-8")
        content = webscraper.parse_html(html, url)[0]
        slice_text, n_chars = slice_html(content, SLICE_CHARS)
        slice_path = wc.HTML_DIR / f"{name}_slice.html"
        slice_path.write_text(slice_text, encoding="utf-8")
        print(f"{name}: slice of about {n_chars} characters saved to {slice_path.name}")

        # 1) open source (requests + BeautifulSoup), Docling, MarkItDown: all on the SAME slice.
        #    wc.TOOLS functions take (path, url); each is timed, fastest of 2 runs.
        for tool, fn in dict(wc.TOOLS).items():
            md, secs, err = wc.fastest(lambda: fn(slice_path, url), f"{name} / {tool}")
            rows.append(_row(name, tool, md, secs, err, n_chars))

        # 3) Azure: optional
        if HAS_AZURE:
            label = "azure"
            def run():
                nonlocal label
                result, label = aw.analyze(slice_path, name)
                return result.content
            md, secs, err = wc.fastest(run, f"{name} / azure", runs=1)
            rows.append(_row(name, label, md, secs, err, n_chars))
        else:
            manual = MANUAL / f"{name}_slice.md"
            if manual.exists():
                rows.append(_row(name, "azure (manual)", manual.read_text(encoding="utf-8"), None, "", n_chars))

        for r in rows[start:]:
            print(f"  {r['page']:20} {r['tool']:20} {r.get('seconds', '')}s {r.get('error', '')}")

    keys = ["page", "tool", "seconds", "chars", "headings", "tables", "images", "slice_chars", "error"]
    csv_path = OUT / "web_benchmark_slice.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"\nSaved: {csv_path}")
    if (OUT / "errors.log").exists():
        print(f"Some runs failed. Details: {OUT / 'errors.log'}")


def _row(name, tool, md, secs, err, n_chars):
    d = OUT / tool.split(" ")[0]
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.md").write_text(md or "", encoding="utf-8")
    row = {"page": name, "tool": tool, "seconds": round(secs, 2) if secs else "", "error": err,
           "slice_chars": n_chars}
    if md:
        row.update(md_metrics(md))
    return row


if __name__ == "__main__":
    main()
