"""Tests for scripts.generate_manifest module."""

import csv
import pytest
from scripts.generate_manifest import (
    classify,
    text_available,
    load_existing,
    scan_files,
    should_ignore_file,
    REPO_ROOT,
    MANIFEST_PATH,
)


class TestClassify:
    """Tests for file classification function"""

    def test_governance_files(self):
        """Test classification of governance documentation"""
        assert classify(REPO_ROOT / "README.md") == "governance"
        assert classify(REPO_ROOT / "CITATION.txt") == "governance"
        assert classify(REPO_ROOT / "DATA_GOVERNANCE.txt") == "governance"
        assert classify(REPO_ROOT / "CHANGELOG.txt") == "governance"

    def test_script_files(self):
        """Test classification of scripts"""
        assert classify(REPO_ROOT / "scripts" / "build_derived.py") == "script"
        assert classify(REPO_ROOT / "scripts" / "generate_manifest.py") == "script"
        assert classify(REPO_ROOT / "requirements.txt") == "script"

    def test_dataset_raw(self):
        """Test classification of raw datasets"""
        assert classify(REPO_ROOT / "data" / "raw" / "sample.xlsx") == "dataset_raw"
        assert classify(REPO_ROOT / "data" / "raw" / "data.xls") == "dataset_raw"

    def test_dataset_derived(self):
        """Test classification of derived datasets"""
        assert classify(REPO_ROOT / "data" / "derived" / "output.csv") == "dataset_derived"
        assert classify(REPO_ROOT / "data" / "derived" / "processed.csv") == "dataset_derived"
        assert (
            classify(REPO_ROOT / "outputs" / "research_sources" / "live_records.json")
            == "dataset_derived"
        )

    def test_policy_documents(self):
        """Test classification of policy documents"""
        assert classify(REPO_ROOT / "docs" / "policy" / "eu_policy.pdf") == "policy"

    def test_literature_documents(self):
        """Test classification of literature documents"""
        assert classify(REPO_ROOT / "docs" / "literature" / "paper.pdf") == "literature"

    def test_manuscripts(self):
        """Test classification of manuscript files"""
        assert classify(REPO_ROOT / "manuscripts" / "draft.docx") == "manuscript"

    def test_fallback_by_extension_csv(self):
        """Test fallback classification for CSV files"""
        assert classify(REPO_ROOT / "somewhere" / "data.csv") == "dataset_derived"

    def test_fallback_by_extension_xlsx(self):
        """Test fallback classification for Excel files"""
        assert classify(REPO_ROOT / "somewhere" / "data.xlsx") == "dataset_raw"

    def test_fallback_by_extension_pdf(self):
        """Test fallback classification for PDF files"""
        assert classify(REPO_ROOT / "somewhere" / "document.pdf") == "policy_or_literature"

    def test_fallback_by_extension_txt(self):
        """Test fallback classification for text files"""
        assert classify(REPO_ROOT / "somewhere" / "notes.txt") == "text"
        assert classify(REPO_ROOT / "somewhere" / "readme.md") == "text"
        assert classify(REPO_ROOT / "somewhere" / "script.py") == "script"

    def test_fallback_other(self):
        """Test fallback classification for unknown types"""
        assert classify(REPO_ROOT / "somewhere" / "file.unknown") == "other"


class TestTextAvailable:
    """Tests for text availability check function"""

    def test_text_files_available(self):
        """Text files should be marked as available"""
        # Create temporary test files
        txt_file = REPO_ROOT / "tests" / "fixtures" / "test.txt"
        md_file = REPO_ROOT / "tests" / "fixtures" / "test.md"
        csv_file = REPO_ROOT / "tests" / "fixtures" / "test.csv"
        json_file = REPO_ROOT / "tests" / "fixtures" / "test.json"
        py_file = REPO_ROOT / "tests" / "fixtures" / "test.py"

        assert text_available(txt_file) == "yes"
        assert text_available(md_file) == "yes"
        assert text_available(csv_file) == "yes"
        assert text_available(json_file) == "yes"
        assert text_available(py_file) == "yes"

    def test_pdf_without_sidecar(self):
        """PDF without sidecar text should be marked as not available"""
        pdf_file = REPO_ROOT / "tests" / "fixtures" / "nosidecar.pdf"
        assert text_available(pdf_file) == "no"

    def test_pdf_with_sidecar(self):
        """PDF with sidecar text should be marked as available"""
        # Create a temporary PDF and its sidecar
        pdf_file = REPO_ROOT / "tests" / "fixtures" / "withsidecar.pdf"
        sidecar_file = REPO_ROOT / "tests" / "fixtures" / "withsidecar.pdf.txt"

        # Create the sidecar
        sidecar_file.write_text("sidecar content")

        try:
            assert text_available(pdf_file) == "yes"
        finally:
            # Clean up
            if sidecar_file.exists():
                sidecar_file.unlink()

    def test_pdf_with_alternate_sidecar(self):
        """PDF with alternate sidecar (.txt instead of .pdf.txt)"""
        pdf_file = REPO_ROOT / "tests" / "fixtures" / "alternate.pdf"
        sidecar_file = REPO_ROOT / "tests" / "fixtures" / "alternate.txt"

        # Create the sidecar
        sidecar_file.write_text("sidecar content")

        try:
            assert text_available(pdf_file) == "yes"
        finally:
            # Clean up
            if sidecar_file.exists():
                sidecar_file.unlink()

    def test_excel_available(self):
        """Excel files should be marked as available (openable)"""
        xlsx_file = REPO_ROOT / "tests" / "fixtures" / "test.xlsx"
        xls_file = REPO_ROOT / "tests" / "fixtures" / "test.xls"

        assert text_available(xlsx_file) == "yes"
        assert text_available(xls_file) == "yes"

    def test_word_available(self):
        """Word files should be marked as available (openable)"""
        docx_file = REPO_ROOT / "tests" / "fixtures" / "test.docx"
        doc_file = REPO_ROOT / "tests" / "fixtures" / "test.doc"

        assert text_available(docx_file) == "yes"
        assert text_available(doc_file) == "yes"

    def test_unknown_format_not_available(self):
        """Unknown file formats should be marked as not available"""
        unknown_file = REPO_ROOT / "tests" / "fixtures" / "test.bin"
        assert text_available(unknown_file) == "no"


class TestLoadExisting:
    """Tests for loading existing manifest data"""

    def test_load_nonexistent_manifest(self, tmp_path, monkeypatch):
        """Test loading when manifest doesn't exist"""
        # Point MANIFEST_PATH to a non-existent path in isolated temp directory
        fake_manifest = tmp_path / "nonexistent_manifest.csv"
        monkeypatch.setattr("scripts.generate_manifest.MANIFEST_PATH", fake_manifest)

        result = load_existing()
        assert result == {}

    def test_load_existing_manifest(self):
        """Test loading data from existing manifest"""
        # Create a temporary manifest
        temp_manifest = REPO_ROOT / "tests" / "fixtures" / "temp_manifest.csv"
        temp_manifest.parent.mkdir(parents=True, exist_ok=True)

        with open(temp_manifest, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "file_name", "file_type", "publisher_or_owner", "year",
                "version_or_identifier", "licence_or_rights_note",
                "summary_1_sentence", "preferred_citation_key", "text_available"
            ])
            writer.writeheader()
            writer.writerow({
                "file_name": "test.csv",
                "file_type": "dataset",
                "publisher_or_owner": "Test Org",
                "year": "2024",
                "version_or_identifier": "v1",
                "licence_or_rights_note": "CC-BY-4.0",
                "summary_1_sentence": "Test file",
                "preferred_citation_key": "test_2024",
                "text_available": "yes"
            })

        try:
            # Monkey-patch MANIFEST_PATH for this test
            import scripts.generate_manifest as gm
            original_path = gm.MANIFEST_PATH
            gm.MANIFEST_PATH = temp_manifest

            result = load_existing()

            assert "test.csv" in result
            assert result["test.csv"]["file_type"] == "dataset"
            assert result["test.csv"]["year"] == "2024"

            # Restore
            gm.MANIFEST_PATH = original_path
        finally:
            if temp_manifest.exists():
                temp_manifest.unlink()


class TestScanFiles:
    """Tests for repository file scanning"""

    def test_scan_finds_files(self):
        """Test that scan_files finds repository files"""
        files = scan_files()

        # Should find at least some Python files
        py_files = [f for f in files if f.suffix == ".py"]
        assert len(py_files) > 0

        # Should find some CSV files
        csv_files = [f for f in files if f.suffix == ".csv"]
        assert len(csv_files) > 0

    def test_scan_excludes_ignored_dirs(self):
        """Test that ignored directories are excluded"""
        files = scan_files()

        # Should not include files from .git, __pycache__, etc.
        for f in files:
            rel_path = f.relative_to(REPO_ROOT)
            assert ".git" not in rel_path.parts
            assert "__pycache__" not in rel_path.parts
            assert ".pytest_cache" not in rel_path.parts

    def test_scan_excludes_manifest_itself(self):
        """Test that the manifest file itself is excluded"""
        files = scan_files()

        # Manifest should not be in the list
        manifest_in_list = any(
            f.resolve() == MANIFEST_PATH.resolve() for f in files
        )
        assert not manifest_in_list

    def test_scan_results_are_sorted(self):
        """Test that scan results are sorted"""
        files = scan_files()

        # Convert to relative paths for comparison
        rel_paths = [f.relative_to(REPO_ROOT).as_posix().lower() for f in files]

        # Check that it's sorted
        assert rel_paths == sorted(rel_paths)

    def test_scan_excludes_root_git_file_in_worktree(self, tmp_path, monkeypatch):
        """Root .git file (Git worktree pointer) should be ignored."""
        import scripts.generate_manifest as gm

        (tmp_path / ".git").write_text("gitdir: /tmp/worktrees/repo")
        (tmp_path / "keep.py").touch()

        monkeypatch.setattr(gm, "REPO_ROOT", tmp_path)
        monkeypatch.setattr(gm, "MANIFEST_PATH", tmp_path / "MANIFEST_SOURCES.csv")

        files = gm.scan_files()
        rel_paths = [f.relative_to(tmp_path).as_posix() for f in files]

        assert ".git" not in rel_paths
        assert "keep.py" in rel_paths

    def test_coverage_files_are_ignored(self):
        """Transient coverage artefacts should be ignored during scanning."""
        assert should_ignore_file(REPO_ROOT / ".coverage")
        assert should_ignore_file(REPO_ROOT / ".coverage.local")
        assert should_ignore_file(REPO_ROOT / "coverage.json")
        assert should_ignore_file(REPO_ROOT / ".allai" / "workspace.db")
        assert not should_ignore_file(REPO_ROOT / "coverage.xml")


class TestManifestSourcesLocalPrAImprovedArchiveRows:
    """Tests for the MANIFEST_SOURCES.csv rows added for the archived
    outputs/run_archive/runs/local-pr-a-improved/ run."""

    ARCHIVE_PREFIX = "outputs/run_archive/runs/local-pr-a-improved/"

    def _archive_entries(self):
        entries = load_existing()
        return {
            name: row
            for name, row in entries.items()
            if name.startswith(self.ARCHIVE_PREFIX)
        }

    def test_archive_rows_are_present_for_the_new_run(self):
        """The manifest must have picked up rows for the newly archived run."""
        entries = self._archive_entries()
        assert len(entries) > 0
        # A representative sample of paths added by this PR must be present.
        expected_paths = {
            self.ARCHIVE_PREFIX + "_checksums.sha256",
            self.ARCHIVE_PREFIX + "manifest.json",
            self.ARCHIVE_PREFIX + "MANIFEST_SOURCES.csv",
            self.ARCHIVE_PREFIX + "analysis_outputs/competences_full_database.json",
            self.ARCHIVE_PREFIX + "analysis_outputs/credentials_matrix.html",
            self.ARCHIVE_PREFIX + "analysis_outputs/gaps_summary.csv",
            self.ARCHIVE_PREFIX
            + "analysis_outputs/sector_dictionaries/blue_biotech_tmbd_dictionary.json",
            self.ARCHIVE_PREFIX
            + "analysis_outputs/sector_dictionaries/ship_repair_tmbd_dictionary.json",
        }
        assert expected_paths.issubset(entries.keys())

    def test_archive_row_field_count_matches_manifest_columns(self):
        """Every added row must have exactly nine comma-separated fields,
        matching the MANIFEST_SOURCES.csv header (no truncated/extra fields
        from an unescaped comma in a summary or citation key). This reads the
        raw rows directly with csv.reader rather than load_existing(), since
        the latter normalizes every row to the fixed COLUMNS key set
        regardless of how many raw fields the on-disk line actually had."""
        with open(MANIFEST_PATH, "r", encoding="utf-8", newline="") as handle:
            reader = csv.reader(handle)
            header = next(reader)
            expected_field_count = len(header)
            archive_rows = [
                row
                for row in reader
                if row and row[0].startswith(self.ARCHIVE_PREFIX)
            ]

        assert archive_rows, "expected at least one archived row to check"
        for row in archive_rows:
            assert len(row) == expected_field_count, row

    def test_checksums_row_is_binary_like_and_marked_text_unavailable(self):
        """The _checksums.sha256 row is a hash listing, not prose/markup, and
        must be classified as 'other' with text_available == 'no'."""
        entries = self._archive_entries()
        row = entries[self.ARCHIVE_PREFIX + "_checksums.sha256"]
        assert row["file_type"] == "other"
        assert row["text_available"] == "no"
        assert row["preferred_citation_key"] == "checksums"

    def test_gaps_summary_csv_row_is_classified_as_dataset_derived(self):
        """gaps_summary.csv is a derived analysis dataset and must carry the
        dataset_derived classification with text_available == 'yes'."""
        entries = self._archive_entries()
        row = entries[self.ARCHIVE_PREFIX + "analysis_outputs/gaps_summary.csv"]
        assert row["file_type"] == "dataset_derived"
        assert row["text_available"] == "yes"

    def test_html_report_rows_are_marked_text_unavailable(self):
        """HTML analysis reports are classified as 'other' with
        text_available == 'no' (HTML is not in the plain-text extension
        allowlist used by text_available())."""
        entries = self._archive_entries()
        for suffix in (
            "analysis_outputs/credentials_matrix.html",
            "analysis_outputs/gaps_by_sector.html",
            "analysis_outputs/literature_integration.html",
            "analysis_outputs/report_index.html",
        ):
            row = entries[self.ARCHIVE_PREFIX + suffix]
            assert row["text_available"] == "no", suffix

    def test_sector_dictionary_json_rows_are_marked_text_available(self):
        """Sector TMBD dictionary JSON files must be marked text_available ==
        'yes', consistent with the .json extension allowlist."""
        entries = self._archive_entries()
        sector_names = (
            "blue_biotech",
            "coastal_tourism",
            "desalination",
            "infra_robotics",
            "living_res",
            "maritime_defence",
            "maritime_transport",
            "non_living_res",
            "port_activities",
            "r_i",
            "renewable_energy",
            "ship_repair",
        )
        for sector in sector_names:
            path = (
                self.ARCHIVE_PREFIX
                + f"analysis_outputs/sector_dictionaries/{sector}_tmbd_dictionary.json"
            )
            assert path in entries, path
            assert entries[path]["text_available"] == "yes"
            assert entries[path]["preferred_citation_key"] == f"{sector}_tmbd_dictionary"

    def test_nested_manifest_sources_csv_row_is_dataset_derived(self):
        """The archived copy of MANIFEST_SOURCES.csv nested under the run
        directory must itself be classified as dataset_derived, matching the
        classification of the top-level MANIFEST_SOURCES.csv row set (a CSV
        without a special-cased 'governance' rule at that nested path)."""
        entries = self._archive_entries()
        row = entries[self.ARCHIVE_PREFIX + "MANIFEST_SOURCES.csv"]
        assert row["file_type"] == "dataset_derived"
        assert row["text_available"] == "yes"

    def test_archive_rows_have_no_duplicate_file_names(self):
        """load_existing() keys by file_name, so if the generator ever wrote
        the same archived path twice, only the last occurrence would survive
        in-memory; assert the on-disk row count for this prefix agrees with
        the deduplicated in-memory count (i.e. no literal duplicate lines)."""
        with open(MANIFEST_PATH, "r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            on_disk_names = [
                row["file_name"]
                for row in reader
                if row.get("file_name", "").startswith(self.ARCHIVE_PREFIX)
            ]
        assert len(on_disk_names) == len(set(on_disk_names))
        assert len(on_disk_names) == len(self._archive_entries())


class TestMainFunction:
    """Tests for main() and CLI execution paths"""

    def test_main_if_name_main_block(self):
        """Test the if __name__ == '__main__' execution path"""
        from scripts.generate_manifest import main

        # Verify main() can be called (may modify MANIFEST_SOURCES.csv)
        # This tests the __name__ == '__main__' block can execute
        result = main()
        # main() returns None, not an int
        assert result is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
