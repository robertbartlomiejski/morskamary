"""Tests for scripts/sync_audit.py."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure scripts/ is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from sync_audit import (  # noqa: E402
    AuditReport,
    _capabilities_semantically_equal,
    _file_hash,
    check_changelog_governance,
    check_git_status,
    check_manifest_drift,
    check_mcp_config,
    check_outputs_drift,
    check_provider_capabilities,
    main,
)


# ---------------------------------------------------------------------------
# AuditReport
# ---------------------------------------------------------------------------


class TestAuditReport:
    def test_starts_clean(self):
        r = AuditReport()
        assert not r.failed
        assert not r.has_warnings

    def test_error_marks_failed(self):
        r = AuditReport()
        r.error("boom")
        assert r.failed
        assert r.errors == ["boom"]

    def test_warn_marks_has_warnings(self):
        r = AuditReport()
        r.warn("hmm")
        assert not r.failed
        assert r.has_warnings
        assert r.warnings == ["hmm"]


# ---------------------------------------------------------------------------
# _file_hash
# ---------------------------------------------------------------------------


class TestFileHash:
    def test_consistent_hash(self, tmp_path):
        p = tmp_path / "test.txt"
        p.write_text("hello world\n", encoding="utf-8")
        h1 = _file_hash(p)
        h2 = _file_hash(p)
        assert h1 == h2
        assert len(h1) == 64  # SHA-256 hex

    def test_different_content_different_hash(self, tmp_path):
        p1 = tmp_path / "a.txt"
        p2 = tmp_path / "b.txt"
        p1.write_text("aaa", encoding="utf-8")
        p2.write_text("bbb", encoding="utf-8")
        assert _file_hash(p1) != _file_hash(p2)


# ---------------------------------------------------------------------------
# check_git_status
# ---------------------------------------------------------------------------


class TestCheckGitStatus:
    def test_clean_working_tree(self):
        report = AuditReport()
        mock_result_status = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )
        mock_result_revlist = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="0\t0", stderr=""
        )
        with patch("sync_audit._run", side_effect=[mock_result_status, mock_result_revlist]):
            check_git_status(report)
        assert not report.failed
        assert not report.has_warnings

    def test_dirty_tree_warns(self):
        report = AuditReport()
        mock_result_status = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=" M file.py\n?? new.txt\n", stderr=""
        )
        mock_result_revlist = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="0\t0", stderr=""
        )
        with patch("sync_audit._run", side_effect=[mock_result_status, mock_result_revlist]):
            check_git_status(report)
        assert not report.failed
        assert report.has_warnings

    def test_ahead_of_remote_warns(self):
        report = AuditReport()
        mock_result_status = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )
        mock_result_revlist = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="3\t0", stderr=""
        )
        with patch("sync_audit._run", side_effect=[mock_result_status, mock_result_revlist]):
            check_git_status(report)
        assert report.has_warnings

    def test_behind_remote_warns(self):
        report = AuditReport()
        mock_result_status = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )
        mock_result_revlist = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="0\t2", stderr=""
        )
        with patch("sync_audit._run", side_effect=[mock_result_status, mock_result_revlist]):
            check_git_status(report)
        assert report.has_warnings


# ---------------------------------------------------------------------------
# check_outputs_drift
# ---------------------------------------------------------------------------


class TestCheckOutputsDrift:
    def test_no_drift(self):
        report = AuditReport()
        mock_result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )
        with patch("sync_audit._run", return_value=mock_result):
            with patch("sync_audit.REPO_ROOT", Path("/fake/repo")):
                with patch.object(Path, "is_dir", return_value=True):
                    check_outputs_drift(report)
        assert not report.failed

    def test_drift_detected(self):
        report = AuditReport()
        mock_result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=" outputs/foo.json | 2 +-\n", stderr=""
        )
        with patch("sync_audit._run", return_value=mock_result):
            with patch("sync_audit.REPO_ROOT", Path("/fake/repo")):
                with patch.object(Path, "is_dir", return_value=True):
                    check_outputs_drift(report)
        assert report.failed


# ---------------------------------------------------------------------------
# check_mcp_config
# ---------------------------------------------------------------------------


class TestCheckMcpConfig:
    def test_valid_config(self, tmp_path):
        mcp_dir = tmp_path / ".vscode"
        mcp_dir.mkdir()
        mcp_file = mcp_dir / "mcp.json"
        mcp_file.write_text(
            json.dumps({"servers": {"test": {"type": "stdio"}}}),
            encoding="utf-8",
        )
        with patch("sync_audit.REPO_ROOT", tmp_path):
            report = AuditReport()
            check_mcp_config(report)
        assert not report.failed

    def test_malformed_json(self, tmp_path):
        mcp_dir = tmp_path / ".vscode"
        mcp_dir.mkdir()
        mcp_file = mcp_dir / "mcp.json"
        mcp_file.write_text("{bad json", encoding="utf-8")
        with patch("sync_audit.REPO_ROOT", tmp_path):
            report = AuditReport()
            check_mcp_config(report)
        assert report.failed

    def test_missing_servers_key(self, tmp_path):
        mcp_dir = tmp_path / ".vscode"
        mcp_dir.mkdir()
        mcp_file = mcp_dir / "mcp.json"
        mcp_file.write_text(json.dumps({"inputs": []}), encoding="utf-8")
        with patch("sync_audit.REPO_ROOT", tmp_path):
            report = AuditReport()
            check_mcp_config(report)
        assert report.failed


# ---------------------------------------------------------------------------
# check_changelog_governance
# ---------------------------------------------------------------------------


class TestCheckChangelogGovernance:
    def test_changelog_exists(self, tmp_path):
        changelog = tmp_path / "CHANGELOG.txt"
        changelog.write_text("- Entry 1\n- Entry 2\n- Entry 3\n- Entry 4\n", encoding="utf-8")
        with patch("sync_audit.REPO_ROOT", tmp_path):
            report = AuditReport()
            check_changelog_governance(report)
        assert not report.failed

    def test_changelog_missing(self, tmp_path):
        with patch("sync_audit.REPO_ROOT", tmp_path):
            report = AuditReport()
            check_changelog_governance(report)
        assert report.failed


# ---------------------------------------------------------------------------
# main() integration
# ---------------------------------------------------------------------------


class TestMain:
    def test_strict_mode_fails_on_warnings(self):
        """In strict mode, warnings count as failures."""
        with patch("sync_audit.check_git_status") as mock_git, \
             patch("sync_audit.check_outputs_drift"), \
             patch("sync_audit.check_manifest_drift"), \
             patch("sync_audit.check_provider_capabilities"), \
             patch("sync_audit.check_mcp_config"), \
             patch("sync_audit.check_changelog_governance"):
            # Inject a warning via side effect
            def add_warning(report):
                report.warn("test warning")
            mock_git.side_effect = add_warning

            exit_code = main(["--strict"])
            assert exit_code == 1

    def test_normal_mode_passes_with_warnings(self):
        """In normal mode, warnings don't cause failure."""
        with patch("sync_audit.check_git_status") as mock_git, \
             patch("sync_audit.check_outputs_drift"), \
             patch("sync_audit.check_manifest_drift"), \
             patch("sync_audit.check_provider_capabilities"), \
             patch("sync_audit.check_mcp_config"), \
             patch("sync_audit.check_changelog_governance"):
            def add_warning(report):
                report.warn("test warning")
            mock_git.side_effect = add_warning

            exit_code = main([])
            assert exit_code == 0

    def test_errors_cause_failure(self):
        """Errors always cause failure."""
        with patch("sync_audit.check_git_status") as mock_git, \
             patch("sync_audit.check_outputs_drift"), \
             patch("sync_audit.check_manifest_drift"), \
             patch("sync_audit.check_provider_capabilities"), \
             patch("sync_audit.check_mcp_config"), \
             patch("sync_audit.check_changelog_governance"):
            def add_error(report):
                report.error("critical issue")
            mock_git.side_effect = add_error

            exit_code = main([])
            assert exit_code == 1


# ---------------------------------------------------------------------------
# Regression tests for CI-safety
# ---------------------------------------------------------------------------


class TestCISafety:
    def test_detached_head_no_upstream_does_not_warn(self):
        """In CI (detached HEAD), no-upstream should emit ok, not warn."""
        report = AuditReport()
        mock_result_status = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )
        # Simulate failure from no upstream (detached HEAD in CI)
        mock_result_revlist = subprocess.CompletedProcess(
            args=[], returncode=128,
            stdout="",
            stderr="fatal: no upstream configured for branch"
        )
        with patch("sync_audit._run", side_effect=[mock_result_status, mock_result_revlist]):
            check_git_status(report)
        assert not report.failed
        assert not report.has_warnings

    def test_provider_capability_reexport_no_false_drift_from_generated_at(self, tmp_path):
        """Re-export with only generated_at/configured changes should not warn."""
        from sync_audit import _capabilities_semantically_equal

        old_data = {
            "generated_at": "2026-01-01T00:00:00Z",
            "providers": {
                "crossref": {"provider": "Crossref", "configured": True, "requires_secret": False},
                "scopus": {"provider": "Scopus", "configured": False, "requires_secret": True},
            },
        }
        new_data = {
            "generated_at": "2026-05-22T12:00:00Z",
            "providers": {
                "crossref": {"provider": "Crossref", "configured": True, "requires_secret": False},
                "scopus": {"provider": "Scopus", "configured": True, "requires_secret": True},
            },
        }
        assert _capabilities_semantically_equal(old_data, new_data)

    def test_provider_capability_structural_change_detected(self, tmp_path):
        """Structural changes (new provider, changed fields) should be detected."""
        from sync_audit import _capabilities_semantically_equal

        old_data = {
            "generated_at": "2026-01-01T00:00:00Z",
            "providers": {
                "crossref": {"provider": "Crossref", "configured": True, "requires_secret": False},
            },
        }
        new_data = {
            "generated_at": "2026-05-22T12:00:00Z",
            "providers": {
                "crossref": {"provider": "Crossref", "configured": True, "requires_secret": False},
                "scopus": {"provider": "Scopus", "configured": True, "requires_secret": True},
            },
        }
        assert not _capabilities_semantically_equal(old_data, new_data)
