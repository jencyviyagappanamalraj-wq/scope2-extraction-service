from collections import Counter
from pathlib import Path

import pdfplumber

from md_utils import rows_to_markdown


def _rows_from_words(words, tol=3):
    """Group words into text rows by their vertical position."""
    rows = []
    for w in sorted(words, key=lambda w: (w["top"], w["x0"])):
        if rows and abs(w["top"] - rows[-1][0]["top"]) <= tol:
            rows[-1].append(w)
        else:
            rows.append([w])
    return rows


def _find_gutter(rows, width):
    """x position of the empty strip between two text columns, or None for one-column pages."""
    if len(rows) < 8:
        return None
    total = sum(len(r) for r in rows)
    best = None
    for x in range(int(width * 0.35), int(width * 0.65), 2):
        crossing = sum(1 for r in rows if any(w["x0"] < x + 4 and w["x1"] > x - 4 for w in r))
        if best is None or crossing < best[1]:
            best = (x, crossing)
    x, crossing = best
    left = sum(1 for r in rows for w in r if (w["x0"] + w["x1"]) / 2 < x)
    if crossing / len(rows) <= 0.35 and left >= 0.25 * total and (total - left) >= 0.25 * total:
        return x
    return None


def _line(ws, col):
    ws = sorted(ws, key=lambda w: w["x0"])
    return {"kind": "text", "col": col, "text": " ".join(w["text"] for w in ws),
            "size": max(w["size"] for w in ws),
            "top": min(w["top"] for w in ws), "bottom": max(w["bottom"] for w in ws)}


def _text_items(words, width):
    rows = _rows_from_words(words)
    gutter = _find_gutter(rows, width)
    if gutter is None:
        return [_line(r, "full") for r in rows], None
    # a row that touches the gutter is full-width text (title, abstract, ...)
    straddle = [any(w["x0"] < gutter + 4 and w["x1"] > gutter - 4 for w in r) for r in rows]
    # a short run of "free" rows between full-width rows is most likely full-width text too
    full = list(straddle)
    i = 0
    while i < len(rows):
        if straddle[i]:
            i += 1
            continue
        j = i
        while j < len(rows) and not straddle[j]:
            j += 1
        if j - i < 3 and (i > 0 or j < len(rows)):
            for k in range(i, j):
                full[k] = True
        i = j
    items = []
    for r, is_full in zip(rows, full):
        if is_full:
            items.append(_line(r, "full"))
        else:
            left = [w for w in r if (w["x0"] + w["x1"]) / 2 < gutter]
            right = [w for w in r if (w["x0"] + w["x1"]) / 2 >= gutter]
            if left:
                items.append(_line(left, "L"))
            if right:
                items.append(_line(right, "R"))
    return items, gutter


def _page_to_markdown(page, number, body, stem, images_dir):
    blocks, items = [], []

    for t in page.find_tables():
        md = rows_to_markdown(t.extract())
        if md:
            x0, top, x1, bottom = t.bbox
            blocks.append(t.bbox)
            items.append({"kind": "block", "text": md, "top": top, "bottom": bottom, "x0": x0, "x1": x1})

    for k, im in enumerate(page.images, start=1):
        bx = page.bbox
        bbox = (max(im["x0"], bx[0]), max(im["top"], bx[1]), min(im["x1"], bx[2]), min(im["bottom"], bx[3]))
        if bbox[2] - bbox[0] < 40 or bbox[3] - bbox[1] < 40:       # skip icons and bullets
            continue
        name = f"page_{number:03d}_figure_{k:02d}.png"
        try:
            page.crop(bbox).to_image(resolution=150).save(str(images_dir / name))
        except Exception as e:
            print(f"Warning: could not save figure {k} on page {number}: {e}")
            continue
        blocks.append(bbox)
        items.append({"kind": "block", "text": f"![Figure {number}.{k}](images/{name})",
                      "top": bbox[1], "bottom": bbox[3], "x0": bbox[0], "x1": bbox[2]})

    def outside(w):
        cx, cy = (w["x0"] + w["x1"]) / 2, (w["top"] + w["bottom"]) / 2
        return not any(b[0] <= cx <= b[2] and b[1] <= cy <= b[3] for b in blocks)

    words = [w for w in page.extract_words(extra_attrs=["size"]) if outside(w)]
    gutter = None
    if words:
        text_items, gutter = _text_items(words, page.width)
        items += text_items

    # place tables / figures into a column (or full width)
    for it in items:
        if it["kind"] == "block":
            centre = (it["x0"] + it["x1"]) / 2
            wide = (it["x1"] - it["x0"]) > 0.6 * page.width
            it["col"] = "full" if (gutter is None or wide) else ("L" if centre < gutter else "R")

    # reading order: full-width items split the page; between them left column, then right column
    items.sort(key=lambda i: i["top"])
    ordered, group = [], []

    def flush_group():
        ordered.extend(sorted([i for i in group if i["col"] == "L"], key=lambda i: i["top"]))
        ordered.extend(sorted([i for i in group if i["col"] == "R"], key=lambda i: i["top"]))
        group.clear()

    for it in items:
        if it["col"] == "full":
            flush_group()
            ordered.append(it)
        else:
            group.append(it)
    flush_group()

    # lines -> paragraphs and headings
    out, para, prev, head = [], [], None, None   # head = (level, index in out) of the previous heading line

    def flush_para():
        if para:
            out.append(" ".join(para))
            para.clear()

    for it in ordered:
        if it["kind"] == "block":
            flush_para()
            out.append(it["text"])
            prev, head = None, None
            continue
        text, size = it["text"], it["size"]
        if size >= body * 1.15 and len(text) < 150:
            flush_para()
            level = "#" if size >= body * 1.6 else "##" if size >= body * 1.3 else "###"
            if head and head[0] == level and prev is not None and it["top"] - prev["bottom"] < 6:
                out[head[1]] += " " + text            # heading that wraps onto a second line
            else:
                out.append(f"{level} {text}")
                head = (level, len(out) - 1)
        else:
            head = None
            height = it["bottom"] - it["top"]
            if prev is None or prev["col"] != it["col"] or it["top"] - prev["bottom"] > 0.6 * height:
                flush_para()
            para.append(text)
        prev = it
    flush_para()
    return "\n\n".join(out)


def extract_markdown_reading_order(pdf_path, output_dir):
    """Open-source reassembly: text, tables and figures in reading order -> one Markdown string.
    Figures are saved as PNG files in <output_dir>/images/<pdf name>/ and linked as images/<file>."""
    pdf_path, output_dir = Path(pdf_path), Path(output_dir)
    images_dir = output_dir / "images" / pdf_path.stem
    images_dir.mkdir(parents=True, exist_ok=True)
    parts = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        sizes = Counter(round(c["size"], 1) for p in pdf.pages for c in p.chars)
        body = sizes.most_common(1)[0][0] if sizes else 10
        for number, page in enumerate(pdf.pages, start=1):
            md = _page_to_markdown(page, number, body, pdf_path.stem, images_dir)
            parts.append(f"<!-- Page {number} -->\n\n{md}" if md else f"<!-- Page {number} -->")
    return "\n\n".join(parts)
