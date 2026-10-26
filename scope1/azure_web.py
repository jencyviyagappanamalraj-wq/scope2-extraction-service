"""Task 2 (enterprise service): Azure AI Document Intelligence on web pages -> Markdown.

    python app/azure_web.py

Needs AZURE_DI_ENDPOINT and AZURE_DI_KEY in .env  (pip install azure-ai-documentintelligence).

Why a "slice"? A web page has no pages, and a full Wikipedia article is huge, so each page is cleaned
(menus, headers and footers removed, the same cleaning as webscraper.parse_html) and cut after about
SLICE_CHARS characters, at a paragraph / table boundary. The same slice is used for every tool in
azure_web_benchmark.py, so the results are comparable.

Azure gets the HTML slice first. If it refuses HTML, it gets a PDF of the page that YOU printed from the
browser (Ctrl+P > Save as PDF) as data/input/web_pdf/<name>.pdf, cut to its first 2 pages.

Output: data/output/azure/web/<name>.md, <name>.json and summary.json
"""
import io
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

import requests
import webscraper

HTML_DIR = ROOT / "data" / "input" / "web"
PRINTED_DIR = ROOT / "data" / "input" / "web_pdf"
OUTPUT_DIR = ROOT / "data" / "output" / "azure" / "web"
SLICE_CHARS = 6000        # about 2 "pages" of 3,000 characters

# Same pages as webscraper.py / web_converters.py
PAGES = {
    "python_programming": "https://en.wikipedia.org/wiki/Python_(programming_language)",
    "india": "https://en.wikipedia.org/wiki/India",
}


def get_client():
    from azure.core.credentials import AzureKeyCredential
    from azure.ai.documentintelligence import DocumentIntelligenceClient
    if not (os.getenv("AZURE_DI_ENDPOINT") and os.getenv("AZURE_DI_KEY")):
        raise RuntimeError("Set AZURE_DI_ENDPOINT and AZURE_DI_KEY in .env")
    return DocumentIntelligenceClient(os.environ["AZURE_DI_ENDPOINT"],
                                      AzureKeyCredential(os.environ["AZURE_DI_KEY"]))


def fetch_html(name, url):
    """Download the page once (respecting robots.txt) and reuse the saved copy afterwards."""
    HTML_DIR.mkdir(parents=True, exist_ok=True)
    path = HTML_DIR / f"{name}.html"
    if not path.exists():
        if not webscraper.allowed_by_robots(url):
            raise PermissionError(f"robots.txt does not allow {url}")
        r = requests.get(url, headers=webscraper.HEADERS, timeout=30)
        r.raise_for_status()
        path.write_text(r.text, encoding="utf-8")
    return path


def slice_html(content, limit=SLICE_CHARS):
    """Keep whole blocks (paragraphs, tables, lists) until about `limit` characters of text.
    Returns (html text, number of characters kept)."""
    container = content
    for cand in [content] + content.find_all(True, limit=60):
        if len(cand.find_all(True, recursive=False)) >= 10:
            container = cand
            break
    parts, total = [], 0
    for child in container.find_all(True, recursive=False):
        parts.append(str(child))
        total += len(child.get_text(" ", strip=True))
        if total >= limit:
            break
    return "<html><body>" + "\n".join(parts) + "</body></html>", total


def analyze_html(path):
    with open(path, "rb") as f:
        poller = get_client().begin_analyze_document(
            "prebuilt-layout", body=f, content_type="text/html", output_content_format="markdown")
    return poller.result()


def analyze_printed_pdf(name):
    from pypdf import PdfReader, PdfWriter
    src = PRINTED_DIR / f"{name}.pdf"
    if not src.exists():
        raise FileNotFoundError(f"{src} not found (print the page to PDF first: Ctrl+P > Save as PDF)")
    writer = PdfWriter()
    for page in PdfReader(str(src)).pages[:2]:
        writer.add_page(page)
    buf = io.BytesIO()
    writer.write(buf)
    poller = get_client().begin_analyze_document(
        "prebuilt-layout", body=io.BytesIO(buf.getvalue()),
        content_type="application/octet-stream", output_content_format="markdown")
    return poller.result()


def analyze(path, name):
    """HTML slice first; printed PDF if Azure refuses HTML. Returns (result, method label)."""
    try:
        return analyze_html(path), "azure (html slice)"
    except Exception as e:
        print(f"  Azure refused the HTML ({type(e).__name__}); trying the printed PDF instead")
        return analyze_printed_pdf(name), "azure (printed PDF, 2 pages)"


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    summary = []
    for name, url in PAGES.items():
        print(f"Processing {url}")
        try:
            html = fetch_html(name, url).read_text(encoding="utf-8")
            content = webscraper.parse_html(html, url)[0]            # menus / footers stripped
            slice_text, n_chars = slice_html(content)
            slice_path = HTML_DIR / f"{name}_slice.html"
            slice_path.write_text(slice_text, encoding="utf-8")

            result, method = analyze(slice_path, name)
            (OUTPUT_DIR / f"{name}.md").write_text(result.content, encoding="utf-8")
            (OUTPUT_DIR / f"{name}.json").write_text(
                json.dumps(result.as_dict(), indent=2), encoding="utf-8")
            info = {"page": name, "method": method, "slice_chars": n_chars,
                    "pages": len(result.pages or []), "tables": len(result.tables or []), "status": "ok"}
        except Exception as e:
            info = {"page": name, "status": f"failed: {type(e).__name__}: {e}"}
        print("  ->", info)
        summary.append(info)
    (OUTPUT_DIR / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print("Done. Results are in", OUTPUT_DIR)


if __name__ == "__main__":
    main()
