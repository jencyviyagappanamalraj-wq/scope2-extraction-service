"""Task 5 helper: fill the S3 bucket by running the real pipeline, then print the resulting layout.

    python app/seed_bucket.py                    # Docling + MarkItDown on every PDF and both web pages
    python app/seed_bucket.py --tool markitdown  # faster (skips Docling)

Needs .env (S3_BUCKET, AWS keys) and an existing bucket (python app/setup_bucket.py).
Writes the key listing to docs/s3_listing.txt so you can show it in the README / demo.
"""
import argparse, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

import pipeline
import s3_storage as s3

URLS = [
    "https://en.wikipedia.org/wiki/Python_(programming_language)",
    "https://en.wikipedia.org/wiki/India",
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tool", choices=["docling", "markitdown", "both"], default="both")
    tools = ["docling", "markitdown"] if ap.parse_args().tool == "both" else [ap.parse_args().tool]

    for pdf in sorted((ROOT / "data" / "input").glob("*.pdf")):
        data = pdf.read_bytes()
        for tool in tools:
            try:
                r = pipeline.pdf_standardize(data, pdf.name, tool)
                print(f"OK   {pdf.name} [{tool}] -> {r['markdown_key']}  ({r['images']} images)")
            except Exception as e:
                print(f"FAIL {pdf.name} [{tool}]: {type(e).__name__}: {str(e)[:200]}")
        try:
            r = pipeline.pdf_extract(data, pdf.name)
            print(f"OK   {pdf.name} [open-source] -> {len(r['files'])} files")
        except Exception as e:
            print(f"FAIL {pdf.name} [open-source]: {type(e).__name__}: {str(e)[:200]}")

    for url in URLS:
        for tool in tools:
            try:
                r = pipeline.url_standardize(url, tool)
                print(f"OK   {url} [{tool}] -> {r['markdown_key']}")
            except Exception as e:
                print(f"FAIL {url} [{tool}]: {type(e).__name__}: {str(e)[:200]}")
        try:
            r = pipeline.url_extract(url)
            print(f"OK   {url} [open-source] -> {len(r['files'])} files")
        except Exception as e:
            print(f"FAIL {url} [open-source]: {type(e).__name__}: {str(e)[:200]}")

    items = s3.list_keys("", 2000)
    listing = "\n".join(i["key"] for i in items)
    (ROOT / "docs").mkdir(exist_ok=True)
    (ROOT / "docs" / "s3_listing.txt").write_text(listing, encoding="utf-8")
    print(f"\n=== Bucket contents ({len(items)} objects) ===\n{listing}")

    md = [i["key"] for i in items if i["key"].startswith("processed/markdown/")]
    if md:
        head = s3.client().head_object(Bucket=s3.bucket(), Key=md[0])
        print(f"\nMetadata of {md[0]}:\n  {head.get('Metadata')}\n  encryption: {head.get('ServerSideEncryption')}")


if __name__ == "__main__":
    main()
