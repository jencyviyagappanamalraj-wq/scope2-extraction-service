"""Scope 2 evaluation script. Standard library only (no installs, no extra disk).

Folder layout (next to this file):
  ground_truth/<doc>.json          the correct answers (you write these, see example.json)
  outputs/<tool>/<doc>.md          each tool's Markdown output for that document
  outputs/<tool>/_max_page.txt     optional, one number, e.g. 2 for a tool that only read pages 1-2

Run:   python evaluate.py
Prints: a table of scores (0 to 1) per tool and element type.
Writes: results.csv (summary) and details.csv (every element, to pick side-by-side examples).
"""
import csv
import difflib
import json
import re
from pathlib import Path

HERE = Path(__file__).parent
GT_DIR = HERE / "ground_truth"
OUT_DIR = HERE / "outputs"
TYPES = ["heading", "text", "table", "formula", "key_value", "image"]
FUZZY = 0.85  # how close two strings must be to count as a match (0 to 1)


def norm(s):
    s = s.lower()
    s = re.sub(r"[#*_`$\\|{}\[\]]", " ", s)  # markdown and LaTeX symbols
    return re.sub(r"\s+", " ", s).strip()


def best_ratio(needle, chunks):
    needle = norm(needle)
    best = 0.0
    for c in chunks:
        c = norm(c)
        if needle and needle in c:
            return 1.0
        best = max(best, difflib.SequenceMatcher(None, needle, c).ratio())
    return best


def line_chunks(md):
    lines = [l for l in md.splitlines() if l.strip()]
    pairs = [lines[i] + " " + lines[i + 1] for i in range(len(lines) - 1)]
    return lines + pairs


def parse_tables(md):
    tables, cur = [], []
    for line in md.splitlines():
        if line.strip().startswith("|"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if all(re.fullmatch(r":?-+:?", c) for c in cells):
                continue  # the |---|---| separator row
            cur.append(cells)
        elif cur:
            tables.append(cur)
            cur = []
    if cur:
        tables.append(cur)
    return tables


def score_element(el, md):
    t = el["type"]
    if t == "heading":
        heads = [l.lstrip("#") for l in md.splitlines() if l.lstrip().startswith("#")]
        return 1.0 if best_ratio(el["text"], heads) >= FUZZY else 0.0
    if t == "text":
        return 1.0 if best_ratio(el["text"], line_chunks(md)) >= FUZZY else 0.0
    if t == "formula":
        return 1.0 if best_ratio(el["latex"], line_chunks(md)) >= 0.8 else 0.0
    if t == "key_value":
        both = norm(el["key"]) + " " + norm(el["value"])
        return 1.0 if best_ratio(both, line_chunks(md)) >= FUZZY else 0.0
    if t == "image":
        has_marker = "![" in md or "<!-- image" in md.lower()
        words = [norm(w) for w in el.get("caption_keywords", [])]
        found = sum(1 for w in words if w and w in norm(md))
        ok = has_marker and (not words or found / len(words) >= 0.5)
        return 1.0 if ok else 0.0
    if t == "table":
        gt_cells = {norm(c) for row in el["cells"] for c in row if c.strip()}
        best = 0.0
        for tbl in parse_tables(md):
            out_cells = {norm(c) for row in tbl for c in row if c.strip()}
            if gt_cells:
                best = max(best, len(gt_cells & out_cells) / len(gt_cells))
        return best
    raise ValueError(f"Unknown element type: {t}")


def main():
    gts = sorted(GT_DIR.glob("*.json"))
    tools = sorted(p for p in OUT_DIR.iterdir() if p.is_dir())
    if not gts or not tools:
        print("Nothing to score: add ground_truth/*.json and outputs/<tool>/ folders.")
        return
    scores = {}   # (tool, type) -> list of scores
    details = []
    for tool in tools:
        limit_file = tool / "_max_page.txt"
        max_page = int(limit_file.read_text().strip()) if limit_file.exists() else None
        for gt_path in gts:
            gt = json.loads(gt_path.read_text(encoding="utf-8"))
            out_path = tool / (gt_path.stem + ".md")
            md = out_path.read_text(encoding="utf-8") if out_path.exists() else ""
            for el in gt["elements"]:
                if max_page and el.get("page", 1) > max_page:
                    continue  # this tool never saw that page
                s = score_element(el, md)
                scores.setdefault((tool.name, el["type"]), []).append(s)
                label = el.get("text") or el.get("latex") or el.get("key") or str(el.get("cells", ""))[:40]
                details.append([tool.name, gt_path.stem, el["type"], el.get("page", ""), label[:60], round(s, 2)])

    names = [t.name for t in tools]
    print(f"{'element':<12}" + "".join(f"{n:>14}" for n in names))
    summary = []
    for typ in TYPES:
        row = f"{typ:<12}"
        for n in names:
            vals = scores.get((n, typ), [])
            avg = sum(vals) / len(vals) if vals else None
            row += f"{('-' if avg is None else f'{avg:.2f} (n={len(vals)})'):>14}"
            summary.append([n, typ, len(vals), "" if avg is None else round(avg, 3)])
        print(row)
    with open(HERE / "results.csv", "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows([["tool", "element_type", "n", "score"]] + summary)
    with open(HERE / "details.csv", "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows([["tool", "doc", "type", "page", "element", "score"]] + details)
    print("\nWrote results.csv and details.csv")


if __name__ == "__main__":
    main()
