"""Task 3: fair comparison on the SAME first 2 pages of every document.
(Azure's free tier only reads the first 2 pages, so every tool is given the same 2 pages.)

    python app/azure_benchmark.py

Inputs : every PDF in data/input/            your test PDFs
         every PDF in data/input/web_pdf/    web pages printed to PDF (Azure cannot read HTML)
Each PDF is cut to its first 2 pages in data/input_2pages/, then run through open-source,
Docling, MarkItDown and Azure (Azure only if AZURE_DI_ENDPOINT and AZURE_DI_KEY are in .env).

Results : data/output/benchmark_2pages/benchmark_2pages.csv   (+ errors.log if something failed)
Manual Azure results: if you downloaded the Markdown from Document Intelligence Studio, save it as
data/output/azure_manual/<name>_p1-2.md and it is measured too (time is left blank).
"""
import csv
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")        # BEFORE importing benchmark: it checks the Azure variables when imported

from pypdf import PdfReader, PdfWriter
import benchmark as b
import azure_di

# benchmark.py no longer contains Azure, so this script adds it itself
TOOLS = dict(b.TOOLS)                 # opensource, docling, markitdown
HAS_AZURE = azure_di.available()


def run_azure(pdf, d):
    """Send the (already trimmed, 2-page) PDF to Azure and save its Markdown."""
    md, info = azure_di.pdf_to_markdown(pdf)
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{pdf.stem}.md").write_text(md, encoding="utf-8")


if HAS_AZURE:
    TOOLS["azure"] = run_azure

PAGES = 2
SOURCES = [("pdf", ROOT / "data" / "input"), ("web-printed", ROOT / "data" / "input" / "web_pdf")]
TRIMMED = ROOT / "data" / "input_2pages"
OUT = ROOT / "data" / "output" / "benchmark_2pages"
MANUAL = ROOT / "data" / "output" / "azure_manual"
KEYS = ["kind", "doc", "tool", "seconds", "chars", "headings", "tables", "formulas", "images", "error"]


def trim(pdf):
    """Copy of the PDF that holds only its first PAGES pages."""
    TRIMMED.mkdir(parents=True, exist_ok=True)
    out = TRIMMED / f"{pdf.stem}_p1-{PAGES}.pdf"
    writer = PdfWriter()
    for page in PdfReader(str(pdf)).pages[:PAGES]:
        writer.add_page(page)
    with open(out, "wb") as f:
        writer.write(f)
    return out


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    b.OUT = OUT                                   # errors.log goes here, not into the full benchmark folder
    (OUT / "errors.log").unlink(missing_ok=True)
    if not HAS_AZURE:
        print("Azure is skipped: AZURE_DI_ENDPOINT / AZURE_DI_KEY not found in .env "
              "(manual Azure files in data/output/azure_manual are still measured).")
    rows = []
    for kind, folder in SOURCES:
        for src in sorted(folder.glob("*.pdf")):
            pdf = trim(src)
            for tool, fn in TOOLS.items():
                d = OUT / tool / pdf.stem
                runs = 1 if tool == "azure" else b.RUNS      # run 1 warms up Docling; Azure is a paid call
                times, err = [], ""
                for _ in range(runs):
                    t0 = time.perf_counter()
                    try:
                        fn(pdf, d)
                        times.append(time.perf_counter() - t0)
                    except Exception as e:
                        err = b.short_error(e)
                        b.log_error(f"{pdf.name} / {tool}")
                        break
                m = {}
                if not err:
                    m = b.opensource_metrics(pdf, d) if tool == "opensource" else b.md_metrics(
                        (d / f"{pdf.stem}.md").read_text(encoding="utf-8"))
                rows.append({"kind": kind, "doc": pdf.stem, "tool": tool,
                             "seconds": round(min(times), 2) if times else "", "error": err, **m})
                print(f"{kind:12} {pdf.stem:28} {tool:11} {rows[-1]['seconds']}s {err}")
            manual = MANUAL / f"{pdf.stem}.md"
            if not HAS_AZURE and manual.exists():
                rows.append({"kind": kind, "doc": pdf.stem, "tool": "azure (manual)", "seconds": "", "error": "",
                             **b.md_metrics(manual.read_text(encoding="utf-8"))})
                print(f"{kind:12} {pdf.stem:28} azure (manual) measured from {manual.name}")
    if not rows:
        sys.exit("No PDFs found in data/input/ or data/input/web_pdf/")
    csv_path = OUT / "benchmark_2pages.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=KEYS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"\nSaved: {csv_path}")
    if (OUT / "errors.log").exists():
        print(f"Some runs failed. Details: {OUT / 'errors.log'}")


if __name__ == "__main__":
    main()
