from __future__ import annotations

"""Tests for pre-acquisition protocol completeness assertion."""

from scripts.export_live_research_records import validate_protocol_completeness

QueryGroups = dict[str, dict[str, str | list[str]]]


def _make_query_groups(
    n_sectors: int = 12, n_queries_per_sector: int = 10
) -> QueryGroups:
    """Build a mock query_groups dict with specified dimensions."""
    groups: QueryGroups = {}
    for sector_index in range(n_sectors):
        slug = f"sector_{sector_index}"
        groups[slug] = {
            "label": f"Sector {sector_index}",
            "queries": [
                f"query_{sector_index}_{query_index}"
                for query_index in range(n_queries_per_sector)
            ],
        }
    return groups


def _make_constraints(
    query_groups: QueryGroups,
    families: list[str] | None = None,
) -> dict[str, dict[str, str]]:
    """Build constraints keyed by lowercased query text."""
    if families is None:
        families = [
            "core_sector",
            "core_sector",
            "core_sector",
            "competence_demand",
            "competence_demand",
            "emerging_demand",
            "emerging_demand",
            "validation_eqf_translation",
            "hypothesis_verification",
            "theory_translation",
        ]
    constraints: dict[str, dict[str, str]] = {}
    for slug, sector_data in query_groups.items():
        queries = sector_data["queries"]
        assert isinstance(queries, list)
        for index, query in enumerate(queries):
            family = families[index] if index < len(families) else "core_sector"
            qid = f"Q_{slug.upper()}_{family.upper()}_{index + 1:03d}"
            constraints[str(query).lower()] = {
                "query_id": qid,
                "query_text": str(query),
                "sector_slug": slug,
                "query_family": family,
            }
    return constraints


class TestProtocolCompletenessAssertion:
    def test_valid_120_query_protocol_passes(self) -> None:
        groups = _make_query_groups(12, 10)
        constraints = _make_constraints(groups)
        errors = validate_protocol_completeness(groups, constraints)
        assert errors == []

    def test_119_queries_fails_before_acquisition(self) -> None:
        groups = _make_query_groups(12, 10)
        first_sector = list(groups.keys())[0]
        queries = groups[first_sector]["queries"]
        assert isinstance(queries, list)
        groups[first_sector]["queries"] = queries[:9]
        constraints = _make_constraints(groups)
        errors = validate_protocol_completeness(groups, constraints)
        assert errors
        assert any("120" in error or "query" in error.lower() for error in errors)

    def test_11_sectors_fails(self) -> None:
        groups = _make_query_groups(11, 10)
        constraints = _make_constraints(groups)
        errors = validate_protocol_completeness(groups, constraints)
        assert errors
        assert any("12" in error or "sector" in error.lower() for error in errors)

    def test_missing_query_family_fails(self) -> None:
        groups = _make_query_groups(12, 10)
        constraints = _make_constraints(groups, families=["core_sector"] * 10)
        errors = validate_protocol_completeness(groups, constraints)
        assert errors
        assert any("family" in error.lower() for error in errors)

    def test_duplicate_query_id_fails(self) -> None:
        groups = _make_query_groups(12, 10)
        constraints = _make_constraints(groups)
        keys = list(constraints.keys())
        constraints[keys[1]]["query_id"] = constraints[keys[0]]["query_id"]
        errors = validate_protocol_completeness(groups, constraints)
        assert errors
        assert any("duplicate" in error.lower() for error in errors)
