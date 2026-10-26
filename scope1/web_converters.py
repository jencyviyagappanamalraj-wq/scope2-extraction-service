"""
Web-page benchmark for Task 3: open-source (requests + BeautifulSoup -> Markdown), Docling and MarkItDown
on the SAME pages. Every tool produces a Markdown file, and every Markdown file is measured the same way.
(Azure AI Document Intelligence: azure_web.py and azure_web_benchmark.py)

Menus, headers, footers and sidebars are STRIPPED before conversion (same cleaning as the bs4
scraper: webscraper.parse_html), so all tools see the same main article content and the
metrics are directly comparable.

Flow: download each page's HTML once -> data/input/web/<name>.html
      -> strip menus -> data/input/web/<name>_main.html
      -> open-source / Docling / MarkItDown on the cleaned file -> data/output/web_markdown/<tool>/<name>.md
      -> data/output/web_markdown/web_benchmark.csv  (+ errors.log if anything fails)

Run from anywhere:   python app/web_converters.py
Needs the latest webscraper.py (it provides parse_html).
"""
import csv, sys, time, traceback
from pathlib import Path

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parent))
import webscraper
from docling_markitdown import get_docling_converter
from benchmark import md_metrics

ROOT = Path(__file__).resolve().parent.parent
HTML_DIR = ROOT / "data" / "input" / "web"
OUT = ROOT / "data" / "output" / "web_markdown"

# Same pages as webscraper.py
PAGES = {
    "python_programming": "https://en.wikipedia.org/wiki/Python_(programming_language)",
    "india": "https://en.wikipedia.org/wiki/India",
}


def fetch_html(name, url):
    HTML_DIR.mkdir(parents=True, exist_ok=True)
    path = HTML_DIR / f"{name}.html"
    if not path.exists():                       # download once, reuse afterwards
        if not webscraper.allowed_by_robots(url):
            raise PermissionError(f"robots.txt does not allow {url}")
        r = requests.get(url, headers=webscraper.HEADERS, timeout=30)
        r.raise_for_status()
        path.write_text(r.text, encoding="utf-8")
    return path


def opensource_web(path, url):
    """Open-source column: requests + BeautifulSoup output reassembled into Markdown (webscraper.html_to_markdown)."""
    return webscraper.html_to_markdown(Path(path).read_text(encoding="utf-8"), url)


def docling_web(path, url=None):
    return get_docling_converter().convert(str(path)).document.export_to_markdown()


def markitdown_web(path, url=None):
    from markitdown import MarkItDown
    return MarkItDown().convert(str(path)).text_content


TOOLS = {"opensource": opensource_web, "docling": docling_web, "markitdown": markitdown_web}


def short_error(e):
    return f"{type(e).__name__}: {str(e)[:150]}".replace("\n", " ")


def fastest(fn, label, runs=2):
    """Return (result, fastest seconds, error). Run 1 warms up Docling."""
    best, result = None, None
    for _ in range(runs):
        t0 = time.perf_counter()
        try:
            result = fn()
        except Exception as e:
            OUT.mkdir(parents=True, exist_ok=True)
            with open(OUT / "errors.log", "a", encoding="utf-8") as f:
                f.write(f"=== {label} ===\n{traceback.format_exc()}\n")
            return None, None, short_error(e)
        t = time.perf_counter() - t0
        best = t if best is None else min(best, t)
    return result, best, ""


def reference_row(name, html):
    """Ground truth for tables: data tables (wikitable + infobox) counted straight from the HTML."""
    soup = BeautifulSoup(html, "html.parser")
    n = len([t for t in soup.select("table.wikitable, table.infobox") if t.find_parent("table") is None])
    return {"page": name, "tool": "REFERENCE (wikitable+infobox)", "tables": n}


def main():
    (OUT / "errors.log").unlink(missing_ok=True) if OUT.exists() else None
    rows = []
    for name, url in PAGES.items():
        full = fetch_html(name, url)
        html = full.read_text(encoding="utf-8")

        content = webscraper.parse_html(html, url)[0]          # menus/headers/footers stripped
        main_only = HTML_DIR / f"{name}_main.html"
        main_only.write_text(f"<html><body>{content}</body></html>", encoding="utf-8")

        rows.append(reference_row(name, html))

        for tool, fn in TOOLS.items():
            md, secs, err = fastest(lambda: fn(main_only, url), f"{name} / {tool}")
            d = OUT / tool
            d.mkdir(parents=True, exist_ok=True)
            (d / f"{name}.md").write_text(md or "", encoding="utf-8")
            row = {"page": name, "tool": tool, "error": err, "seconds": round(secs, 2) if secs else ""}
            if md:
                row.update(md_metrics(md))
            rows.append(row)
            print(f"{name:20} {tool:11} {row['seconds']}s {err}")

    OUT.mkdir(parents=True, exist_ok=True)
    keys = ["page", "tool", "seconds", "chars", "headings", "tables", "images", "error"]
    with open(OUT / "web_benchmark.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"\nSaved: {OUT / 'web_benchmark.csv'}")
    if (OUT / "errors.log").exists():
        print(f"Some runs failed. Details: {OUT / 'errors.log'}")


if __name__ == "__main__":
    main()
