"""Glue between extraction, standardization and S3 storage. Used by the FastAPI app."""
import hashlib
import json
import tempfile
import time
from pathlib import Path
from urllib.parse import urlparse

import requests

import s3_storage as s3
import extractor
import md_pdf                    # NEW: open-source PDF -> one reading-order Markdown
import webscraper


def make_docid(name, data):
    return f"{s3.slug(Path(name).stem)}-{hashlib.sha1(data).hexdigest()[:8]}"


def _links(keys):
    return {k: {"s3_uri": s3.uri(k), "download_url": s3.presign(k)} for k in keys}


# ------------------------------------------------------------------ PDF
def pdf_extract(pdf_bytes, filename, source="uploaded"):
    """Open-source extraction (pypdf + pdfplumber): pieces + ONE reading-order Markdown -> S3."""
    docid = make_docid(filename, pdf_bytes)
    keys = [s3.put(s3.raw_key("pdf", source, docid, "pdf"), pdf_bytes,
                   doc_type="pdf", tool="raw", extra={"original-name": filename})]
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        pdf = work / f"{docid}.pdf"
        pdf.write_bytes(pdf_bytes)
        t0 = time.perf_counter()
        extractor.extract_text_with_pypdf(pdf, work / "out")
        extractor.extract_tables_layout_images(pdf, work / "out")
        md = md_pdf.extract_markdown_reading_order(pdf, work / "out")      # NEW
        secs = f"{time.perf_counter() - t0:.2f}"
        tool = "pypdf-pdfplumber"
        for f in sorted((work / "out").glob("*")):
            if f.is_file():
                keys.append(s3.put(s3.extracted_key(tool, source, docid, f.name), f,
                                   doc_type="pdf", tool=tool, extra={"seconds": secs}))
        image_keys = {}                                                    # NEW: remember each image's S3 key
        for img in sorted((work / "out" / "images" / pdf.stem).glob("*")):
            k = s3.put(s3.image_key(source, docid, img.name), img, doc_type="image", tool=tool)
            image_keys[img.name] = k
            keys.append(k)
        md = s3.rewrite_image_links(md, image_keys)                        # NEW: images/xyz.png -> s3 link
        md_key = s3.put(s3.markdown_key(tool, source, docid), md, doc_type="pdf", tool=tool,
                        extra={"seconds": secs, "images": str(len(image_keys))})
        keys.append(md_key)
    return {"doc_id": docid, "tool": tool, "seconds": float(secs), "images": len(image_keys),
            "markdown_key": md_key, "files": _links(keys),
            "markdown": s3.presign_markdown(md)}


def pdf_standardize(pdf_bytes, filename, tool, source="uploaded"):
    """Docling or MarkItDown -> Markdown (+ images) -> S3, with image links rewritten to S3."""
    docid = make_docid(filename, pdf_bytes)
    keys = [s3.put(s3.raw_key("pdf", source, docid, "pdf"), pdf_bytes,
                   doc_type="pdf", tool="raw", extra={"original-name": filename})]
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        pdf = work / f"{docid}.pdf"
        pdf.write_bytes(pdf_bytes)
        out_md = work / "md" / f"{docid}.md"
        t0 = time.perf_counter()
        if tool == "docling":
            import docling_markitdown as dm          # lazy: heavy import
            dm.convert_pdf_with_docling(pdf, out_md)
        elif tool == "markitdown":
            import docling_markitdown as dm
            dm.convert_pdf_with_markitdown(pdf, out_md)
        else:
            raise ValueError("tool must be 'docling' or 'markitdown'")
        secs = f"{time.perf_counter() - t0:.2f}"
        image_keys = {}
        img_dir = out_md.parent / "images"
        if img_dir.exists():
            for img in sorted(img_dir.glob("*")):
                k = s3.put(s3.image_key(source, docid, img.name), img, doc_type="image", tool=tool)
                image_keys[img.name] = k
                keys.append(k)
        md = s3.rewrite_image_links(out_md.read_text(encoding="utf-8"), image_keys)
        md_key = s3.put(s3.markdown_key(tool, source, docid), md, doc_type="pdf", tool=tool,
                        extra={"seconds": secs, "images": str(len(image_keys))})
        keys.append(md_key)
    return {"doc_id": docid, "tool": tool, "seconds": float(secs), "images": len(image_keys),
            "markdown_key": md_key, "files": _links(keys),
            "markdown": s3.presign_markdown(md)}


# ------------------------------------------------------------------ Web
def _fetch(url):
    if not webscraper.allowed_by_robots(url):
        raise PermissionError("robots.txt does not allow fetching this URL")
    r = requests.get(url, headers=webscraper.HEADERS, timeout=30)
    r.raise_for_status()
    parts = urlparse(url)
    source = s3.slug(parts.netloc)
    docid = make_docid(parts.path.strip("/").replace("/", "-") or "index", r.content)
    return r.text, source, docid


def url_extract(url):
    """Open-source scrape (requests + BeautifulSoup): text, tables, image URLs + Markdown -> S3."""
    html, source, docid = _fetch(url)
    keys = [s3.put(s3.raw_key("html", source, docid, "html"), html,
                   doc_type="html", tool="raw", source_url=url)]
    tool = "requests-bs4"
    with tempfile.TemporaryDirectory() as tmp:
        t0 = time.perf_counter()
        files = webscraper.scrape_page(url, docid, Path(tmp))
        markdown = webscraper.html_to_markdown(html, url)                  # NEW
        secs = f"{time.perf_counter() - t0:.2f}"
        for f in files:
            keys.append(s3.put(s3.extracted_key(tool, source, docid, f.name), f,
                               doc_type="web", tool=tool, source_url=url, extra={"seconds": secs}))
    md_key = s3.put(s3.markdown_key(tool, source, docid), markdown, doc_type="web", tool=tool,
                    source_url=url, extra={"seconds": secs})               # NEW
    keys.append(md_key)
    return {"doc_id": docid, "tool": tool, "seconds": float(secs), "markdown_key": md_key,
            "files": _links(keys), "markdown": markdown}


def url_standardize(url, tool):
    html, source, docid = _fetch(url)
    keys = [s3.put(s3.raw_key("html", source, docid, "html"), html,
                   doc_type="html", tool="raw", source_url=url)]
    with tempfile.TemporaryDirectory() as tmp:
        page = Path(tmp) / f"{docid}.html"
        content = webscraper.parse_html(html, url)[0]                      # NEW: strip menus, headers, footers
        page.write_text(f"<html><body>{content}</body></html>", encoding="utf-8")
        t0 = time.perf_counter()
        if tool == "docling":
            import docling_markitdown as dm
            md = dm.get_docling_converter().convert(str(page)).document.export_to_markdown()
        elif tool == "markitdown":
            from markitdown import MarkItDown
            md = MarkItDown().convert(str(page)).text_content
        else:
            raise ValueError("tool must be 'docling' or 'markitdown'")
        secs = f"{time.perf_counter() - t0:.2f}"
    md_key = s3.put(s3.markdown_key(tool, source, docid), md, doc_type="web", tool=tool,
                    source_url=url, extra={"seconds": secs})
    keys.append(md_key)
    return {"doc_id": docid, "tool": tool, "seconds": float(secs), "markdown_key": md_key,
            "files": _links(keys), "markdown": md}
