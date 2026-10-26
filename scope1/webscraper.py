"""Task 2 (open-source): requests + BeautifulSoup. Saves text, tables (JSON) and image URLs."""
import json
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup, NavigableString

from opensource_markdown import table_to_md

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = PROJECT_ROOT / "data" / "output" / "web"

# Wikimedia and many sites ask for a descriptive User-Agent with a contact
HEADERS = {"User-Agent": "UnstructuredIngestionStudentProject/1.0 (contact: jencyviyagappanamalraj@gmail.com)"}


def allowed_by_robots(url):
    """Respect robots.txt. We download it ourselves with our own User-Agent, because Python's
    default one gets a 403 from sites like Wikipedia, and Python then treats 403 as 'everything forbidden'."""
    parts = urlparse(url)
    robots_url = f"{parts.scheme}://{parts.netloc}/robots.txt"
    try:
        r = requests.get(robots_url, headers=HEADERS, timeout=10)
    except Exception:
        return True                      # robots.txt could not be reached
    if r.status_code != 200:
        return True                      # no robots.txt published, so no restrictions
    rp = RobotFileParser()
    rp.parse(r.text.splitlines())
    return rp.can_fetch(HEADERS["User-Agent"], url)


def parse_html(html, base_url):
    """Parse HTML into (content element, text, tables, image URLs, heading count).
    Pure parsing (no network), so it can be timed fairly against the other tools."""
    soup = BeautifulSoup(html, "html.parser")

    # Remove non-content elements (menus, footers, scripts)
    for element in soup(["script", "style", "noscript", "nav", "header", "footer", "aside"]):
        element.decompose()

    # Prefer the main content area (Wikipedia: #mw-content-text) to avoid navigation noise
    content = soup.select_one("#mw-content-text") or soup.select_one("main") \
        or soup.select_one("article") or soup

    text = content.get_text(separator="\n", strip=True)

    tables = []
    for table in content.find_all("table"):
        if table.find_parent("table") is not None:           # nested table: already part of its parent
            continue
        if table.find_parent(class_=["navbox", "sidebar", "metadata"]):   # navigation/layout, not data
            continue
        rows = []
        for row in table.find_all("tr"):
            if row.find_parent("table") is not table:       # row belongs to a nested table
                continue
            row_data = [c.get_text(" ", strip=True) for c in row.find_all(["th", "td"], recursive=False)]
            if row_data:
                rows.append(row_data)
        if rows:
            tables.append(rows)

    images = [urljoin(base_url, img["src"]) for img in content.find_all("img") if img.get("src")]
    headings = len(content.find_all(re.compile(r"^h[1-6]$")))
    return content, text, tables, images, headings


def scrape_page(url, page_name, output_dir=None):
    """Scrape text, tables and image URLs from a page. Returns the list of files written."""
    output_dir = Path(output_dir) if output_dir else DEFAULT_OUT
    output_dir.mkdir(parents=True, exist_ok=True)

    if not allowed_by_robots(url):
        raise PermissionError(f"robots.txt does not allow fetching {url}")

    print(f"\nScraping: {url}")
    response = requests.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()
    _, text, tables, images, _ = parse_html(response.text, url)

    text_file = output_dir / f"{page_name}_text.txt"
    text_file.write_text(text, encoding="utf-8")
    tables_file = output_dir / f"{page_name}_tables.json"
    tables_file.write_text(json.dumps(tables, indent=2, ensure_ascii=False), encoding="utf-8")
    images_file = output_dir / f"{page_name}_images.json"
    images_file.write_text(json.dumps(images, indent=2), encoding="utf-8")

    print(f"Saved text, {len(tables)} tables, {len(images)} image URLs to {output_dir}")
    return [text_file, tables_file, images_file]


# ---------------------------------------------------------------- HTML -> Markdown (open-source, in page order)
def _txt(el):
    return re.sub(r"\s+", " ", el.get_text()).strip()


def _table_rows(table):
    rows = []
    for tr in table.find_all("tr"):
        if tr.find_parent("table") is not table:             # row of a nested table
            continue
        cells = [_txt(c) for c in tr.find_all(["th", "td"], recursive=False)]
        if cells:
            rows.append(cells)
    return rows


def html_to_markdown(html, base_url):
    """Walk the main content in document order: headings, paragraphs, lists, tables, code, images.
    Pure bs4 (no Docling/MarkItDown), so it is the open-source column for Task 4-style output."""
    content = parse_html(html, base_url)[0]
    for el in content.select("sup.reference, .mw-editsection, .navbox, .sidebar, .metadata, .noprint, .reflist"):
        el.decompose()
    out = []

    def image(img):
        src = img.get("src") or ""
        small = any(str(img.get(k, "99")).isdigit() and int(img.get(k, 99)) < 40 for k in ("width", "height"))
        if src and not small:
            out.append(f"![{img.get('alt', '').strip()}]({urljoin(base_url, src)})")

    def walk(node):
        for ch in node.children:
            if isinstance(ch, NavigableString) or not ch.name:
                continue
            n = ch.name
            if re.fullmatch(r"h[1-6]", n):
                if _txt(ch):
                    out.append("#" * int(n[1]) + " " + _txt(ch))
            elif n == "p":
                if _txt(ch):
                    out.append(_txt(ch))
                for img in ch.find_all("img"):
                    image(img)
            elif n in ("ul", "ol"):
                items = [_txt(li) for li in ch.find_all("li", recursive=False) if _txt(li)]
                out.append("\n".join((f"{i}. " if n == "ol" else "- ") + t for i, t in enumerate(items, 1)))
            elif n == "table":
                md = table_to_md(_table_rows(ch))
                if md:
                    out.append(md)
            elif n == "pre":
                out.append("```\n" + ch.get_text().strip("\n") + "\n```")
            elif n == "img":
                image(ch)
            else:
                walk(ch)

    walk(content)
    return "\n\n".join(o for o in out if o.strip()) + "\n"


def scrape_chosen_pages():
    scrape_page("https://en.wikipedia.org/wiki/Python_(programming_language)", "python_programming")
    scrape_page("https://en.wikipedia.org/wiki/India", "india")


if __name__ == "__main__":
    scrape_chosen_pages()
