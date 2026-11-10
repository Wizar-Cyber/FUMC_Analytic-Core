from __future__ import annotations

import re
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Inches, Pt


ROOT = Path(__file__).resolve().parents[1]
ARTICLES = (
    (ROOT / "articulo_trabajo_grado.md", ROOT / "articulo_trabajo_grado.docx"),
    (
        ROOT / "entregables" / "articulo_trabajo_grado.md",
        ROOT / "entregables" / "articulo_trabajo_grado.docx",
    ),
)


def _clean_inline(text: str) -> str:
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    return text.replace("**", "").replace("`", "")


def _table_cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _render_article(source: Path, destination: Path) -> None:
    doc = Document()
    for section in doc.sections:
        section.top_margin = Inches(0.75)
        section.bottom_margin = Inches(0.75)
        section.left_margin = Inches(0.9)
        section.right_margin = Inches(0.9)

    normal = doc.styles["Normal"]
    normal.font.name = "Times New Roman"
    normal.font.size = Pt(11)

    lines = source.read_text(encoding="utf-8").splitlines()
    index = 0
    in_code = False
    skip_mermaid = False
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()

        if stripped.startswith("```"):
            if not in_code:
                skip_mermaid = stripped.lower().startswith("```mermaid")
                in_code = True
            else:
                in_code = False
                skip_mermaid = False
            index += 1
            continue
        if in_code:
            if not skip_mermaid:
                paragraph = doc.add_paragraph()
                run = paragraph.add_run(line)
                run.font.name = "Consolas"
                run.font.size = Pt(9)
            index += 1
            continue

        if not stripped:
            index += 1
            continue

        if stripped.startswith("|"):
            rows = []
            while index < len(lines) and lines[index].strip().startswith("|"):
                row = _table_cells(lines[index])
                if not all(re.fullmatch(r":?-{3,}:?", cell) for cell in row):
                    rows.append(row)
                index += 1
            if rows:
                width = max(len(row) for row in rows)
                table = doc.add_table(rows=0, cols=width)
                table.style = "Light Shading Accent 1"
                for values in rows:
                    cells = table.add_row().cells
                    for column, value in enumerate(values):
                        cells[column].text = _clean_inline(value)
                doc.add_paragraph("")
            continue

        heading = re.match(r"^(#{1,4})\s+(.*)$", stripped)
        if heading:
            level = len(heading.group(1))
            title = _clean_inline(heading.group(2))
            if level == 1:
                paragraph = doc.add_paragraph()
                paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
                run = paragraph.add_run(title)
                run.bold = True
                run.font.name = "Times New Roman"
                run.font.size = Pt(16)
            else:
                paragraph = doc.add_heading(title, level=min(level - 1, 3))
                paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
            index += 1
            continue

        if stripped.startswith("- "):
            doc.add_paragraph(_clean_inline(stripped[2:]), style="List Bullet")
            index += 1
            continue

        numbered = re.match(r"^\d+\.\s+(.*)$", stripped)
        if numbered:
            doc.add_paragraph(_clean_inline(numbered.group(1)), style="List Number")
            index += 1
            continue

        paragraph = doc.add_paragraph(_clean_inline(stripped.lstrip("> ")))
        paragraph.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        index += 1

    destination.parent.mkdir(parents=True, exist_ok=True)
    doc.save(destination)


if __name__ == "__main__":
    for article_path, docx_path in ARTICLES:
        _render_article(article_path, docx_path)
        print(f"Created {docx_path}")
