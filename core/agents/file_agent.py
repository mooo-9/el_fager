"""
FileAgent -- reads and understands documents: PDFs, Word files, plain text, images.
Extracts content and answers questions about it using Claude Haiku.
"""
import re
from pathlib import Path

from core.agents.base_agent import BaseAgent

_SEARCH_DIRS = [
    Path("C:/Users/Mohab1/OneDrive/Desktop"),
    Path("C:/Users/Mohab1/OneDrive/Documents"),
    Path("C:/Users/Mohab1/Downloads"),
    Path("."),
]

_MAX_CONTENT_CHARS = 6000


class FileAgent(BaseAgent):
    @property
    def name(self) -> str:
        return "file"

    @property
    def description(self) -> str:
        return "Document intelligence -- reads PDFs, Word docs, images and answers questions."

    def run(self, task: str) -> str:
        path = self._resolve_path(task)
        if path is None:
            return (
                "No file found. Mention the filename or path, e.g. "
                "'summarize thesis.pdf' or 'what does contract.docx say about payment terms?'"
            )

        content = self._extract_content(path)
        if not content:
            return (
                f"Could not read content from {path.name}. "
                "File may be empty, encrypted, or an unsupported format."
            )

        return self._answer(task, path, content)

    def _resolve_path(self, task: str) -> Path | None:
        # 1. Quoted path -- highest confidence
        quoted = re.search(
            r'["\']([^"\']+\.(?:pdf|docx|doc|xlsx|txt|csv|md|png|jpg|jpeg))["\']',
            task,
            re.IGNORECASE,
        )
        if quoted:
            p = Path(quoted.group(1))
            if p.exists():
                return p

        # 2. Unquoted filename with known extension
        ext_match = re.search(
            r'(\S+\.(?:pdf|docx|doc|xlsx|txt|csv|md|png|jpg|jpeg))',
            task,
            re.IGNORECASE,
        )
        if ext_match:
            candidate = ext_match.group(1)
            p = Path(candidate)
            if p.exists():
                return p
            # Search in common directories by filename only
            name = Path(candidate).name
            for d in _SEARCH_DIRS:
                found = d / name
                if found.exists():
                    return found

        return None

    def _extract_content(self, path: Path) -> str:
        suffix = path.suffix.lower()
        if suffix == ".pdf":
            return self._read_pdf(path)
        if suffix in {".docx", ".doc"}:
            return self._read_docx(path)
        if suffix in {".txt", ".csv", ".md"}:
            return self._read_text(path)
        if suffix in {".png", ".jpg", ".jpeg"}:
            return self._ocr_image(path)
        return ""

    def _read_pdf(self, path: Path) -> str:
        try:
            import fitz  # pymupdf
            texts = []
            with fitz.open(path) as pdf:
                for page in pdf.pages(stop=10):
                    t = page.get_text()
                    if t:
                        texts.append(t)
            return "\n".join(texts)[:_MAX_CONTENT_CHARS]
        except Exception:
            return ""

    def _read_docx(self, path: Path) -> str:
        # python-docx supports .docx only; legacy .doc raises and returns ""
        try:
            from docx import Document
            doc = Document(str(path))
            text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
            return text[:_MAX_CONTENT_CHARS]
        except Exception:
            return ""

    def _read_text(self, path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8", errors="replace")[:_MAX_CONTENT_CHARS]
        except Exception:
            return ""

    def _ocr_image(self, path: Path) -> str:
        try:
            import pytesseract
            from PIL import Image
            img = Image.open(path)
            return pytesseract.image_to_string(img)[:_MAX_CONTENT_CHARS]
        except Exception:
            return ""

    def _answer(self, task: str, path: Path, content: str) -> str:
        prompt = (
            "You are El Fager's document assistant. Answer the user's question "
            "based strictly on the document content below. Be specific and concise. "
            "No emojis. Plain English only.\n\n"
            f"File: {path.name}\n\n"
            f"Content:\n{content}\n\n"
            f"Question: {task}"
        )
        try:
            import anthropic
            client = anthropic.Anthropic()
            from core.telemetry import instrument_client
            instrument_client(client, "file_agent")
            resp = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=400,
                messages=[{"role": "user", "content": prompt}],
            )
            return resp.content[0].text.strip()
        except Exception:
            return f"Could not get an AI answer for {path.name}. Please try again."
