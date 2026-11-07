from pathlib import Path
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Inches, Pt

md_path = Path(r"C:\Users\ripre\Documents\Trabajo de grado\articulo_trabajo_grado.md")
out_path = Path(r"C:\Users\ripre\Documents\Trabajo de grado\articulo_trabajo_grado.docx")

doc = Document()
for section in doc.sections:
    section.top_margin = Inches(0.75)
    section.bottom_margin = Inches(0.75)
    section.left_margin = Inches(0.9)
    section.right_margin = Inches(0.9)

style = doc.styles["Normal"]
style.font.name = "Times New Roman"
style.font.size = Pt(11)

for line in md_path.read_text(encoding="utf-8").splitlines():
    if not line.strip():
        doc.add_paragraph("")
        continue

    if line.startswith("# "):
        p = doc.add_paragraph()
        run = p.add_run(line[2:])
        run.bold = True
        run.font.name = "Times New Roman"
        run.font.size = Pt(16)
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        continue

    if line.startswith("## "):
        p = doc.add_paragraph()
        run = p.add_run(line[3:])
        run.bold = True
        run.font.name = "Times New Roman"
        run.font.size = Pt(12)
        p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        continue

    if line.startswith("|") or line.startswith("---"):
        # Skip raw markdown tables; they do not render well in the generated Word doc.
        continue

    p = doc.add_paragraph(line)
    p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY

doc.save(out_path)
print(f"Created {out_path}")
