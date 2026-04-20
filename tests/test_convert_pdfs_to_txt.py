"""Tests for scripts/convert_pdfs_to_txt.py - PDF text extraction.

Note: These tests are skipped if pypdf is not installed (optional dependency).
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

# Mock pypdf before import if not available
try:
    import pypdf
    PYPDF_AVAILABLE = True
except ImportError:
    PYPDF_AVAILABLE = False
    # Create mock module
    sys.modules['pypdf'] = Mock()

# Skip all tests if pypdf is not available
pytestmark = pytest.mark.skipif(not PYPDF_AVAILABLE, reason="pypdf not installed (optional dependency)")

# Add scripts directory to path for import
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

# Only import if pypdf is available, otherwise tests will be skipped anyway
if PYPDF_AVAILABLE:
    import convert_pdfs_to_txt
else:
    convert_pdfs_to_txt = None


class TestExtractWithPypdf:
    """Test pypdf extraction function."""

    def test_extract_single_page_pdf(self, tmp_path):
        """Extract text from a single-page PDF."""
        pdf_path = tmp_path / "test.pdf"

        with patch("convert_pdfs_to_txt.pypdf.PdfReader") as mock_reader:
            mock_page = MagicMock()
            mock_page.extract_text.return_value = "Page 1 content"
            mock_reader.return_value.pages = [mock_page]

            result = convert_pdfs_to_txt.extract_with_pypdf(pdf_path)

            assert result == "Page 1 content"
            mock_reader.assert_called_once_with(str(pdf_path))

    def test_extract_multi_page_pdf(self, tmp_path):
        """Extract text from a multi-page PDF."""
        pdf_path = tmp_path / "multipage.pdf"

        with patch("convert_pdfs_to_txt.pypdf.PdfReader") as mock_reader:
            mock_page1 = MagicMock()
            mock_page1.extract_text.return_value = "Page 1"
            mock_page2 = MagicMock()
            mock_page2.extract_text.return_value = "Page 2"
            mock_reader.return_value.pages = [mock_page1, mock_page2]

            result = convert_pdfs_to_txt.extract_with_pypdf(pdf_path)

            assert result == "Page 1\n\nPage 2"

    def test_extract_handles_extraction_error(self, tmp_path):
        """Handle extraction errors gracefully by returning empty string for that page."""
        pdf_path = tmp_path / "error.pdf"

        with patch("convert_pdfs_to_txt.pypdf.PdfReader") as mock_reader:
            mock_page1 = MagicMock()
            mock_page1.extract_text.return_value = "Page 1"
            mock_page2 = MagicMock()
            mock_page2.extract_text.side_effect = Exception("Extraction failed")
            mock_reader.return_value.pages = [mock_page1, mock_page2]

            result = convert_pdfs_to_txt.extract_with_pypdf(pdf_path)

            assert result == "Page 1\n\n"

    def test_extract_empty_page(self, tmp_path):
        """Handle pages that return None or empty text."""
        pdf_path = tmp_path / "empty.pdf"

        with patch("convert_pdfs_to_txt.pypdf.PdfReader") as mock_reader:
            mock_page = MagicMock()
            mock_page.extract_text.return_value = None
            mock_reader.return_value.pages = [mock_page]

            result = convert_pdfs_to_txt.extract_with_pypdf(pdf_path)

            assert result == ""


class TestExtractWithPdfminer:
    """Test pdfminer extraction function."""

    def test_extract_with_pdfminer(self, tmp_path):
        """Extract text using pdfminer."""
        pdf_path = tmp_path / "test.pdf"

        with patch("convert_pdfs_to_txt.extract_text") as mock_extract:
            mock_extract.return_value = "Extracted text via pdfminer"

            result = convert_pdfs_to_txt.extract_with_pdfminer(pdf_path)

            assert result == "Extracted text via pdfminer"
            mock_extract.assert_called_once_with(str(pdf_path))

    def test_extract_with_pdfminer_returns_empty_on_none(self, tmp_path):
        """Handle None return from pdfminer."""
        pdf_path = tmp_path / "test.pdf"

        with patch("convert_pdfs_to_txt.extract_text") as mock_extract:
            mock_extract.return_value = None

            result = convert_pdfs_to_txt.extract_with_pdfminer(pdf_path)

            assert result == ""


class TestScanPdfs:
    """Test PDF file scanning."""

    def test_scan_finds_pdf_files(self, tmp_path, monkeypatch):
        """Scan should find PDF files in the repository."""
        # Create mock directory structure
        (tmp_path / "data").mkdir()
        (tmp_path / "data" / "raw").mkdir()
        (tmp_path / "data" / "raw" / "doc1.pdf").touch()
        (tmp_path / "data" / "raw" / "doc2.pdf").touch()
        (tmp_path / "other.txt").touch()

        monkeypatch.setattr(convert_pdfs_to_txt, "REPO_ROOT", tmp_path)

        result = convert_pdfs_to_txt.scan_pdfs()

        assert len(result) == 2
        assert all(p.suffix.lower() == ".pdf" for p in result)

    def test_scan_excludes_ignored_directories(self, tmp_path, monkeypatch):
        """Scan should exclude .git, __pycache__, .pytest_cache directories."""
        (tmp_path / ".git").mkdir()
        (tmp_path / ".git" / "ignored.pdf").touch()
        (tmp_path / "__pycache__").mkdir()
        (tmp_path / "__pycache__" / "ignored.pdf").touch()
        (tmp_path / "valid.pdf").touch()

        monkeypatch.setattr(convert_pdfs_to_txt, "REPO_ROOT", tmp_path)

        result = convert_pdfs_to_txt.scan_pdfs()

        assert len(result) == 1
        assert result[0].name == "valid.pdf"

    def test_scan_returns_sorted_results(self, tmp_path, monkeypatch):
        """Scan results should be sorted by relative path."""
        (tmp_path / "z.pdf").touch()
        (tmp_path / "a.pdf").touch()
        (tmp_path / "m.pdf").touch()

        monkeypatch.setattr(convert_pdfs_to_txt, "REPO_ROOT", tmp_path)

        result = convert_pdfs_to_txt.scan_pdfs()

        names = [p.name for p in result]
        assert names == ["a.pdf", "m.pdf", "z.pdf"]

    def test_scan_case_insensitive_pdf_extension(self, tmp_path, monkeypatch):
        """Scan should find .PDF, .pdf, .Pdf files."""
        (tmp_path / "file1.pdf").touch()
        (tmp_path / "file2.PDF").touch()
        (tmp_path / "file3.Pdf").touch()

        monkeypatch.setattr(convert_pdfs_to_txt, "REPO_ROOT", tmp_path)

        result = convert_pdfs_to_txt.scan_pdfs()

        assert len(result) == 3


class TestMain:
    """Test main conversion workflow."""

    def test_main_converts_pdfs_without_sidecar(self, tmp_path, monkeypatch, capsys):
        """Main should convert PDFs that don't have sidecar files."""
        pdf_file = tmp_path / "test.pdf"
        pdf_file.touch()

        monkeypatch.setattr(convert_pdfs_to_txt, "REPO_ROOT", tmp_path)
        monkeypatch.setattr(sys, "argv", ["convert_pdfs_to_txt.py"])

        with patch("convert_pdfs_to_txt.extract_with_pypdf") as mock_extract:
            mock_extract.return_value = "Extracted content"

            convert_pdfs_to_txt.main()

            sidecar = tmp_path / "test.pdf.txt"
            assert sidecar.exists()
            assert sidecar.read_text() == "Extracted content"

        captured = capsys.readouterr()
        assert "converted=1" in captured.out

    def test_main_skips_existing_sidecar_without_force(self, tmp_path, monkeypatch, capsys):
        """Main should skip PDFs with existing sidecar files unless --force."""
        pdf_file = tmp_path / "test.pdf"
        pdf_file.touch()
        sidecar = tmp_path / "test.pdf.txt"
        sidecar.write_text("Existing content")

        monkeypatch.setattr(convert_pdfs_to_txt, "REPO_ROOT", tmp_path)
        monkeypatch.setattr(sys, "argv", ["convert_pdfs_to_txt.py"])

        convert_pdfs_to_txt.main()

        assert sidecar.read_text() == "Existing content"
        captured = capsys.readouterr()
        assert "skipped=1" in captured.out

    def test_main_overwrites_with_force_flag(self, tmp_path, monkeypatch, capsys):
        """Main with --force should overwrite existing sidecar files."""
        pdf_file = tmp_path / "test.pdf"
        pdf_file.touch()
        sidecar = tmp_path / "test.pdf.txt"
        sidecar.write_text("Old content")

        monkeypatch.setattr(convert_pdfs_to_txt, "REPO_ROOT", tmp_path)
        monkeypatch.setattr(sys, "argv", ["convert_pdfs_to_txt.py", "--force"])

        with patch("convert_pdfs_to_txt.extract_with_pypdf") as mock_extract:
            mock_extract.return_value = "New content"

            convert_pdfs_to_txt.main()

            assert sidecar.read_text() == "New content"

        captured = capsys.readouterr()
        assert "converted=1" in captured.out

    def test_main_respects_limit_flag(self, tmp_path, monkeypatch, capsys):
        """Main with --limit should only convert N PDFs."""
        for i in range(5):
            (tmp_path / f"test{i}.pdf").touch()

        monkeypatch.setattr(convert_pdfs_to_txt, "REPO_ROOT", tmp_path)
        monkeypatch.setattr(sys, "argv", ["convert_pdfs_to_txt.py", "--limit", "2"])

        with patch("convert_pdfs_to_txt.extract_with_pypdf") as mock_extract:
            mock_extract.return_value = "Content"

            convert_pdfs_to_txt.main()

        captured = capsys.readouterr()
        assert "converted=2" in captured.out

    def test_main_fallback_to_pdfminer_on_pypdf_failure(self, tmp_path, monkeypatch, capsys):
        """Main should fallback to pdfminer if pypdf fails."""
        pdf_file = tmp_path / "test.pdf"
        pdf_file.touch()

        monkeypatch.setattr(convert_pdfs_to_txt, "REPO_ROOT", tmp_path)
        monkeypatch.setattr(sys, "argv", ["convert_pdfs_to_txt.py"])

        with patch("convert_pdfs_to_txt.extract_with_pypdf") as mock_pypdf, \
             patch("convert_pdfs_to_txt.extract_with_pdfminer") as mock_pdfminer:
            mock_pypdf.side_effect = Exception("pypdf failed")
            mock_pdfminer.return_value = "Fallback content"

            convert_pdfs_to_txt.main()

            sidecar = tmp_path / "test.pdf.txt"
            assert sidecar.exists()
            assert sidecar.read_text() == "Fallback content"

    def test_main_counts_failed_extractions(self, tmp_path, monkeypatch, capsys):
        """Main should count PDFs that fail extraction."""
        pdf_file = tmp_path / "test.pdf"
        pdf_file.touch()

        monkeypatch.setattr(convert_pdfs_to_txt, "REPO_ROOT", tmp_path)
        monkeypatch.setattr(sys, "argv", ["convert_pdfs_to_txt.py"])

        with patch("convert_pdfs_to_txt.extract_with_pypdf") as mock_pypdf, \
             patch("convert_pdfs_to_txt.extract_with_pdfminer") as mock_pdfminer:
            mock_pypdf.side_effect = Exception("Failed")
            mock_pdfminer.side_effect = Exception("Failed")

            convert_pdfs_to_txt.main()

        captured = capsys.readouterr()
        assert "failed=1" in captured.out

    def test_main_skips_empty_extraction(self, tmp_path, monkeypatch, capsys):
        """Main should count as failed if extraction returns only whitespace."""
        pdf_file = tmp_path / "test.pdf"
        pdf_file.touch()

        monkeypatch.setattr(convert_pdfs_to_txt, "REPO_ROOT", tmp_path)
        monkeypatch.setattr(sys, "argv", ["convert_pdfs_to_txt.py"])

        with patch("convert_pdfs_to_txt.extract_with_pypdf") as mock_extract:
            mock_extract.return_value = "   \n\n  "

            convert_pdfs_to_txt.main()

            sidecar = tmp_path / "test.pdf.txt"
            assert not sidecar.exists()

        captured = capsys.readouterr()
        assert "failed=1" in captured.out
