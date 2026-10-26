"""Task 6 backend. Run from the project root:
    uvicorn api:app --app-dir app --reload
Interactive UI (works as the demo front end): http://127.0.0.1:8000/docs
"""
import importlib.util
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")   # reads S3_BUCKET, AWS_* from .env

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

import pipeline
import s3_storage as s3

MAX_BYTES = 25 * 1024 * 1024
Tool = Literal["docling", "markitdown"]

app = FastAPI(title="Unstructured Data Ingestion Pipeline",
              description="Upload a PDF or submit a URL; get Markdown back and stored in S3.")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

@app.get("/", include_in_schema=False)
def root():
    return {"message": "Ingestion API is running. See /docs"}

class UrlRequest(BaseModel):
    url: str


def _read_pdf(file: UploadFile):
    data = file.file.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise HTTPException(413, "PDF larger than 25 MB")
    if not data.startswith(b"%PDF"):
        raise HTTPException(400, "File is not a valid PDF")
    return data


def _run(fn, *args):
    try:
        return fn(*args)
    except PermissionError as e:
        raise HTTPException(403, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    except ImportError as e:
        raise HTTPException(503, f"This tool is not installed on this deployment ({e.name}). "
                                 "Use 'markitdown' or the open-source endpoints, or run the project locally for Docling.")
    except Exception as e:                     # surface the reason instead of a blank 500
        raise HTTPException(500, f"{type(e).__name__}: {e}")


@app.get("/health")
def health():
    return {"status": "ok", "docling": importlib.util.find_spec("docling") is not None}


@app.post("/pdf/extract", summary="Open-source extraction (pypdf + pdfplumber) of an uploaded PDF")
def pdf_extract(file: UploadFile = File(...)):
    return _run(pipeline.pdf_extract, _read_pdf(file), file.filename or "upload.pdf")


@app.post("/pdf/standardize", summary="Convert an uploaded PDF to Markdown with Docling or MarkItDown")
def pdf_standardize(file: UploadFile = File(...), tool: Tool = Query("docling")):
    return _run(pipeline.pdf_standardize, _read_pdf(file), file.filename or "upload.pdf", tool)


@app.post("/url/extract", summary="Open-source scrape (requests + BeautifulSoup) of a URL")
def url_extract(body: UrlRequest):
    return _run(pipeline.url_extract, body.url)


@app.post("/url/standardize", summary="Convert a web page to Markdown with Docling or MarkItDown")
def url_standardize(body: UrlRequest, tool: Tool = Query("docling")):
    return _run(pipeline.url_standardize, body.url, tool)


@app.get("/documents", summary="List stored Markdown files")
def documents(prefix: str = "processed/markdown/"):
    return {"items": _run(s3.list_keys, prefix)}


@app.get("/documents/markdown", summary="Fetch one stored Markdown file (image links made viewable)")
def document_markdown(key: str):
    if not key.startswith("processed/markdown/"):
        raise HTTPException(400, "key must start with processed/markdown/")
    return {"key": key, "markdown": s3.presign_markdown(_run(s3.get_text, key))}


@app.get("/files/{key:path}", include_in_schema=False)
def local_file(key: str):
    """Serves stored files ONLY in STORAGE_MODE=local (in S3 mode, presigned S3 links are used)."""
    if not s3.LOCAL:
        raise HTTPException(404, "Not found")
    root = s3.LOCAL_ROOT.resolve()
    path = (root / key).resolve()
    if root not in path.parents or not path.is_file():      # block path traversal
        raise HTTPException(404, "Not found")
    return FileResponse(path)
