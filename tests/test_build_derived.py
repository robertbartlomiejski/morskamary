"""Tests for scripts/build_derived.py — Excel to CSV conversion logic."""

from pathlib import Path
from unittest.mock import patch

import pandas as pd

from scripts.build_derived import (
    export_sheet,
    main,
    sanitize,
    scan_excel_files,
    write_datadict,
)


class TestSanitize:
    """Test sheet name sanitization."""

    def test_basic_sanitization(self) -> None:
        assert sanitize("Sheet 1") == "sheet_1"
        assert sanitize("My Data Sheet") == "my_data_sheet"

    def test_special_characters_removed(self) -> None:
        assert sanitize("Data@#$%Sheet!") == "data_sheet"
        assert sanitize("Sheet (2023)") == "sheet_2023"

    def test_multiple_spaces_collapsed(self) -> None:
        assert sanitize("Sheet    With    Spaces") == "sheet_with_spaces"

    def test_consecutive_underscores_collapsed(self) -> None:
        assert sanitize("Sheet___Name") == "sheet_name"

    def test_empty_string_returns_default(self) -> None:
        assert sanitize("") == "sheet"
        assert sanitize("   ") == "sheet"
        assert sanitize("@#$%") == "sheet"

    def test_leading_trailing_underscores_stripped(self) -> None:
        assert sanitize("_Sheet_") == "sheet"
        assert sanitize("__Data__") == "data"


class TestScanExcelFiles:
    """Test Excel file scanning."""

    def test_scan_finds_known_excel_files(self, tmp_path: Path) -> None:
        """Test that scan prioritizes known Excel filenames."""
        known_file = tmp_path / "Blue Social Competences Univ Szczecin.xlsx"
        known_file.touch()
        other_file = tmp_path / "other.xlsx"
        other_file.touch()

        with patch("scripts.build_derived.REPO_ROOT", tmp_path):
            results = scan_excel_files()

        assert len(results) == 2
        # Known files should be first
        assert results[0].name == "Blue Social Competences Univ Szczecin.xlsx"

    def test_scan_excludes_temp_files(self, tmp_path: Path) -> None:
        """Test that temporary Excel files (~$) are excluded."""
        temp_file = tmp_path / "~$temporary.xlsx"
        temp_file.touch()
        valid_file = tmp_path / "valid.xlsx"
        valid_file.touch()

        with patch("scripts.build_derived.REPO_ROOT", tmp_path):
            results = scan_excel_files()

        assert len(results) == 1
        assert results[0].name == "valid.xlsx"

    def test_scan_excludes_ignored_directories(self, tmp_path: Path) -> None:
        """Test that ignored directories (.git, __pycache__) are skipped."""
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        (git_dir / "data.xlsx").touch()

        cache_dir = tmp_path / "__pycache__"
        cache_dir.mkdir()
        (cache_dir / "cache.xlsx").touch()

        valid_file = tmp_path / "valid.xlsx"
        valid_file.touch()

        with patch("scripts.build_derived.REPO_ROOT", tmp_path):
            results = scan_excel_files()

        assert len(results) == 1
        assert results[0].name == "valid.xlsx"

    def test_scan_returns_empty_when_no_files(self, tmp_path: Path) -> None:
        """Test that scan returns empty list when no Excel files exist."""
        with patch("scripts.build_derived.REPO_ROOT", tmp_path):
            results = scan_excel_files()

        assert results == []


class TestExportSheet:
    """Test CSV export functionality."""

    def test_export_sheet_creates_csv(self, tmp_path: Path) -> None:
        """Test that export_sheet creates a valid CSV file."""
        df = pd.DataFrame({"col1": [1, 2, 3], "col2": ["a", "b", "c"]})
        out_csv = tmp_path / "output.csv"

        export_sheet(df, out_csv)

        assert out_csv.exists()
        loaded = pd.read_csv(out_csv)
        pd.testing.assert_frame_equal(df, loaded)

    def test_export_sheet_creates_parent_directories(self, tmp_path: Path) -> None:
        """Test that export_sheet creates parent directories if needed."""
        out_csv = tmp_path / "subdir" / "nested" / "output.csv"
        df = pd.DataFrame({"col": [1, 2]})

        export_sheet(df, out_csv)

        assert out_csv.exists()
        assert out_csv.parent.exists()

    def test_export_sheet_handles_empty_dataframe(self, tmp_path: Path) -> None:
        """Test that export_sheet handles empty DataFrames."""
        df = pd.DataFrame()
        out_csv = tmp_path / "empty.csv"

        export_sheet(df, out_csv)

        assert out_csv.exists()


class TestWriteDatadict:
    """Test data dictionary generation."""

    def test_write_datadict_creates_metadata_csv(self, tmp_path: Path) -> None:
        """Test that write_datadict creates a valid data dictionary CSV."""
        df = pd.DataFrame(
            {
                "col1": [1, 2, None],
                "col2": ["a", "b", "c"],
                "col3": [1.1, None, 3.3],
            }
        )
        out_dd = tmp_path / "datadict.csv"

        write_datadict(df, out_dd)

        assert out_dd.exists()
        dd = pd.read_csv(out_dd)
        assert list(dd.columns) == ["column", "dtype", "non_null", "null"]
        assert list(dd["column"]) == ["col1", "col2", "col3"]
        assert dd["non_null"].tolist() == [2, 3, 2]
        assert dd["null"].tolist() == [1, 0, 1]

    def test_write_datadict_handles_all_null_column(self, tmp_path: Path) -> None:
        """Test that write_datadict handles columns with all null values."""
        df = pd.DataFrame({"all_null": [None, None, None], "valid": [1, 2, 3]})
        out_dd = tmp_path / "datadict.csv"

        write_datadict(df, out_dd)

        dd = pd.read_csv(out_dd)
        all_null_row = dd[dd["column"] == "all_null"].iloc[0]
        assert all_null_row["null"] == 3
        assert all_null_row["non_null"] == 0


class TestMainIntegration:
    """Integration tests for the main() function."""

    def test_main_with_valid_excel_file(self, tmp_path: Path, capsys) -> None:
        """Test main() with a valid Excel file containing multiple sheets."""
        # Create a test Excel file with multiple sheets
        excel_file = tmp_path / "test_data.xlsx"
        with pd.ExcelWriter(excel_file, engine="openpyxl") as writer:
            df1 = pd.DataFrame({"A": [1, 2], "B": [3, 4]})
            df2 = pd.DataFrame({"X": ["a", "b"], "Y": ["c", "d"]})
            df1.to_excel(writer, sheet_name="Sheet1", index=False)
            df2.to_excel(writer, sheet_name="Sheet2", index=False)

        derived_dir = tmp_path / "derived"

        with patch("scripts.build_derived.REPO_ROOT", tmp_path):
            with patch("scripts.build_derived.DERIVED_DIR", derived_dir):
                main()

        # Check that CSVs and data dictionaries were created
        assert (derived_dir / "test_data__sheet1.csv").exists()
        assert (derived_dir / "test_data__sheet2.csv").exists()
        assert (derived_dir / "test_data__sheet1__datadict.csv").exists()
        assert (derived_dir / "test_data__sheet2__datadict.csv").exists()

        # Verify console output
        captured = capsys.readouterr()
        assert "Processed:" in captured.out
        assert "exported_tables=2" in captured.out

    def test_main_skips_empty_sheets(self, tmp_path: Path, capsys) -> None:
        """Test that main() skips completely empty sheets."""
        excel_file = tmp_path / "test_empty.xlsx"
        with pd.ExcelWriter(excel_file, engine="openpyxl") as writer:
            df_valid = pd.DataFrame({"A": [1, 2]})
            df_empty = pd.DataFrame()
            df_valid.to_excel(writer, sheet_name="ValidSheet", index=False)
            df_empty.to_excel(writer, sheet_name="EmptySheet", index=False)

        derived_dir = tmp_path / "derived"

        with patch("scripts.build_derived.REPO_ROOT", tmp_path):
            with patch("scripts.build_derived.DERIVED_DIR", derived_dir):
                main()

        # Only valid sheet should be exported
        assert (derived_dir / "test_empty__validsheet.csv").exists()
        assert not (derived_dir / "test_empty__emptysheet.csv").exists()

        captured = capsys.readouterr()
        assert "skipped_empty=1" in captured.out

    def test_main_handles_corrupted_excel(self, tmp_path: Path, capsys) -> None:
        """Test that main() gracefully handles corrupted Excel files."""
        # Create a fake Excel file with invalid content
        fake_excel = tmp_path / "corrupted.xlsx"
        fake_excel.write_text("This is not a valid Excel file")

        with patch("scripts.build_derived.REPO_ROOT", tmp_path):
            with patch("scripts.build_derived.DERIVED_DIR", tmp_path / "derived"):
                main()

        captured = capsys.readouterr()
        assert "FAILED to open:" in captured.out

    def test_main_with_no_excel_files(self, tmp_path: Path, capsys) -> None:
        """Test that main() handles empty directory gracefully."""
        with patch("scripts.build_derived.REPO_ROOT", tmp_path):
            main()

        captured = capsys.readouterr()
        assert "No Excel files found." in captured.out

    def test_main_handles_sheet_parsing_errors(self, tmp_path: Path, capsys) -> None:
        """Test that main() continues processing when a single sheet fails."""
        excel_file = tmp_path / "test_partial_fail.xlsx"
        with pd.ExcelWriter(excel_file, engine="openpyxl") as writer:
            df = pd.DataFrame({"A": [1, 2]})
            df.to_excel(writer, sheet_name="GoodSheet", index=False)

        derived_dir = tmp_path / "derived"

        def mock_parse(*args, **kwargs):
            sheet_name = kwargs.get("sheet_name")
            if sheet_name == "GoodSheet":
                return pd.DataFrame({"A": [1, 2]})
            raise ValueError("Simulated parse error")

        with patch("scripts.build_derived.REPO_ROOT", tmp_path):
            with patch("scripts.build_derived.DERIVED_DIR", derived_dir):
                with patch("pandas.ExcelFile") as mock_excel:
                    mock_instance = mock_excel.return_value
                    mock_instance.sheet_names = ["GoodSheet", "BadSheet"]
                    mock_instance.parse.side_effect = mock_parse
                    main()

        assert (derived_dir / "test_partial_fail__goodsheet.csv").exists()
        assert (derived_dir / "test_partial_fail__goodsheet__datadict.csv").exists()
        assert not (derived_dir / "test_partial_fail__badsheet.csv").exists()
        assert not (derived_dir / "test_partial_fail__badsheet__datadict.csv").exists()

        captured = capsys.readouterr()
        assert "FAILED to parse:" in captured.out
        assert "BadSheet" in captured.out
        assert "Processed:" in captured.out
        assert "exported_tables=1" in captured.out

    def test_main_if_name_main_block(self):
        """Test the if __name__ == '__main__' execution path"""
        from scripts.build_derived import main

        # Verify main() can be called and returns None/0
        result = main()
        # main() returns None, not int, so we just verify it runs
        assert result is None
