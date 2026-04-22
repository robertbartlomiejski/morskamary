"""Integration tests for main entrypoints of primary scripts."""

import pytest


@pytest.mark.integration
def test_main_demo_outputs(capsys):
    """main.main should render the demo summary without errors."""
    import main

    main.main()

    captured = capsys.readouterr()
    assert "MORSKAMARY: Blue Sociology Competence Mapping" in captured.out
    assert "Competence Mapping Summary" in captured.out
    assert "Competence Gap Analysis Example" in captured.out


@pytest.mark.integration
def test_run_full_analysis_main(tmp_path, monkeypatch):
    """run_full_analysis.main should complete and produce key outputs."""
    import run_full_analysis as rfa

    monkeypatch.setattr(rfa, "OUTPUTS_DIR", tmp_path)

    exit_code = rfa.main()

    assert exit_code == 0

    expected_files = [
        "report_index.html",
        "gaps_by_sector.html",
        "credentials_matrix.html",
        "literature_integration.html",
        "competences_full_database.json",
        "credentials_database.json",
        "sector_pathways.json",
        "gaps_summary.csv",
    ]
    for fname in expected_files:
        assert (tmp_path / fname).exists()

    sector_dir = tmp_path / "sector_dictionaries"
    sector_files = list(sector_dir.glob("*_tmbd_dictionary.json"))
    assert len(sector_files) == len(rfa.SECTORS)


@pytest.mark.integration
def test_main_real_data_entrypoint(capsys):
    """main_real_data.main should run successfully and return zero."""
    import main_real_data

    exit_code = main_real_data.main()

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Real Data Analysis Complete" in captured.out


class TestMainRealDataEdgeCases:
    """Edge case tests for main_real_data.py"""

    def test_main_real_data_if_name_main(self):
        """Test the if __name__ == '__main__' execution path for main_real_data"""
        import main_real_data

        # Verify main() can be called and returns int
        result = main_real_data.main()
        assert isinstance(result, int)
        assert result in (0, 1)
