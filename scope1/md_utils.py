"""Small helpers shared by the open-source extractors."""


def rows_to_markdown(rows):
    """Turn a list of rows (list of cell strings) into a Markdown pipe table."""
    cleaned = []
    for row in rows or []:
        cells = [str(c if c is not None else "").replace("\n", " ").replace("|", "\\|").strip() for c in row]
        if any(cells):
            cleaned.append(cells)
    if not cleaned:
        return ""
    width = max(len(r) for r in cleaned)
    cleaned = [r + [""] * (width - len(r)) for r in cleaned]
    lines = ["| " + " | ".join(cleaned[0]) + " |",
             "| " + " | ".join("---" for _ in range(width)) + " |"]
    lines += ["| " + " | ".join(r) + " |" for r in cleaned[1:]]
    return "\n".join(lines)
