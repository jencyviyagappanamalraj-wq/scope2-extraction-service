"""Azure AI Document Intelligence (prebuilt-layout -> Markdown), no manual downloads.

The API returns the Markdown straight into Python; the portal download is only for the Studio UI.

FREE TIER (F0) ONLY ANALYSES THE FIRST 2 PAGES OF EACH PDF. Workaround used here: split the PDF
into 2-page pieces, send each piece as its own request, and join the Markdown. On a paid (S0)
resource set  AZURE_CHUNK_PAGES=0  in .env and the whole PDF goes in one request.

.env needs: AZURE_DI_ENDPOINT, AZURE_DI_KEY   (optional: AZURE_CHUNK_PAGES=2)

    python app/azure_di.py                      # every PDF in data/input -> data/output/azure/<name>.md
    python app/azure_di.py data/input/a.pdf
"""
import io
import json
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

CHUNK_PAGES = int(os.getenv("AZURE_CHUNK_PAGES", "2"))
OUT = ROOT / "data" / "output" / "azure"


def available():
    return bool(os.getenv("AZURE_DI_ENDPOINT") and os.getenv("AZURE_DI_KEY"))


def _client():
    from azure.core.credentials import AzureKeyCredential
    from azure.ai.documentintelligence import DocumentIntelligenceClient
    return DocumentIntelligenceClient(os.environ["AZURE_DI_ENDPOINT"],
                                      AzureKeyCredential(os.environ["AZURE_DI_KEY"]))


def analyze_bytes(data, content_type="application/octet-stream", client=None):
    """One Layout request -> result object (result.content is the Markdown)."""
    client = client or _client()
    poller = client.begin_analyze_document(
        "prebuilt-layout", body=io.BytesIO(data), content_type=content_type,
        output_content_format="markdown")
    return poller.result()


def split_pdf(pdf_path, n=CHUNK_PAGES):
    from pypdf import PdfReader, PdfWriter
    reader = PdfReader(str(pdf_path))
    total = len(reader.pages)
    if n <= 0 or total <= n:
        return [Path(pdf_path).read_bytes()], total
    chunks = []
    for start in range(0, total, n):
        writer = PdfWriter()
        for i in range(start, min(start + n, total)):
            writer.add_page(reader.pages[i])
        buf = io.BytesIO()
        writer.write(buf)
        chunks.append(buf.getvalue())
    return chunks, total


def pdf_to_markdown(pdf_path, chunk_pages=CHUNK_PAGES):
    """Whole PDF -> (markdown, info). info = pages, tables, requests, seconds (sum of all requests)."""
    client = _client()
    chunks, total = split_pdf(pdf_path, chunk_pages)
    parts, tables, t0 = [], 0, time.perf_counter()
    for i, data in enumerate(chunks, start=1):
        print(f"  Azure request {i}/{len(chunks)} ...")
        res = analyze_bytes(data, client=client)
        parts.append(res.content)
        tables += len(res.tables or [])
    seconds = round(time.perf_counter() - t0, 2)
    return "\n\n<!-- PageBreak -->\n\n".join(parts), {
        "pages": total, "tables": tables, "requests": len(chunks), "seconds": seconds}


def main(args):
    if not available():
        sys.exit("Set AZURE_DI_ENDPOINT and AZURE_DI_KEY in .env")
    pdfs = [Path(a) for a in args] or sorted((ROOT / "data" / "input").glob("*.pdf"))
    OUT.mkdir(parents=True, exist_ok=True)
    summary = []
    for pdf in pdfs:
        print(f"Processing {pdf.name}")
        try:
            md, info = pdf_to_markdown(pdf)
            (OUT / f"{pdf.stem}.md").write_text(md, encoding="utf-8")
            info.update(file=pdf.name, status="ok")
        except Exception as e:
            info = {"file": pdf.name, "status": f"failed: {type(e).__name__}: {str(e)[:200]}"}
        print("  ->", info)
        summary.append(info)
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1:])
