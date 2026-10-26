"""
Task 3 benchmark for PDFs. Calls YOUR functions from extractor.py, opensource_markdown.py and
docling_markitdown.py, and compares: open-source libraries vs Docling vs MarkItDown.

    python app/benchmark.py              # every PDF in data/input/
    python app/benchmark.py data/input/a.pdf

Results: data/output/benchmark/benchmark.csv   (one row per document x tool)
Errors : data/output/benchmark/errors.log      (full details if any tool failed)
"""
import csv, json, re, sys, time, traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dotenv import load_dotenv
ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

import extractor
import opensource_markdown as osm
import docling_markitdown as dm

OUT = ROOT / "data" / "output" / "benchmark"
RUNS = 2   # run 1 warms up (Docling model load); we report the FASTEST run


def run_opensource(pdf, d):
    extractor.extract_text_with_pypdf(pdf, d)
    extractor.extract_tables_layout_images(pdf, d)
    osm.pdf_to_markdown(pdf, d / f"{pdf.stem}.md", image_subdir="md_images")   # reassembled Markdown


def run_docling(pdf, d):
    dm.convert_pdf_with_docling(pdf, d / f"{pdf.stem}.md")


def run_markitdown(pdf, d):
    dm.convert_pdf_with_markitdown(pdf, d / f"{pdf.stem}.md")


TOOLS = {"opensource": run_opensource, "docling": run_docling, "markitdown": run_markitdown}


def md_metrics(text):
    lines = text.splitlines()
    return {
        "chars": len(text),
        "headings": sum(1 for l in lines if re.match(r"#{1,6} ", l)),
        # Markdown pipe tables + HTML <table>
        "tables": len(re.findall(r"^\|[\s\-:|]+\|$", text, flags=re.M)) + len(re.findall(r"<table", text, flags=re.I)),
        # real LaTeX only: $$...$$ blocks, or $...$ containing \ ^ _ { (so dollar amounts don't count)
        "formulas": text.count("$$") // 2 + len(re.findall(r"(?<!\$)\$(?=[^$\n]*[\\^_{])[^$\n]+\$(?!\$)", text)),
        "images": len(re.findall(r"!\[.*?\]\(.*?\)|<!-- image -->|<figure>", text)),
    }


def opensource_metrics(pdf, d):
    text = (d / f"{pdf.stem}.txt").read_text(encoding="utf-8")
    tables = json.loads((d / f"{pdf.stem}_tables.json").read_text(encoding="utf-8"))
    flat = [t for p in tables for t in p["tables"]]
    imgs = list((d / "images" / pdf.stem).glob("*"))
    md = (d / f"{pdf.stem}.md").read_text(encoding="utf-8")
    return {"chars": len(text), "headings": md_metrics(md)["headings"], "tables": len(flat),
            "formulas": 0, "images": len(imgs)}


def short_error(e):
    return f"{type(e).__name__}: {str(e)[:150]}".replace("\n", " ")


def log_error(label):
    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / "errors.log", "a", encoding="utf-8") as f:
        f.write(f"=== {label} ===\n{traceback.format_exc()}\n")


def main(args):
    pdfs = [Path(a) for a in args] or sorted((ROOT / "data" / "input").glob("*.pdf"))
    if not pdfs:
        sys.exit("No PDFs found in data/input/")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "errors.log").unlink(missing_ok=True)
    rows = []
    for pdf in pdfs:
        for tool, fn in TOOLS.items():
            d = OUT / tool / pdf.stem
            times, err = [], ""
            for _ in range(RUNS):
                t0 = time.perf_counter()
                try:
                    fn(pdf, d)
                    times.append(time.perf_counter() - t0)
                except Exception as e:
                    err = short_error(e)
                    log_error(f"{pdf.name} / {tool}")
                    break
            m = {}
            if not err:
                m = opensource_metrics(pdf, d) if tool == "opensource" else md_metrics(
                    (d / f"{pdf.stem}.md").read_text(encoding="utf-8"))
            rows.append({"doc": pdf.stem, "tool": tool,
                         "seconds": round(min(times), 2) if times else "", "error": err, **m})
            print(f"{pdf.stem:25} {tool:11} {rows[-1]['seconds']}s {err}")
    keys = ["doc", "tool", "seconds", "chars", "headings", "tables", "formulas", "images", "error"]
    with open(OUT / "benchmark.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"\nSaved: {OUT / 'benchmark.csv'}")
    if (OUT / "errors.log").exists():
        print(f"Some runs failed. Details: {OUT / 'errors.log'}")


if __name__ == "__main__":
    main(sys.argv[1:])
