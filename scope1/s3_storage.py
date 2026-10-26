"""Task 5: S3 layout, metadata/tags, encryption, link rewriting.

Key layout (all keys are lowercase, no spaces):
  raw/pdf/<source>/<YYYY-MM-DD>/<docid>.pdf              original uploads
  raw/html/<source>/<YYYY-MM-DD>/<docid>.html            fetched web pages
  processed/markdown/<tool>/<source>/<docid>.md          final Markdown (docling | markitdown)
  processed/extracted/<tool>/<source>/<docid>/<file>     open-source output (txt / json)
  assets/images/<source>/<docid>/<image>                 extracted images, linked from the Markdown
<source> = "uploaded" for user PDFs, or the site name for web pages (e.g. en-wikipedia-org).
<docid>  = <slugified-name>-<8-char content hash>, so the same document always maps to the same keys.
"""
import mimetypes
import os
import re
from datetime import date
from pathlib import Path
from urllib.parse import quote

import boto3
from botocore.config import Config

REGION = os.environ.get("AWS_REGION", "ap-south-1")
ENDPOINT = os.environ.get("S3_ENDPOINT_URL") or None     # set for MinIO/LocalStack only


def bucket():
    name = os.environ.get("S3_BUCKET")
    if not name:
        raise RuntimeError("Set the S3_BUCKET environment variable")
    return name


def client():
    return boto3.client("s3", region_name=REGION, endpoint_url=ENDPOINT,
                        config=Config(signature_version="s3v4"))


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "doc"


def today():
    return date.today().isoformat()


def raw_key(kind, source, docid, ext):
    return f"raw/{kind}/{source}/{today()}/{docid}.{ext}"


def markdown_key(tool, source, docid):
    return f"processed/markdown/{tool}/{source}/{docid}.md"


def extracted_key(tool, source, docid, filename):
    return f"processed/extracted/{tool}/{source}/{docid}/{filename}"


def image_key(source, docid, filename):
    return f"assets/images/{source}/{docid}/{filename}"


def _ascii(value):
    """S3 user metadata must be ASCII."""
    return str(value).encode("ascii", "ignore").decode()[:1000]


def put(key, body, *, doc_type, tool, source_url="", extra=None):
    """Upload bytes with encryption, metadata (searchable) and tags (filterable / for access rules)."""
    if isinstance(body, (str, Path)) and Path(str(body)).exists():
        body = Path(body).read_bytes()
    elif isinstance(body, str):
        body = body.encode("utf-8")
    meta = {"source-url": source_url or "uploaded", "tool": tool,
            "processed-date": today(), "doc-type": doc_type}
    meta.update(extra or {})
    tags = f"tool={quote(tool)}&doctype={quote(doc_type)}&date={today()}"
    ctype = mimetypes.guess_type(key)[0] or "application/octet-stream"
    if key.endswith(".md"):
        ctype = "text/markdown; charset=utf-8"
    client().put_object(
        Bucket=bucket(), Key=key, Body=body, ContentType=ctype,
        ServerSideEncryption="AES256",
        Metadata={k: _ascii(v) for k, v in meta.items()}, Tagging=tags,
    )
    return key


def uri(key):
    return f"s3://{bucket()}/{key}"


def presign(key, expires=3600):
    return client().generate_presigned_url(
        "get_object", Params={"Bucket": bucket(), "Key": key}, ExpiresIn=expires)


def rewrite_image_links(markdown, image_keys):
    """Replace local links like ](images/foo.png) with s3:// links to the uploaded image.
    image_keys: {filename: s3 key}"""
    def repl(m):
        name = Path(m.group(1)).name
        return f"]({uri(image_keys[name])})" if name in image_keys else m.group(0)
    return re.sub(r"\]\((?:\./)?images/([^)\s]+)\)", repl, markdown)


def presign_markdown(markdown, expires=3600):
    """For display: turn s3://bucket/key links into temporary HTTPS links (the bucket stays private)."""
    prefix = f"s3://{bucket()}/"
    def repl(m):
        return f"]({presign(m.group(1), expires)})"
    return re.sub(r"\]\(" + re.escape(prefix) + r"([^)\s]+)\)", repl, markdown)


def list_keys(prefix="processed/markdown/", limit=200):
    out = []
    for page in client().get_paginator("list_objects_v2").paginate(Bucket=bucket(), Prefix=prefix):
        for obj in page.get("Contents", []):
            out.append({"key": obj["Key"], "size": obj["Size"],
                        "modified": obj["LastModified"].isoformat()})
            if len(out) >= limit:
                return out
    return out


def get_text(key):
    return client().get_object(Bucket=bucket(), Key=key)["Body"].read().decode("utf-8")
