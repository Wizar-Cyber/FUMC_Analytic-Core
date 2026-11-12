"""Convierte un Markdown simple (encabezados, párrafos, listas, tablas, **negrita**, *cursiva*, `código`)
a .docx reutilizando los estilos de un .docx existente como plantilla.

Uso: python scripts/md_to_docx.py <entrada.md> <plantilla_y_salida.docx>
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import docx
from docx.shared import Pt

INLINE = re.compile(r"(\*\*[^*]+\*\*|`[^`]+`|\*[^*\s][^*]*\*)")


def add_inline(paragraph, text: str, bold_all: bool = False) -> None:
    for part in INLINE.split(text):
        if not part:
            continue
        if part.startswith("**") and part.endswith("**") and len(part) > 4:
            run = paragraph.add_run(part[2:-2])
            run.bold = True
        elif part.startswith("`") and part.endswith("`") and len(part) > 2:
            run = paragraph.add_run(part[1:-1])
            run.font.name = "Consolas"
            run.font.size = Pt(9.5)
        elif part.startswith("*") and part.endswith("*") and len(part) > 2:
            run = paragraph.add_run(part[1:-1])
            run.italic = True
        else:
            run = paragraph.add_run(part)
        if bold_all:
            run.bold = True


def split_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def convert(md_path: Path, docx_path: Path) -> None:
    document = docx.Document(str(docx_path))
    table_style = document.tables[0].style if document.tables else None
    body = document.element.body
    for element in list(body):
        if not element.tag.endswith("sectPr"):
            body.remove(element)

    lines = md_path.read_text(encoding="utf-8").splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if not stripped:
            i += 1
            continue
        if stripped.startswith("|") and i + 1 < len(lines) and re.match(r"^\|[\s:|-]+\|$", lines[i + 1].strip()):
            header = split_row(stripped)
            i += 2
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append(split_row(lines[i]))
                i += 1
            table = document.add_table(rows=1 + len(rows), cols=len(header))
            if table_style is not None:
                table.style = table_style
            for c, text in enumerate(header):
                cell = table.rows[0].cells[c]
                cell.paragraphs[0].text = ""
                add_inline(cell.paragraphs[0], text, bold_all=True)
            for r, row in enumerate(rows, start=1):
                for c in range(len(header)):
                    cell = table.rows[r].cells[c]
                    cell.paragraphs[0].text = ""
                    add_inline(cell.paragraphs[0], row[c] if c < len(row) else "")
            for row in table.rows:
                for cell in row.cells:
                    for paragraph in cell.paragraphs:
                        for run in paragraph.runs:
                            run.font.size = Pt(9)
            document.add_paragraph()
            continue
        if stripped.startswith("### "):
            document.add_heading(stripped[4:].strip(), level=2)
        elif stripped.startswith("## "):
            document.add_heading(stripped[3:].strip(), level=1)
        elif stripped.startswith("# "):
            paragraph = document.add_paragraph()
            add_inline(paragraph, stripped[2:].strip(), bold_all=True)
        elif re.match(r"^[-*] ", stripped):
            paragraph = document.add_paragraph(style="List Bullet")
            add_inline(paragraph, stripped[2:].strip())
        elif re.match(r"^\d+\. ", stripped):
            paragraph = document.add_paragraph(style="List Number")
            add_inline(paragraph, re.sub(r"^\d+\.\s+", "", stripped))
        else:
            paragraph = document.add_paragraph()
            add_inline(paragraph, stripped.rstrip(" "))
        i += 1
    document.save(str(docx_path))


if __name__ == "__main__":
    convert(Path(sys.argv[1]), Path(sys.argv[2]))
