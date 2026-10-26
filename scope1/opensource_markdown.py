"""Reassemble open-source extraction (pdfplumber) into ONE reading-order Markdown file.

    python app/opensource_markdown.py data/input/some.pdf          # -> data/output/opensource_md/some.md

What it does (no AI models, only geometry + font sizes):
  * text lines      -> paragraphs; big/bold short lines become # headings
  * tables          -> Markdown tables (placed where they sit on the page)
  * embedded images -> cropped PNG files, linked as ![..](images/<file>)
  * two-column pages are detected and read left column, then right column

Known limits (these are real findings for the Task 3 comparison, say so in the write-up):
  * formulas stay as plain text (no LaTeX), key-value blocks stay as plain lines
  * vector figures (drawn, not embedded) are not detected as images
  * tables without ruling lines may be missed; complex layouts can be mis-ordered
"""
import re
import sys
from collections import Counter
from pathlib import Path

MIN_IMG = 40          # ignore images smaller than 40 pt (icons, bullets)


# --------------------------------------------------------------- shared helper (also used by webscraper.py)
def _cell(c):
    return re.sub(r"\s+", " ", str(c or "")).replace("|", "\\|").strip()


def table_to_md(rows):
    """List of rows -> Markdown table. Returns "" for layout boxes / empty false positives."""
    rows = [[_cell(c) for c in r] for r in rows if r]
    rows = [r for r in rows if any(r)]
    if len(rows) < 2:
        return ""
    width = max(len(r) for r in rows)
    if width < 2:
        return ""
    rows = [r + [""] * (width - len(r)) for r in rows]
    lines = ["| " + " | ".join(rows[0]) + " |", "|" + "|".join(["---"] * width) + "|"]
    lines += ["| " + " | ".join(r) + " |" for r in rows[1:]]
    return "\n".join(lines)


# --------------------------------------------------------------- PDF
def _is_two_column(lines, width):
    body = [l for l in lines if len(l["text"]) > 20]
    if len(body) < 10:
        return False
    mid = width / 2
    crossing = sum(1 for l in body if l["x0"] < mid - 10 and l["x1"] > mid + 10)
    left = sum(1 for l in body if l["x1"] <= mid + 10)
    right = sum(1 for l in body if l["x0"] >= mid - 10)
    return crossing / len(body) < 0.15 and left >= 3 and right >= 3


def _line_style(line, body_size):
    sizes = [c["size"] for c in line["chars"]] or [body_size]
    size = sorted(sizes)[len(sizes) // 2]
    letters = [c for c in line["chars"] if c["text"].strip()]
    bold = bool(letters) and all("bold" in c.get("fontname", "").lower() for c in letters)
    return size, bold


def _heading_level(line, body_size):
    text = line["text"].strip()
    if not text or len(text) > 150:
        return 0
    size, bold = _line_style(line, body_size)
    if size >= body_size * 1.6:
        return 1
    if size >= body_size * 1.3:
        return 2
    if size >= body_size * 1.12:
        return 3
    if bold and len(text) < 80 and not text.endswith((".", ",", ":")):
        return 3
    return 0


BULLET = re.compile(r"^([\u2022\u25cf\u25aa\u2013\-\*]|\d{1,2}[.)])\s+")


def _running_lines(all_lines, page_heights):
    """Texts that repeat at the top/bottom of most pages (running headers, 'Page 3 of 6')."""
    if len(all_lines) < 3:
        return set()
    count = Counter()
    for lines, h in zip(all_lines, page_heights):
        seen = set()
        for l in lines:
            if l["top"] < h * 0.08 or l["bottom"] > h * 0.92:
                seen.add(re.sub(r"\d+", "#", l["text"].strip()))
        count.update(seen)
    return {t for t, n in count.items() if n >= max(3, len(all_lines) * 0.5)}


def _page_markdown(page, lines, pno, body_size, img_dir, img_prefix, skip=frozenset()):
    W = page.width
    two_col = _is_two_column(lines, W)
    mid = W / 2

    def col_of(x0, x1):
        return 1 if two_col and (x0 + x1) / 2 > mid and (x1 - x0) < 0.6 * W else 0

    elems = []  # (col, top, kind, payload)

    # tables
    boxes = []
    try:
        for t in page.find_tables():
            md = table_to_md(t.extract())
            if md:
                x0, top, x1, bottom = t.bbox
                boxes.append(t.bbox)
                elems.append((col_of(x0, x1), top, "block", md))
    except Exception as e:
        print(f"  warning: tables on page {pno}: {e}")

    # images
    px0, ptop, px1, pbottom = page.bbox
    for i, im in enumerate(page.images, start=1):
        if im["x1"] - im["x0"] < MIN_IMG or im["bottom"] - im["top"] < MIN_IMG:
            continue
        box = (max(im["x0"], px0), max(im["top"], ptop), min(im["x1"], px1), min(im["bottom"], pbottom))
        name = f"md_p{pno:03d}_img{i:03d}.png"
        try:
            page.crop(box).to_image(resolution=150).save(str(img_dir / name))
            elems.append((col_of(box[0], box[2]), box[1], "block", f"![Figure (page {pno})]({img_prefix}/{name})"))
        except Exception as e:
            print(f"  warning: image on page {pno}: {e}")

    # text lines (skip the ones that belong to a table we kept)
    for l in lines:
        cx, cy = (l["x0"] + l["x1"]) / 2, (l["top"] + l["bottom"]) / 2
        if any(b[0] <= cx <= b[2] and b[1] <= cy <= b[3] for b in boxes):
            continue
        if re.sub(r"\d+", "#", l["text"].strip()) in skip and (l["top"] < page.height * 0.08 or l["bottom"] > page.height * 0.92):
            continue
        if l["text"].strip():
            elems.append((col_of(l["x0"], l["x1"]), l["top"], "line", l))

    elems.sort(key=lambda e: (e[0], e[1]))

    out, para, prev, last_head = [], [], None, None

    def flush():
        nonlocal para
        if para:
            out.append(" ".join(para))
            para = []

    for col, top, kind, payload in elems:
        if kind == "block":
            flush()
            out.append(payload)
            prev = None
            continue
        line = payload
        level = _heading_level(line, body_size)
        text = line["text"].strip()
        if level:
            flush()
            if last_head and last_head[0] == level and last_head[1] == col and line["top"] - last_head[2] < 1.6 * (line["bottom"] - line["top"]):
                out[-1] += " " + text                 # heading wrapped over two lines
            else:
                out.append("#" * level + " " + text)
            last_head = (level, col, line["bottom"])
            prev = None
            continue
        last_head = None
        height = max(line["bottom"] - line["top"], 1)
        is_item = bool(BULLET.match(text))
        new_para = prev is None or prev[0] != col or is_item or (line["top"] - prev[1]) > 0.9 * height
        if new_para:
            flush()
        if is_item and re.match(r"^[\u2022\u25cf\u25aa\u2013*]\s", text):
            text = "- " + text[2:].lstrip()
        if para and para[-1].endswith("-") and text[:1].islower():
            para[-1] = para[-1][:-1] + text          # re-join hyphenated word
        else:
            para.append(text)
        prev = (col, line["bottom"])
    flush()
    return "\n\n".join(out)


def pdf_to_markdown(pdf_path, out_md, image_subdir="images"):
    """Convert one PDF to Markdown (+ cropped images in <out_md folder>/<image_subdir>/)."""
    import pdfplumber

    pdf_path, out_md = Path(pdf_path), Path(out_md)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    img_dir = out_md.parent / image_subdir
    img_dir.mkdir(parents=True, exist_ok=True)

    parts = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        all_lines = [p.extract_text_lines(return_chars=True) for p in pdf.pages]
        sizes = Counter(round(c["size"]) for lines in all_lines for l in lines for c in l["chars"])
        body_size = sizes.most_common(1)[0][0] if sizes else 10
        skip = _running_lines(all_lines, [p.height for p in pdf.pages])
        for pno, (page, lines) in enumerate(zip(pdf.pages, all_lines), start=1):
            parts.append(_page_markdown(page, lines, pno, body_size, img_dir, image_subdir, skip))
    out_md.write_text("\n\n".join(p for p in parts if p) + "\n", encoding="utf-8")
    print(f"Open-source Markdown saved: {out_md}")
    return out_md


if __name__ == "__main__":
    root = Path(__file__).resolve().parent.parent
    targets = [Path(a) for a in sys.argv[1:]] or sorted((root / "data" / "input").glob("*.pdf"))
    for p in targets:
        pdf_to_markdown(p, root / "data" / "output" / "opensource_md" / f"{p.stem}.md")
