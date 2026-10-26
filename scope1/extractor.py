from pathlib import Path
import json

from pypdf import PdfReader
import pdfplumber


# Project folders (resolved from this file, so it works from any working directory)
PROJECT_ROOT = Path(__file__).resolve().parent.parent

INPUT_DIR = PROJECT_ROOT / "data" / "input"
OUTPUT_DIR = PROJECT_ROOT / "data" / "output"


# FUNCTION 1: Extract text using pypdf
def extract_text_with_pypdf(pdf_path, output_dir):
    pdf_path, output_dir = Path(pdf_path), Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    reader = PdfReader(str(pdf_path))

    all_text = []

    for page_number, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        all_text.append(f"--- Page {page_number} ---\n{text}")

    output_file = output_dir / f"{pdf_path.stem}.txt"
    output_file.write_text("\n\n".join(all_text), encoding="utf-8")

    print(f"Text saved to: {output_file}")


# FUNCTION 2: Extract tables, layout and images
def extract_tables_layout_images(pdf_path, output_dir):
    pdf_path, output_dir = Path(pdf_path), Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    tables_data = []
    layout_data = []

    # One images folder PER PDF, so images from different PDFs never overwrite each other
    images_dir = output_dir / "images" / pdf_path.stem
    images_dir.mkdir(parents=True, exist_ok=True)

    # Extract tables and layout using pdfplumber
    with pdfplumber.open(str(pdf_path)) as pdf:
        for page_number, page in enumerate(pdf.pages, start=1):
            tables = page.extract_tables() or []
            tables_data.append({"page": page_number, "tables": tables})

            words = page.extract_words() or []
            layout_data.append({
                "page": page_number,
                "width": page.width,
                "height": page.height,
                "words": words,
            })

    tables_file = output_dir / f"{pdf_path.stem}_tables.json"
    tables_file.write_text(
        json.dumps(tables_data, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"Tables saved to: {tables_file}")

    layout_file = output_dir / f"{pdf_path.stem}_layout.json"
    layout_file.write_text(
        json.dumps(layout_data, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"Layout saved to: {layout_file}")

    # Extract embedded images using pypdf
    reader = PdfReader(str(pdf_path))
    image_count = 0

    for page_number, page in enumerate(reader.pages, start=1):
        try:
            for image_index, image in enumerate(page.images, start=1):
                extension = Path(Path(image.name).name).suffix or ".bin"
                image_file = images_dir / (
                    f"page_{page_number:03d}_image_{image_index:03d}{extension}"
                )
                image_file.write_bytes(image.data)
                image_count += 1
        except Exception as error:
            print(f"Warning: Could not extract images from page {page_number}: {error}")

    print(f"Total embedded images saved: {image_count}")


# Main function: run both extraction functions on EVERY PDF in data/input
def main():
    pdfs = sorted(INPUT_DIR.glob("*.pdf"))
    if not pdfs:
        print(f"ERROR: no PDFs found in {INPUT_DIR}")
        return

    for pdf in pdfs:
        print(f"\nStarting PDF extraction: {pdf.name}")
        extract_text_with_pypdf(pdf, OUTPUT_DIR)
        extract_tables_layout_images(pdf, OUTPUT_DIR)

    print("\nPDF extraction completed!")


if __name__ == "__main__":
    main()
