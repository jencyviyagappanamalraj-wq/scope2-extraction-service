from pathlib import Path

# Heavy libraries are imported lazily (inside the functions) so a lean deployment
# without Docling can still import this module and use MarkItDown.

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INPUT_DIR = PROJECT_ROOT / "data" / "input"
MARKDOWN_DIR = PROJECT_ROOT / "data" / "output" / "markdown"

_docling_converter = None


def get_docling_converter():
    """Build the Docling converter once and reuse it (model loading is slow)."""
    global _docling_converter
    if _docling_converter is None:
        from docling.document_converter import DocumentConverter, PdfFormatOption
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import PdfPipelineOptions

        pipeline_options = PdfPipelineOptions()
        pipeline_options.generate_picture_images = True
        pipeline_options.do_formula_enrichment = True      # formulas -> LaTeX ($$ ... $$); slower, downloads a model on first run
        _docling_converter = DocumentConverter(
            format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)}
        )
    return _docling_converter


def convert_pdf_with_docling(pdf_path, output_path):
    """Convert a PDF into Markdown using Docling and save images separately."""
    from docling_core.types.doc import ImageRefMode

    pdf_path, output_path = Path(pdf_path), Path(output_path)
    print(f"Processing with Docling: {pdf_path}")

    result = get_docling_converter().convert(str(pdf_path))
    document = result.document
    print(f"Pictures detected by Docling: {len(document.pictures)}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    image_dir = output_path.parent / "images"
    image_dir.mkdir(parents=True, exist_ok=True)

    markdown = document.export_to_markdown(
        image_mode=ImageRefMode.REFERENCED,
        image_dir=image_dir,
        image_uri_prefix="images/",
    )
    output_path.write_text(markdown, encoding="utf-8")
    print(f"Docling Markdown saved: {output_path}")


def convert_pdf_with_markitdown(pdf_path, output_path):
    """Convert a PDF into Markdown using MarkItDown (no image extraction for PDFs)."""
    from markitdown import MarkItDown

    pdf_path, output_path = Path(pdf_path), Path(output_path)
    print(f"Processing with MarkItDown: {pdf_path}")

    markdown = MarkItDown().convert(str(pdf_path)).text_content

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(markdown, encoding="utf-8")
    print(f"MarkItDown Markdown saved: {output_path}")


def run_all():
    pdfs = sorted(INPUT_DIR.glob("*.pdf"))
    if not pdfs:
        print(f"ERROR: no PDFs found in {INPUT_DIR}")
        return
    for pdf in pdfs:
        convert_pdf_with_docling(pdf, MARKDOWN_DIR / "docling" / pdf.stem / f"{pdf.stem}.md")
        convert_pdf_with_markitdown(pdf, MARKDOWN_DIR / "markitdown" / f"{pdf.stem}.md")


if __name__ == "__main__":
    run_all()
