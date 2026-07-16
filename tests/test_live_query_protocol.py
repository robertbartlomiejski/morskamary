"""Tests for `src.scientific_sources.live_query_protocol` (PR-190 / Layer 0)."""

from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Any, Dict

import pytest
import yaml

import run_full_analysis
from src.core import BlueDynamicsAxis
from src.scientific_sources.live_query_protocol import (
    FAMILY_MINIMUMS,
    LiveQuery,
    LiveQueryFamily,
    LiveQueryProtocol,
    LiveQueryProtocolError,
    LiveQuerySector,
    load_live_query_protocol,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_PATH = REPO_ROOT / "config" / "live_query_protocol.yml"
LEGACY_QUERIES_PATH = REPO_ROOT / "config" / "research_queries.yml"


# ---------- fixtures ----------------------------------------------------


@pytest.fixture(scope="module")
def loaded_protocol() -> LiveQueryProtocol:
    return load_live_query_protocol(PROTOCOL_PATH)


def _minimal_valid_sector(
    slug: str = "blue_biotech",
    label: str = "Blue Biotech",
    axis: str = "MARINE",
) -> Dict[str, Any]:
    """Produce a minimal valid sector payload that satisfies family minimums."""
    return {
        "label": label,
        "description": f"Description for {label}",
        "axis_primary": axis,
        "queries": _minimal_valid_queries(slug),
    }


def _minimal_valid_queries(slug: str) -> list:
    """Produce the minimum set of queries per sector: 3/2/2/1/1/1 = 10 queries."""
    plan = [
        (LiveQueryFamily.CORE_SECTOR, 3),
        (LiveQueryFamily.COMPETENCE_DEMAND, 2),
        (LiveQueryFamily.EMERGING_DEMAND, 2),
        (LiveQueryFamily.VALIDATION_EQF_TRANSLATION, 1),
        (LiveQueryFamily.HYPOTHESIS_VERIFICATION, 1),
        (LiveQueryFamily.THEORY_TRANSLATION, 1),
    ]
    queries = []
    for family, count in plan:
        for i in range(count):
            queries.append(_minimal_query(slug, family, i))
    return queries


def _minimal_query(slug: str, family: LiveQueryFamily, idx: int) -> Dict[str, Any]:
    family_token = family.value.upper()
    return {
        "query_id": f"Q_{slug.upper()}_{family_token}_{idx:03d}",
        "sector": slug.replace("_", " ").title(),
        "sector_slug": slug,
        "axis_target": "MARINE",
        "query_text": f"query text {family.value} {idx}",
        "query_family": family.value,
        "evidence_intent": family.value,
        "time_window": {"from_year": 2019, "to_year": 2026},
        "sort_strategy": {
            "crossref": "published-desc",
            "scopus": "date-desc",
            "wos": "date-desc",
        },
        "sampling_strategy": {
            "mode": "stratified",
            "pages": 3,
            "rows_per_page": 50,
            "dedupe_key": "doi|normalized_title",
        },
        "expected_signal": ["competence_demand"],
    }


def _minimal_valid_document(
    sectors: Dict[str, Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    if sectors is None:
        sectors = {"blue_biotech": _minimal_valid_sector()}
    return {
        "protocol_version": "1.0.0",
        "query_families": [f.value for f in LiveQueryFamily],
        "hypotheses": {
            "H1": {
                "label": "Maritimisation Shift",
                "definition": "Test definition",
                "test": "cohens_d",
                "direction": "positive",
                "required_axes": ["MARITIME", "OCEANIC"],
                "declared_outcomes": [
                    "supported_maritime_dominance",
                    "partially_supported_maritime",
                    "not_supported",
                    "not_computable",
                ],
                "required_result_fields": [
                    "hypothesis_id",
                    "interpretation",
                ],
            }
        },
        "sectors": sectors,
    }


def _write_yaml(tmp_path: Path, payload: Dict[str, Any]) -> Path:
    path = tmp_path / "protocol.yml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return path


# ---------- shipped file: structural checks -----------------------------


class TestShippedProtocol:
    """Structural checks against the actual `config/live_query_protocol.yml`."""

    def test_protocol_file_exists(self) -> None:
        assert PROTOCOL_PATH.is_file(), (
            "config/live_query_protocol.yml is required (PR-190 / Layer 0)"
        )

    def test_loads_without_error(self, loaded_protocol: LiveQueryProtocol) -> None:
        assert loaded_protocol.protocol_version
        assert loaded_protocol.sectors
        assert loaded_protocol.hypotheses

    def test_covers_twelve_canonical_sectors(
        self, loaded_protocol: LiveQueryProtocol
    ) -> None:
        assert len(loaded_protocol.sectors) == 12
        labels = {sector.label for sector in loaded_protocol.sectors.values()}
        assert labels == set(run_full_analysis.SECTORS), (
            "live_query_protocol.yml labels must match run_full_analysis.SECTORS exactly"
        )

    def test_all_six_families_declared(
        self, loaded_protocol: LiveQueryProtocol
    ) -> None:
        assert set(loaded_protocol.query_families) == set(LiveQueryFamily)

    def test_hypothesis_registry_loaded(self, loaded_protocol: LiveQueryProtocol) -> None:
        assert {"H1", "H2", "H3"} <= set(loaded_protocol.hypotheses)
        h1 = loaded_protocol.hypotheses["H1"]
        assert h1.label
        assert h1.required_axes

    def test_per_sector_family_minimums(
        self, loaded_protocol: LiveQueryProtocol
    ) -> None:
        for slug, sector in loaded_protocol.sectors.items():
            grouped = sector.queries_by_family()
            for family, minimum in FAMILY_MINIMUMS.items():
                assert len(grouped[family]) >= minimum, (
                    f"sector {slug}: family {family.value} has "
                    f"{len(grouped[family])} queries, requires >= {minimum}"
                )

    def test_minimum_query_count_across_all_sectors(
        self, loaded_protocol: LiveQueryProtocol
    ) -> None:
        # 12 sectors * (3 core + 2 comp + 2 emerging + 1 val + 1 hyp + 1 theory) = 120 minimum
        assert len(loaded_protocol.all_queries()) >= 120

    def test_all_query_ids_unique(self, loaded_protocol: LiveQueryProtocol) -> None:
        ids = [q.query_id for q in loaded_protocol.all_queries()]
        assert len(ids) == len(set(ids)), "query_id values must be globally unique"

    def test_axis_targets_are_valid(
        self, loaded_protocol: LiveQueryProtocol
    ) -> None:
        for query in loaded_protocol.all_queries():
            assert isinstance(query.axis_target, BlueDynamicsAxis)

    def test_competence_demand_queries_use_workforce_vocabulary(
        self, loaded_protocol: LiveQueryProtocol
    ) -> None:
        """PR-190: competence_demand queries must explicitly include competence/
        workforce/education vocabulary."""
        vocab = {
            "skills",
            "competences",
            "competency",
            "workforce",
            "education",
            "training",
            "learning outcomes",
            "curriculum",
            "qualification",
            "professional development",
        }
        for query in loaded_protocol.all_queries():
            if query.query_family is not LiveQueryFamily.COMPETENCE_DEMAND:
                continue
            text = query.query_text.lower()
            assert any(term in text for term in vocab), (
                f"competence_demand query {query.query_id} must include at least one "
                f"of the required workforce/education vocabulary terms; got: {text!r}"
            )

    def test_emerging_demand_queries_use_emerging_vocabulary(
        self, loaded_protocol: LiveQueryProtocol
    ) -> None:
        """PR-190: emerging_demand queries must include forward-looking signals."""
        vocab = {
            "ai",
            "digital twin",
            "autonomous systems",
            "resilience",
            "climate adaptation",
            "just transition",
            "safety",
            "ocean literacy",
            "marine governance",
            "blue economy labour",
            "hydrosocial",
            "port-city",
        }
        for query in loaded_protocol.all_queries():
            if query.query_family is not LiveQueryFamily.EMERGING_DEMAND:
                continue
            text = query.query_text.lower()
            assert any(term in text for term in vocab), (
                f"emerging_demand query {query.query_id} must include at least one "
                f"of the required emerging-signal vocabulary terms; got: {text!r}"
            )

    def test_validation_queries_reference_eqf_or_micro_credential(
        self, loaded_protocol: LiveQueryProtocol
    ) -> None:
        for query in loaded_protocol.all_queries():
            if query.query_family is not LiveQueryFamily.VALIDATION_EQF_TRANSLATION:
                continue
            text = query.query_text.lower()
            assert ("eqf" in text) or ("micro-credential" in text) or (
                "qualification framework" in text
            ), (
                f"validation_eqf_translation query {query.query_id} must reference "
                f"EQF or micro-credential; got: {text!r}"
            )

    def test_hypothesis_queries_reference_hypothesis_or_indicator_terms(
        self, loaded_protocol: LiveQueryProtocol
    ) -> None:
        for query in loaded_protocol.all_queries():
            if query.query_family is not LiveQueryFamily.HYPOTHESIS_VERIFICATION:
                continue
            text = query.query_text.lower()
            assert ("hypothesis" in text) or ("indicator" in text), (
                f"hypothesis_verification query {query.query_id} must reference "
                f"hypothesis/indicator terms; got: {text!r}"
            )

    def test_theory_translation_queries_reference_axis_or_theory_terms(
        self, loaded_protocol: LiveQueryProtocol
    ) -> None:
        for query in loaded_protocol.all_queries():
            if query.query_family is not LiveQueryFamily.THEORY_TRANSLATION:
                continue
            text = query.query_text.lower()
            assert ("theory" in text) or ("axis" in text) or ("translation" in text), (
                f"theory_translation query {query.query_id} must reference theory/axis "
                f"terms; got: {text!r}"
            )


# ---------- backward-compatibility view --------------------------------


class TestLegacyView:
    def test_shape_matches_research_queries_schema(
        self, loaded_protocol: LiveQueryProtocol
    ) -> None:
        legacy = loaded_protocol.to_legacy_query_groups()
        assert "query_groups" in legacy
        assert isinstance(legacy["query_groups"], dict)
        for slug, group in legacy["query_groups"].items():
            assert set(group.keys()) == {"label", "description", "queries"}
            assert isinstance(group["queries"], list)
            assert all(isinstance(q, str) for q in group["queries"])

    def test_slugs_and_labels_parity_with_research_queries_yml(
        self, loaded_protocol: LiveQueryProtocol
    ) -> None:
        legacy_new = loaded_protocol.to_legacy_query_groups()["query_groups"]
        legacy_old = yaml.safe_load(LEGACY_QUERIES_PATH.read_text(encoding="utf-8"))[
            "query_groups"
        ]
        assert set(legacy_new.keys()) == set(legacy_old.keys())
        for slug, group in legacy_old.items():
            assert legacy_new[slug]["label"] == group["label"]

    def test_all_legacy_core_queries_preserved_verbatim(
        self, loaded_protocol: LiveQueryProtocol
    ) -> None:
        """The 3 queries per sector in `research_queries.yml` must appear
        verbatim among the new protocol's queries for that sector."""
        legacy_new = loaded_protocol.to_legacy_query_groups()["query_groups"]
        legacy_old = yaml.safe_load(LEGACY_QUERIES_PATH.read_text(encoding="utf-8"))[
            "query_groups"
        ]
        for slug, group in legacy_old.items():
            new_queries = set(legacy_new[slug]["queries"])
            missing = set(group["queries"]) - new_queries
            assert not missing, (
                f"sector {slug}: legacy queries missing from new protocol: {missing}"
            )


# ---------- loader validation --------------------------------------------


class TestLoaderValidation:
    def test_missing_file_raises_file_not_found(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            load_live_query_protocol(tmp_path / "does_not_exist.yml")

    def test_invalid_yaml_raises_protocol_error(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.yml"
        path.write_text(": this is not: valid: yaml: [", encoding="utf-8")
        with pytest.raises(LiveQueryProtocolError):
            load_live_query_protocol(path)

    def test_non_mapping_top_level_rejected(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.yml"
        path.write_text("- just\n- a\n- list\n", encoding="utf-8")
        with pytest.raises(LiveQueryProtocolError, match="top-level"):
            load_live_query_protocol(path)

    def test_missing_protocol_version_rejected(self, tmp_path: Path) -> None:
        payload = _minimal_valid_document()
        del payload["protocol_version"]
        path = _write_yaml(tmp_path, payload)
        with pytest.raises(LiveQueryProtocolError, match="protocol_version"):
            load_live_query_protocol(path)

    def test_missing_sectors_rejected(self, tmp_path: Path) -> None:
        payload = _minimal_valid_document()
        del payload["sectors"]
        path = _write_yaml(tmp_path, payload)
        with pytest.raises(LiveQueryProtocolError, match="sectors"):
            load_live_query_protocol(path)

    def test_missing_hypotheses_rejected(self, tmp_path: Path) -> None:
        payload = _minimal_valid_document()
        del payload["hypotheses"]
        path = _write_yaml(tmp_path, payload)
        with pytest.raises(LiveQueryProtocolError, match="hypotheses"):
            load_live_query_protocol(path)

    def test_empty_sectors_rejected(self, tmp_path: Path) -> None:
        payload = _minimal_valid_document(sectors={})
        path = _write_yaml(tmp_path, payload)
        with pytest.raises(LiveQueryProtocolError, match="at least one"):
            load_live_query_protocol(path)

    def test_incomplete_family_declaration_rejected(self, tmp_path: Path) -> None:
        payload = _minimal_valid_document()
        payload["query_families"] = ["core_sector", "competence_demand"]
        path = _write_yaml(tmp_path, payload)
        with pytest.raises(LiveQueryProtocolError, match="query_families"):
            load_live_query_protocol(path)

    def test_unknown_axis_target_rejected(self, tmp_path: Path) -> None:
        sector = _minimal_valid_sector()
        sector["queries"][0]["axis_target"] = "NOT_AN_AXIS"
        payload = _minimal_valid_document(sectors={"blue_biotech": sector})
        path = _write_yaml(tmp_path, payload)
        with pytest.raises(LiveQueryProtocolError, match="unknown axis"):
            load_live_query_protocol(path)

    def test_unknown_axis_primary_rejected(self, tmp_path: Path) -> None:
        sector = _minimal_valid_sector()
        sector["axis_primary"] = "NOT_AN_AXIS"
        payload = _minimal_valid_document(sectors={"blue_biotech": sector})
        path = _write_yaml(tmp_path, payload)
        with pytest.raises(LiveQueryProtocolError, match="unknown axis"):
            load_live_query_protocol(path)

    def test_unknown_query_family_rejected(self, tmp_path: Path) -> None:
        sector = _minimal_valid_sector()
        sector["queries"][0]["query_family"] = "not_a_real_family"
        payload = _minimal_valid_document(sectors={"blue_biotech": sector})
        path = _write_yaml(tmp_path, payload)
        with pytest.raises(LiveQueryProtocolError, match="query_family"):
            load_live_query_protocol(path)

    def test_family_minimum_violation_rejected(self, tmp_path: Path) -> None:
        sector = _minimal_valid_sector()
        # Drop one core_sector query, leaving 2 < required 3
        sector["queries"] = [
            q for q in sector["queries"] if q["query_family"] != "core_sector"
        ] + [_minimal_query("blue_biotech", LiveQueryFamily.CORE_SECTOR, 0),
             _minimal_query("blue_biotech", LiveQueryFamily.CORE_SECTOR, 1)]
        payload = _minimal_valid_document(sectors={"blue_biotech": sector})
        path = _write_yaml(tmp_path, payload)
        with pytest.raises(LiveQueryProtocolError, match="core_sector"):
            load_live_query_protocol(path)

    def test_duplicate_query_id_across_sectors_rejected(self, tmp_path: Path) -> None:
        sector_a = _minimal_valid_sector(slug="blue_biotech", label="Blue Biotech")
        sector_b = _minimal_valid_sector(slug="ship_repair", label="Ship Repair")
        sector_b["queries"][0]["query_id"] = sector_a["queries"][0]["query_id"]
        sector_b["queries"][0]["sector_slug"] = "ship_repair"
        payload = _minimal_valid_document(
            sectors={"blue_biotech": sector_a, "ship_repair": sector_b}
        )
        path = _write_yaml(tmp_path, payload)
        with pytest.raises(LiveQueryProtocolError, match="duplicate query_id"):
            load_live_query_protocol(path)

    def test_sector_slug_mismatch_rejected(self, tmp_path: Path) -> None:
        sector = _minimal_valid_sector()
        sector["queries"][0]["sector_slug"] = "wrong_slug"
        payload = _minimal_valid_document(sectors={"blue_biotech": sector})
        path = _write_yaml(tmp_path, payload)
        with pytest.raises(LiveQueryProtocolError, match="does not match"):
            load_live_query_protocol(path)

    def test_time_window_from_year_after_to_year_rejected(
        self, tmp_path: Path
    ) -> None:
        sector = _minimal_valid_sector()
        sector["queries"][0]["time_window"] = {"from_year": 2026, "to_year": 2019}
        payload = _minimal_valid_document(sectors={"blue_biotech": sector})
        path = _write_yaml(tmp_path, payload)
        with pytest.raises(LiveQueryProtocolError, match="from_year"):
            load_live_query_protocol(path)

    def test_non_positive_pages_rejected(self, tmp_path: Path) -> None:
        sector = _minimal_valid_sector()
        sector["queries"][0]["sampling_strategy"]["pages"] = 0
        payload = _minimal_valid_document(sectors={"blue_biotech": sector})
        path = _write_yaml(tmp_path, payload)
        with pytest.raises(LiveQueryProtocolError, match="pages"):
            load_live_query_protocol(path)

    def test_empty_expected_signal_rejected(self, tmp_path: Path) -> None:
        sector = _minimal_valid_sector()
        sector["queries"][0]["expected_signal"] = []
        payload = _minimal_valid_document(sectors={"blue_biotech": sector})
        path = _write_yaml(tmp_path, payload)
        with pytest.raises(LiveQueryProtocolError, match="expected_signal"):
            load_live_query_protocol(path)

    def test_missing_required_query_field_rejected(self, tmp_path: Path) -> None:
        sector = _minimal_valid_sector()
        del sector["queries"][0]["query_text"]
        payload = _minimal_valid_document(sectors={"blue_biotech": sector})
        path = _write_yaml(tmp_path, payload)
        with pytest.raises(LiveQueryProtocolError, match="query_text"):
            load_live_query_protocol(path)


# ---------- successful minimal parse ------------------------------------


class TestSuccessfulParse:
    def test_minimal_valid_document_parses(self, tmp_path: Path) -> None:
        payload = _minimal_valid_document()
        path = _write_yaml(tmp_path, payload)
        protocol = load_live_query_protocol(path)
        assert protocol.protocol_version == "1.0.0"
        assert len(protocol.sectors) == 1
        sector = protocol.sectors["blue_biotech"]
        assert isinstance(sector, LiveQuerySector)
        assert sector.axis_primary is BlueDynamicsAxis.MARINE
        assert len(sector.queries) == 10
        # 3 + 2 + 2 + 1 + 1 + 1 grouping
        grouped = sector.queries_by_family()
        assert len(grouped[LiveQueryFamily.CORE_SECTOR]) == 3
        assert len(grouped[LiveQueryFamily.COMPETENCE_DEMAND]) == 2
        assert len(grouped[LiveQueryFamily.EMERGING_DEMAND]) == 2
        assert len(grouped[LiveQueryFamily.VALIDATION_EQF_TRANSLATION]) == 1
        assert len(grouped[LiveQueryFamily.HYPOTHESIS_VERIFICATION]) == 1
        assert len(grouped[LiveQueryFamily.THEORY_TRANSLATION]) == 1

    def test_query_records_have_typed_fields(self, tmp_path: Path) -> None:
        payload = _minimal_valid_document()
        path = _write_yaml(tmp_path, payload)
        protocol = load_live_query_protocol(path)
        query = protocol.sectors["blue_biotech"].queries[0]
        assert isinstance(query, LiveQuery)
        assert isinstance(query.axis_target, BlueDynamicsAxis)
        assert isinstance(query.query_family, LiveQueryFamily)
        assert query.time_window.from_year == 2019
        assert query.time_window.to_year == 2026
        assert query.sort_strategy.crossref == "published-desc"
        assert query.sampling_strategy.pages == 3
        assert query.expected_signal == ["competence_demand"]
        assert query.hypothesis_targets == ()
        assert query.theory_terms == ()

    def test_load_accepts_string_path(self, tmp_path: Path) -> None:
        payload = _minimal_valid_document()
        path = _write_yaml(tmp_path, payload)
        # Passing a str, not a Path
        protocol = load_live_query_protocol(str(path))
        assert isinstance(protocol, LiveQueryProtocol)


# ---------- helper: docstring example -----------------------------------


def test_module_docstring_documents_public_surface() -> None:
    """Guard that the module docstring keeps mentioning the public API names."""
    from src.scientific_sources import live_query_protocol as mod
    doc = mod.__doc__ or ""
    for name in (
        "LiveQueryFamily",
        "LiveQuery",
        "LiveQuerySector",
        "LiveQueryProtocol",
        "LiveQueryProtocolError",
        "load_live_query_protocol",
    ):
        assert name in doc, f"module docstring should mention {name}"


def test_textwrap_import_unused_but_module_health() -> None:
    """Regression guard: textwrap import in tests remains available for future
    tests; presence must not fail the collection phase."""
    assert textwrap.dedent("x") == "x"
