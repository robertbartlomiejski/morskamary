from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import yaml

import scripts.export_live_query_protocol_projection as projection_export
from src.scientific_sources.live_query_protocol import load_live_query_protocol

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "export_live_query_protocol_projection.py"
PROTOCOL_PATH = REPO_ROOT / "config" / "live_query_protocol.yml"


def test_projection_script_generates_legacy_query_groups(tmp_path: Path) -> None:
    output_path = tmp_path / "research_queries_from_protocol.yml"
    summary_path = tmp_path / "summary.json"
    constraints_path = tmp_path / "query_protocol_constraints.json"
    cmd = [
        sys.executable,
        str(SCRIPT_PATH),
        "--protocol-path",
        str(PROTOCOL_PATH),
        "--output-path",
        str(output_path),
        "--emit-summary-path",
        str(summary_path),
        "--emit-constraints-path",
        str(constraints_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    assert constraints_path.is_file()
    payload = yaml.safe_load(output_path.read_text(encoding="utf-8"))
    assert "query_groups" in payload

    protocol = load_live_query_protocol(PROTOCOL_PATH)
    projected = []
    for group in payload["query_groups"].values():
        projected.extend(group["queries"])
    assert projected == protocol.flattened_query_texts()


def test_projection_script_fails_when_minimum_query_count_not_met(tmp_path: Path) -> None:
    output_path = tmp_path / "research_queries_from_protocol.yml"
    cmd = [
        sys.executable,
        str(SCRIPT_PATH),
        "--protocol-path",
        str(PROTOCOL_PATH),
        "--output-path",
        str(output_path),
        "--min-total-queries",
        "999",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    assert result.returncode == 1
    assert "exact protocol count mismatch" in result.stderr


def _projection_paths(tmp_path: Path) -> tuple[Path, Path, Path]:
    return (
        tmp_path / "research_queries_from_protocol.yml",
        tmp_path / "summary.json",
        tmp_path / "query_protocol_constraints.json",
    )


def _projection_args(
    output_path: Path, summary_path: Path, constraints_path: Path
) -> list[str]:
    return [
        "--protocol-path",
        str(PROTOCOL_PATH),
        "--output-path",
        str(output_path),
        "--emit-summary-path",
        str(summary_path),
        "--emit-constraints-path",
        str(constraints_path),
    ]


def _write_existing_artifacts(paths: tuple[Path, Path, Path]) -> dict[Path, bytes]:
    previous = {
        paths[0]: b"previous projection\n",
        paths[1]: b"previous summary\n",
        paths[2]: b"previous constraints\n",
    }
    for path, content in previous.items():
        path.write_bytes(content)
    return previous


def _assert_existing_artifacts_unchanged(previous: dict[Path, bytes]) -> None:
    for path, content in previous.items():
        assert path.read_bytes() == content


def _assert_no_publication_temporary_files(tmp_path: Path) -> None:
    assert not list(tmp_path.glob(".*.stage"))
    assert not list(tmp_path.glob(".*.rollback"))


def test_projection_validates_final_bytes_before_staging_or_publishing(
    tmp_path: Path, monkeypatch
) -> None:
    paths = _projection_paths(tmp_path)
    previous = _write_existing_artifacts(paths)

    def invalid_projection_serialization(*_args, **_kwargs) -> str:
        return "not: the authoritative projection\n"

    def should_not_stage(*_args, **_kwargs):
        raise AssertionError("staging must not start before final-byte validation")

    monkeypatch.setattr(projection_export.yaml, "safe_dump", invalid_projection_serialization)
    monkeypatch.setattr(projection_export, "_stage_bytes_artifact", should_not_stage)

    with pytest.raises(ValueError, match="serialized protocol projection differs"):
        projection_export.main(_projection_args(*paths))

    _assert_existing_artifacts_unchanged(previous)
    _assert_no_publication_temporary_files(tmp_path)


def _assert_prewrite_protocol_validation_failure(
    paths: tuple[Path, Path, Path], error_match: str
) -> None:
    previous = _write_existing_artifacts(paths)

    with pytest.raises(projection_export.LiveQueryProtocolError, match=error_match):
        projection_export.main(_projection_args(*paths))

    _assert_existing_artifacts_unchanged(previous)
    _assert_no_publication_temporary_files(paths[0].parent)


def test_projection_query_count_mismatch_preserves_existing_artifacts(
    tmp_path: Path, monkeypatch
) -> None:
    paths = _projection_paths(tmp_path)
    original_constraints = projection_export.LiveQueryProtocol.to_query_constraints

    def omit_one_constraint(self):
        return original_constraints(self)[:-1]

    monkeypatch.setattr(
        projection_export.LiveQueryProtocol,
        "to_query_constraints",
        omit_one_constraint,
    )

    _assert_prewrite_protocol_validation_failure(paths, "exactly 120 queries")


def test_projection_duplicate_query_id_preserves_existing_artifacts(
    tmp_path: Path, monkeypatch
) -> None:
    paths = _projection_paths(tmp_path)
    original_constraints = projection_export.LiveQueryProtocol.to_query_constraints

    def duplicate_constraint_id(self):
        constraints = original_constraints(self)
        duplicate = dict(constraints[1])
        duplicate["query_id"] = constraints[0]["query_id"]
        constraints[1] = duplicate
        return constraints

    monkeypatch.setattr(
        projection_export.LiveQueryProtocol,
        "to_query_constraints",
        duplicate_constraint_id,
    )

    _assert_prewrite_protocol_validation_failure(paths, "duplicate projected query IDs")


def test_projection_family_mismatch_preserves_existing_artifacts(
    tmp_path: Path, monkeypatch
) -> None:
    paths = _projection_paths(tmp_path)
    original_constraints = projection_export.LiveQueryProtocol.to_query_constraints

    def mismatch_query_family(self):
        constraints = original_constraints(self)
        changed = dict(constraints[0])
        changed["query_family"] = (
            "competence_demand"
            if changed["query_family"] != "competence_demand"
            else "core_sector"
        )
        constraints[0] = changed
        return constraints

    monkeypatch.setattr(
        projection_export.LiveQueryProtocol,
        "to_query_constraints",
        mismatch_query_family,
    )

    _assert_prewrite_protocol_validation_failure(paths, "family mismatch")


def test_projection_axis_target_mismatch_preserves_existing_artifacts(
    tmp_path: Path, monkeypatch
) -> None:
    paths = _projection_paths(tmp_path)
    original_constraints = projection_export.LiveQueryProtocol.to_query_constraints

    def mismatch_axis_target(self):
        constraints = original_constraints(self)
        changed = dict(constraints[0])
        changed["axis_target"] = (
            "MARITIME" if changed["axis_target"] != "MARITIME" else "MARINE"
        )
        constraints[0] = changed
        return constraints

    monkeypatch.setattr(
        projection_export.LiveQueryProtocol,
        "to_query_constraints",
        mismatch_axis_target,
    )

    _assert_prewrite_protocol_validation_failure(paths, "axis-target mismatch")


def test_projection_constraints_mismatch_preserves_existing_artifacts(
    tmp_path: Path, monkeypatch
) -> None:
    paths = _projection_paths(tmp_path)
    original_constraints = projection_export.LiveQueryProtocol.to_query_constraints

    def mismatch_sampling_constraint(self):
        constraints = original_constraints(self)
        changed = dict(constraints[0])
        sampling = dict(changed["sampling_strategy"])
        sampling["rows_per_page"] = int(sampling["rows_per_page"]) + 1
        changed["sampling_strategy"] = sampling
        constraints[0] = changed
        return constraints

    monkeypatch.setattr(
        projection_export.LiveQueryProtocol,
        "to_query_constraints",
        mismatch_sampling_constraint,
    )

    _assert_prewrite_protocol_validation_failure(paths, "sampling-strategy mismatch")


def test_projection_staged_write_failure_preserves_existing_artifacts(
    tmp_path: Path, monkeypatch
) -> None:
    paths = _projection_paths(tmp_path)
    previous = _write_existing_artifacts(paths)
    original_stage = projection_export._stage_bytes_artifact
    staged_count = 0

    def fail_second_stage(destination: Path, content: bytes) -> Path:
        nonlocal staged_count
        staged_count += 1
        if staged_count == 2:
            raise OSError("simulated staged write failure")
        return original_stage(destination, content)

    monkeypatch.setattr(projection_export, "_stage_bytes_artifact", fail_second_stage)

    with pytest.raises(OSError, match="simulated staged write failure"):
        projection_export.main(_projection_args(*paths))

    _assert_existing_artifacts_unchanged(previous)
    _assert_no_publication_temporary_files(tmp_path)


def test_projection_revalidates_staged_bytes_before_publishing(
    tmp_path: Path, monkeypatch
) -> None:
    paths = _projection_paths(tmp_path)
    previous = _write_existing_artifacts(paths)
    original_stage = projection_export._stage_bytes_artifact
    staged_count = 0

    def tamper_first_stage(destination: Path, content: bytes) -> Path:
        nonlocal staged_count
        staged_count += 1
        stage_path = original_stage(destination, content)
        if staged_count == 1:
            stage_path.write_bytes(b"not: the authoritative projection\n")
        return stage_path

    monkeypatch.setattr(projection_export, "_stage_bytes_artifact", tamper_first_stage)

    with pytest.raises(ValueError, match="serialized protocol projection differs"):
        projection_export.main(_projection_args(*paths))

    _assert_existing_artifacts_unchanged(previous)
    _assert_no_publication_temporary_files(tmp_path)


@pytest.mark.parametrize("failed_artifact", ["projection", "summary", "constraints"])
def test_projection_replacement_failure_rolls_back_all_existing_artifacts(
    tmp_path: Path, monkeypatch, failed_artifact: str
) -> None:
    paths = _projection_paths(tmp_path)
    previous = _write_existing_artifacts(paths)
    targets = dict(zip(("projection", "summary", "constraints"), paths))
    target = targets[failed_artifact]
    original_replace = projection_export.os.replace

    def fail_selected_stage_replace(source, destination):
        if Path(source).suffix == ".stage" and Path(destination) == target:
            raise OSError(f"simulated replacement failure for {failed_artifact}")
        return original_replace(source, destination)

    monkeypatch.setattr(projection_export.os, "replace", fail_selected_stage_replace)

    with pytest.raises(OSError, match="simulated replacement failure"):
        projection_export.main(_projection_args(*paths))

    _assert_existing_artifacts_unchanged(previous)
    _assert_no_publication_temporary_files(tmp_path)


def test_projection_rollback_removes_a_previously_absent_output(
    tmp_path: Path, monkeypatch
) -> None:
    output_path, summary_path, constraints_path = _projection_paths(tmp_path)
    previous = {
        summary_path: b"previous summary\n",
        constraints_path: b"previous constraints\n",
    }
    for path, content in previous.items():
        path.write_bytes(content)
    original_replace = projection_export.os.replace

    def fail_summary_stage_replace(source, destination):
        if Path(source).suffix == ".stage" and Path(destination) == summary_path:
            raise OSError("simulated replacement failure for summary")
        return original_replace(source, destination)

    monkeypatch.setattr(projection_export.os, "replace", fail_summary_stage_replace)

    with pytest.raises(OSError, match="simulated replacement failure for summary"):
        projection_export.main(
            _projection_args(output_path, summary_path, constraints_path)
        )

    assert not output_path.exists()
    _assert_existing_artifacts_unchanged(previous)
    _assert_no_publication_temporary_files(tmp_path)


def test_projection_preserves_original_failure_when_rollback_also_fails(
    tmp_path: Path, monkeypatch
) -> None:
    output_path, summary_path, constraints_path = _projection_paths(tmp_path)
    _write_existing_artifacts((output_path, summary_path, constraints_path))
    original_replace = projection_export.os.replace

    def fail_publish_and_rollback(source, destination):
        source_path = Path(source)
        destination_path = Path(destination)
        if source_path.suffix == ".stage" and destination_path == summary_path:
            raise OSError("primary replacement failure")
        if source_path.suffix == ".rollback" and destination_path == output_path:
            raise OSError("secondary rollback failure")
        return original_replace(source, destination)

    monkeypatch.setattr(projection_export.os, "replace", fail_publish_and_rollback)

    with pytest.raises(OSError, match="primary replacement failure") as exc_info:
        projection_export.main(
            _projection_args(output_path, summary_path, constraints_path)
        )

    assert "could not completely roll back" not in str(exc_info.value)


def test_projection_publication_bytes_are_deterministic(tmp_path: Path) -> None:
    paths = _projection_paths(tmp_path)
    args = _projection_args(*paths)

    assert projection_export.main(args) == 0
    first_bytes = {path: path.read_bytes() for path in paths}
    assert projection_export.main(args) == 0

    for path, content in first_bytes.items():
        assert path.read_bytes() == content
