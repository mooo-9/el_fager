from pathlib import Path
from unittest.mock import patch, MagicMock
from core.agents.file_agent import FileAgent


class TestResolvePath:
    def test_returns_none_when_no_file_mentioned(self):
        agent = FileAgent()
        assert agent._resolve_path("what is the weather today") is None

    def test_finds_pdf_by_name_in_search_dirs(self, tmp_path, monkeypatch):
        import core.agents.file_agent as fa
        test_file = tmp_path / "thesis.pdf"
        test_file.write_bytes(b"%PDF-1.4")
        monkeypatch.setattr(fa, "_SEARCH_DIRS", [tmp_path])
        result = FileAgent()._resolve_path("summarize thesis.pdf")
        assert result == test_file

    def test_finds_docx_by_name_in_search_dirs(self, tmp_path, monkeypatch):
        import core.agents.file_agent as fa
        test_file = tmp_path / "report.docx"
        test_file.write_bytes(b"PK")
        monkeypatch.setattr(fa, "_SEARCH_DIRS", [tmp_path])
        result = FileAgent()._resolve_path("summarize this document report.docx")
        assert result == test_file

    def test_finds_txt_by_name_in_search_dirs(self, tmp_path, monkeypatch):
        import core.agents.file_agent as fa
        test_file = tmp_path / "notes.txt"
        test_file.write_text("hello", encoding="utf-8")
        monkeypatch.setattr(fa, "_SEARCH_DIRS", [tmp_path])
        result = FileAgent()._resolve_path("read notes.txt")
        assert result == test_file


class TestReadPdf:
    def test_returns_extracted_text(self, tmp_path):
        mock_page = MagicMock()
        mock_page.extract_text.return_value = "This is thesis content."
        mock_pdf = MagicMock()
        mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
        mock_pdf.__exit__ = MagicMock(return_value=False)
        mock_pdf.pages = [mock_page]
        with patch("pdfplumber.open", return_value=mock_pdf):
            result = FileAgent()._read_pdf(tmp_path / "test.pdf")
        assert "thesis content" in result

    def test_returns_empty_string_on_failure(self, tmp_path):
        with patch("pdfplumber.open", side_effect=Exception("corrupt")):
            result = FileAgent()._read_pdf(tmp_path / "bad.pdf")
        assert result == ""


class TestReadDocx:
    def test_returns_paragraph_text(self, tmp_path):
        mock_para = MagicMock()
        mock_para.text = "Contract clause 1."
        mock_doc = MagicMock()
        mock_doc.paragraphs = [mock_para]
        with patch("docx.Document", return_value=mock_doc):
            result = FileAgent()._read_docx(tmp_path / "contract.docx")
        assert "Contract clause 1." in result

    def test_returns_empty_string_on_failure(self, tmp_path):
        with patch("docx.Document", side_effect=Exception("bad file")):
            result = FileAgent()._read_docx(tmp_path / "bad.docx")
        assert result == ""


class TestReadText:
    def test_reads_plain_text_file(self, tmp_path):
        f = tmp_path / "notes.txt"
        f.write_text("Hello world", encoding="utf-8")
        result = FileAgent()._read_text(f)
        assert result == "Hello world"

    def test_returns_empty_string_on_missing_file(self, tmp_path):
        result = FileAgent()._read_text(tmp_path / "missing.txt")
        assert result == ""


class TestAnswer:
    def test_returns_haiku_answer(self, tmp_path):
        mock_resp = MagicMock()
        mock_resp.content = [MagicMock(text="Payment terms are Net 30.")]
        with patch("anthropic.Anthropic") as MockCl:
            MockCl.return_value.messages.create.return_value = mock_resp
            result = FileAgent()._answer(
                "what are the payment terms?",
                tmp_path / "contract.pdf",
                "Pay within 30 days of invoice.",
            )
        assert isinstance(result, str)
        assert len(result) > 0

    def test_fallback_on_api_failure(self, tmp_path):
        with patch("anthropic.Anthropic", side_effect=Exception("API down")):
            result = FileAgent()._answer(
                "summarize", tmp_path / "doc.pdf", "Short content here."
            )
        assert "Short content here" in result or "doc.pdf" in result


class TestRun:
    def test_returns_helpful_message_when_no_file_found(self):
        result = FileAgent().run("what does this say about payments?")
        assert isinstance(result, str)
        assert "file" in result.lower() or "filename" in result.lower()

    def test_run_with_pdf_routes_through_read_pdf(self, tmp_path, monkeypatch):
        import core.agents.file_agent as fa
        test_file = tmp_path / "invoice.pdf"
        test_file.write_bytes(b"%PDF")
        monkeypatch.setattr(fa, "_SEARCH_DIRS", [tmp_path])
        mock_resp = MagicMock()
        mock_resp.content = [MagicMock(text="Total amount is $500.")]
        with patch.object(FileAgent, "_read_pdf", return_value="Invoice total: $500"), \
             patch("anthropic.Anthropic") as MockCl:
            MockCl.return_value.messages.create.return_value = mock_resp
            result = FileAgent().run("what is the total in invoice.pdf?")
        assert isinstance(result, str)
        assert len(result) > 0
