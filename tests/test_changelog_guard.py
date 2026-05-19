"""Tests for scripts.changelog_guard."""

from __future__ import annotations

import pytest

from scripts import changelog_guard


class TestRequiresChangelogForFile:
    """Unit tests for changelog trigger detection."""

    @pytest.mark.parametrize(
        ("path", "expected"),
        [
            ("scripts/generate_manifest.py", True),
            ("prompts/example.txt", True),
            ("templates/example.md", True),
            ("data/derived/table.json", True),
            ("folder/report.csv", True),
            ("folder/report.xlsx", True),
            ("folder/policy.pdf", True),
            ("CITATION.txt", True),
            ("DATA_GOVERNANCE.txt", True),
            ("LLM_CONTEXT_INSTRUCTION.txt", True),
            ("CHANGELOG.txt", False),
            ("README.md", False),
            ("docs/overview.md", False),
            ("src/core.py", False),
        ],
    )
    def test_trigger_matrix(self, path: str, expected: bool) -> None:
        """Only substantive tracked artifacts should trigger changelog enforcement."""
        assert changelog_guard.requires_changelog_for_file(path) is expected

    def test_normalizes_relative_and_windows_paths(self) -> None:
        """Normalization should keep git-style comparisons stable."""
        assert changelog_guard.normalize_changed_file("./scripts\\tool.py") == "scripts/tool.py"


class TestEvaluateChangedFiles:
    """Tests for aggregate changelog evaluation."""

    def test_only_changelog_update_does_not_require_guard(self) -> None:
        """A lone changelog edit should pass without extra triggers."""
        result = changelog_guard.evaluate_changed_files(["CHANGELOG.txt"])

        assert result.requires_changelog is False
        assert result.has_changelog_update is True
        assert result.missing_changelog is False
        assert result.triggering_files == ()

    def test_triggering_change_without_changelog_fails(self) -> None:
        """Substantive changes without CHANGELOG.txt should fail the guard."""
        result = changelog_guard.evaluate_changed_files(
            ["scripts/export_live_research_records.py", "tests/test_export_live_research_records.py"]
        )

        assert result.requires_changelog is True
        assert result.has_changelog_update is False
        assert result.missing_changelog is True
        assert result.triggering_files == ("scripts/export_live_research_records.py",)

    def test_triggering_change_with_changelog_passes(self) -> None:
        """Substantive changes plus CHANGELOG.txt should pass the guard."""
        result = changelog_guard.evaluate_changed_files(
            ["data/derived/example.csv", "CHANGELOG.txt"]
        )

        assert result.requires_changelog is True
        assert result.has_changelog_update is True
        assert result.missing_changelog is False

    def test_blank_entries_are_ignored(self) -> None:
        """Empty lines from git diff output should not affect the result."""
        result = changelog_guard.evaluate_changed_files(["", " ", "\n", "README.md"])

        assert result.changed_files == ("README.md",)
        assert result.requires_changelog is False


class TestDiffChangedFiles:
    """Tests for git diff integration."""

    def test_raises_when_git_diff_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A git diff failure should surface as a runtime error."""

        def fake_run(*args, **kwargs):  # type: ignore[no-untyped-def]
            class Result:
                returncode = 1
                stdout = ""
                stderr = "fatal: bad revision"

            return Result()

        monkeypatch.setattr(changelog_guard.subprocess, "run", fake_run)

        with pytest.raises(RuntimeError, match="fatal: bad revision"):
            changelog_guard.diff_changed_files("main")

    def test_returns_normalized_changed_files(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """git diff output should be normalized and filtered."""

        def fake_run(*args, **kwargs):  # type: ignore[no-untyped-def]
            class Result:
                returncode = 0
                stdout = "./scripts/tool.py\nCHANGELOG.txt\n\n"
                stderr = ""

            return Result()

        monkeypatch.setattr(changelog_guard.subprocess, "run", fake_run)

        assert changelog_guard.diff_changed_files("main") == (
            "scripts/tool.py",
            "CHANGELOG.txt",
        )


class TestMain:
    """CLI tests for the changelog guard."""

    def test_main_returns_failure_for_missing_changelog(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """CLI should fail when explicit changed files omit CHANGELOG.txt."""
        exit_code = changelog_guard.main(
            ["--changed-file", "scripts/generate_manifest.py"]
        )

        captured = capsys.readouterr()
        assert exit_code == 1
        assert "does not update CHANGELOG.txt" in captured.out
        assert "scripts/generate_manifest.py" in captured.out

    def test_main_returns_success_when_changelog_present(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """CLI should pass when substantive changes include the changelog."""
        exit_code = changelog_guard.main(
            [
                "--changed-file",
                "scripts/generate_manifest.py",
                "--changed-file",
                "CHANGELOG.txt",
            ]
        )

        captured = capsys.readouterr()
        assert exit_code == 0
        assert "CHANGELOG enforcement passed." in captured.out
