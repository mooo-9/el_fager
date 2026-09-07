"""
PDF tools for El Fager.

Create PDFs from text, merge, split, compress, get info, and extract text.
Uses pypdf (already installed) and reportlab (installed this session).
"""

import os


def create_pdf(text: str, output_path: str, title: str = "") -> str:
    """Create a PDF from plain text. Handles long documents."""
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.enums import TA_RIGHT, TA_LEFT
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
        from reportlab.lib.units import cm
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont

        os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else ".", exist_ok=True)

        doc = SimpleDocTemplate(
            output_path,
            pagesize=A4,
            rightMargin=2 * cm,
            leftMargin=2 * cm,
            topMargin=2 * cm,
            bottomMargin=2 * cm,
            title=title or "El Fager Document",
        )

        styles = getSampleStyleSheet()
        body_style = ParagraphStyle(
            "body",
            parent=styles["Normal"],
            fontSize=12,
            leading=18,
            wordWrap="RTL",
        )

        story = []
        if title:
            title_style = ParagraphStyle(
                "title",
                parent=styles["Title"],
                fontSize=16,
                spaceAfter=12,
            )
            story.append(Paragraph(title, title_style))
            story.append(Spacer(1, 0.5 * cm))

        for para in text.split("\n\n"):
            para = para.strip()
            if para:
                safe_para = para.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                story.append(Paragraph(safe_para, body_style))
                story.append(Spacer(1, 0.3 * cm))

        doc.build(story)
        size_kb = os.path.getsize(output_path) // 1024
        return f"PDF created: {output_path} ({size_kb} KB, {len(story)} elements)."
    except Exception as e:
        return f"[create_pdf failed: {e}]"


def merge_pdfs(input_paths: list, output_path: str) -> str:
    """Merge multiple PDF files into one."""
    try:
        from pypdf import PdfWriter

        writer = PdfWriter()
        page_count = 0
        for path in input_paths:
            if not os.path.exists(path):
                return f"[merge_pdfs failed: file not found: {path}]"
            from pypdf import PdfReader
            reader = PdfReader(path)
            for page in reader.pages:
                writer.add_page(page)
                page_count += 1

        os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else ".", exist_ok=True)
        with open(output_path, "wb") as f:
            writer.write(f)

        size_kb = os.path.getsize(output_path) // 1024
        return f"Merged {len(input_paths)} PDFs into {output_path} ({page_count} pages, {size_kb} KB)."
    except Exception as e:
        return f"[merge_pdfs failed: {e}]"


def split_pdf(input_path: str, pages: str, output_path: str) -> str:
    """Extract specific pages from a PDF. pages format: '1-3,5,7-9' (1-indexed)."""
    try:
        from pypdf import PdfReader, PdfWriter

        if not os.path.exists(input_path):
            return f"[split_pdf failed: file not found: {input_path}]"

        reader = PdfReader(input_path)
        total = len(reader.pages)

        # Parse page range string
        page_indices = []
        for part in pages.split(","):
            part = part.strip()
            if "-" in part:
                start, end = part.split("-", 1)
                page_indices.extend(range(int(start) - 1, int(end)))
            else:
                page_indices.append(int(part) - 1)

        # Validate
        invalid = [i + 1 for i in page_indices if i < 0 or i >= total]
        if invalid:
            return f"[split_pdf failed: page(s) {invalid} out of range (PDF has {total} pages)]"

        writer = PdfWriter()
        for i in page_indices:
            writer.add_page(reader.pages[i])

        os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else ".", exist_ok=True)
        with open(output_path, "wb") as f:
            writer.write(f)

        size_kb = os.path.getsize(output_path) // 1024
        return f"Extracted {len(page_indices)} pages from {input_path} -> {output_path} ({size_kb} KB)."
    except Exception as e:
        return f"[split_pdf failed: {e}]"


def compress_pdf(input_path: str, output_path: str = None) -> str:
    """Reduce PDF file size by compressing content streams."""
    try:
        from pypdf import PdfReader, PdfWriter

        if not os.path.exists(input_path):
            return f"[compress_pdf failed: file not found: {input_path}]"

        original_size = os.path.getsize(input_path)
        if output_path is None:
            base, ext = os.path.splitext(input_path)
            output_path = f"{base}_compressed{ext}"

        reader = PdfReader(input_path)
        writer = PdfWriter()
        for page in reader.pages:
            writer.add_page(page)
        for page in writer.pages:
            page.compress_content_streams()

        os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else ".", exist_ok=True)
        with open(output_path, "wb") as f:
            writer.write(f)

        new_size = os.path.getsize(output_path)
        savings_pct = (1 - new_size / original_size) * 100 if original_size else 0
        orig_kb = original_size // 1024
        new_kb = new_size // 1024
        return (
            f"Compressed: {input_path} ({orig_kb} KB) -> {output_path} ({new_kb} KB), "
            f"{savings_pct:.0f}% smaller."
        )
    except Exception as e:
        return f"[compress_pdf failed: {e}]"


def pdf_info(path: str) -> str:
    """Page count, file size, and metadata for a PDF."""
    try:
        from pypdf import PdfReader

        if not os.path.exists(path):
            return f"[pdf_info failed: file not found: {path}]"

        reader = PdfReader(path)
        page_count = len(reader.pages)
        size_kb = os.path.getsize(path) // 1024
        meta = reader.metadata or {}

        info_lines = [
            f"File: {path}",
            f"Pages: {page_count}",
            f"Size: {size_kb} KB",
        ]
        if meta.get("/Title"):
            info_lines.append(f"Title: {meta['/Title']}")
        if meta.get("/Author"):
            info_lines.append(f"Author: {meta['/Author']}")
        if meta.get("/CreationDate"):
            info_lines.append(f"Created: {meta['/CreationDate']}")
        if reader.is_encrypted:
            info_lines.append("Encrypted: yes")

        return "\n".join(info_lines)
    except Exception as e:
        return f"[pdf_info failed: {e}]"


def pdf_to_text(path: str, pages: str = None) -> str:
    """Extract text from a PDF. pages: '1-3,5' (1-indexed, optional)."""
    try:
        from pypdf import PdfReader

        if not os.path.exists(path):
            return f"[pdf_to_text failed: file not found: {path}]"

        reader = PdfReader(path)
        total = len(reader.pages)

        if pages:
            page_indices = []
            for part in pages.split(","):
                part = part.strip()
                if "-" in part:
                    start, end = part.split("-", 1)
                    page_indices.extend(range(int(start) - 1, int(end)))
                else:
                    page_indices.append(int(part) - 1)
            page_indices = [i for i in page_indices if 0 <= i < total]
        else:
            page_indices = list(range(total))

        parts = []
        for i in page_indices:
            text = reader.pages[i].extract_text() or ""
            if text.strip():
                parts.append(f"[Page {i + 1}]\n{text.strip()}")

        extracted = "\n\n".join(parts)
        if not extracted:
            return f"[No text found in {path} — may be a scanned image PDF]"
        if len(extracted) > 8000:
            extracted = extracted[:8000] + f"\n\n...[truncated — {len(extracted)} chars total]"
        return extracted
    except Exception as e:
        return f"[pdf_to_text failed: {e}]"
