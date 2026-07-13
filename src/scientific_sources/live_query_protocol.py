"""Loader and validator for `config/live_query_protocol.yml` (PR-190 / Layer 0).

The live query protocol registry is the structured successor to
`config/research_queries.yml`. This module parses the YAML file into typed
dataclasses, enforces the per-family minimums that the PR-190 specification
requires, and offers a backward-compatibility view (`to_legacy_query_groups`)
that renders the protocol into the exact shape consumed by
`scripts/export_live_research_records.py`.

The legacy `config/research_queries.yml` file MUST remain in place unchanged;
this module is additive and does not modify or replace it.

Public surface:
    - LiveQueryFamily       : allowed query-family names
    - LiveQuery             : one query record
    - LiveQuerySector       : one sector's block of queries
    - LiveQueryProtocol     : whole protocol registry
    - LiveQueryProtocolError: raised on any validation failure
    - load_live_query_protocol(path) -> LiveQueryProtocol
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence, Union

import yaml  # type: ignore[import-untyped]

from src.core import BlueDynamicsAxis


REQUIRED_QUERY_FIELDS = (
    "query_id",
    "sector",
    "sector_slug",
    "axis_target",
    "query_text",
    "query_family",
    "evidence_intent",
    "time_window",
    "sort_strategy",
    "sampling_strategy",
    "expected_signal",
)

REQUIRED_TIME_WINDOW_FIELDS = ("from_year", "to_year")
REQUIRED_SORT_STRATEGY_FIELDS = ("crossref", "scopus", "wos")
REQUIRED_SAMPLING_STRATEGY_FIELDS = (
    "mode",
    "pages",
    "rows_per_page",
    "dedupe_key",
)


class LiveQueryFamily(str, Enum):
    """Allowed query families in the live query protocol."""

    CORE_SECTOR = "core_sector"
    COMPETENCE_DEMAND = "competence_demand"
    EMERGING_DEMAND = "emerging_demand"
    VALIDATION_EQF_TRANSLATION = "validation_eqf_translation"
    HYPOTHESIS_VERIFICATION = "hypothesis_verification"
    THEORY_TRANSLATION = "theory_translation"


# Per-family minimums a sector must satisfy. PR-190 specification:
#   - at least 3 core sector queries
#   - at least 2 competence-demand queries
#   - at least 2 emerging-demand queries
#   - at least 1 validation/EQF translation query
#   - at least 1 hypothesis-verification query
#   - at least 1 theory-translation query
FAMILY_MINIMUMS: Dict[LiveQueryFamily, int] = {
    LiveQueryFamily.CORE_SECTOR: 3,
    LiveQueryFamily.COMPETENCE_DEMAND: 2,
    LiveQueryFamily.EMERGING_DEMAND: 2,
    LiveQueryFamily.VALIDATION_EQF_TRANSLATION: 1,
    LiveQueryFamily.HYPOTHESIS_VERIFICATION: 1,
    LiveQueryFamily.THEORY_TRANSLATION: 1,
}


class LiveQueryProtocolError(ValueError):
    """Raised when the live query protocol file fails schema or minimum checks."""


@dataclass(frozen=True)
class TimeWindow:
    """Temporal window applied to a provider search."""

    from_year: int
    to_year: int


@dataclass(frozen=True)
class SortStrategy:
    """Per-provider result ordering hints."""

    crossref: str
    scopus: str
    wos: str


@dataclass(frozen=True)
class SamplingStrategy:
    """Provider paging and dedupe strategy for one query."""

    mode: str
    pages: int
    rows_per_page: int
    dedupe_key: str


@dataclass(frozen=True)
class LiveQuery:
    """A single live query protocol record."""

    query_id: str
    sector: str
    sector_slug: str
    axis_target: BlueDynamicsAxis
    query_text: str
    query_family: LiveQueryFamily
    evidence_intent: str
    time_window: TimeWindow
    sort_strategy: SortStrategy
    sampling_strategy: SamplingStrategy
    expected_signal: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class LiveQuerySector:
    """A sector-scoped block of live query records."""

    slug: str
    label: str
    description: str
    axis_primary: BlueDynamicsAxis
    queries: List[LiveQuery] = field(default_factory=list)

    def queries_by_family(
        self,
    ) -> Dict[LiveQueryFamily, List[LiveQuery]]:
        """Group this sector's queries by their declared family."""
        grouped: Dict[LiveQueryFamily, List[LiveQuery]] = {
            family: [] for family in LiveQueryFamily
        }
        for query in self.queries:
            grouped[query.query_family].append(query)
        return grouped


@dataclass(frozen=True)
class LiveQueryProtocol:
    """Parsed and validated live query protocol registry."""

    protocol_version: str
    query_families: List[LiveQueryFamily]
    sectors: Dict[str, LiveQuerySector]

    def all_queries(self) -> List[LiveQuery]:
        """Return every query across every sector as a flat list."""
        return [q for sector in self.sectors.values() for q in sector.queries]

    def flattened_query_texts(self) -> List[str]:
        """Return flattened query text list in deterministic protocol order."""
        return [q.query_text for q in self.all_queries()]

    def to_legacy_query_groups(self) -> Dict[str, Dict[str, Any]]:
        """Render the protocol into the shape consumed by
        `scripts/export_live_research_records.py`.

        Returns::

            {
                "query_groups": {
                    "<sector_slug>": {
                        "label":       str,
                        "description": str,
                        "queries":     [str, str, ...],
                    },
                    ...
                }
            }

        Only the ``query_text`` field is emitted per query, matching the
        legacy ``config/research_queries.yml`` contract exactly.
        """
        query_groups: Dict[str, Dict[str, Any]] = {}
        for slug, sector in self.sectors.items():
            query_groups[slug] = {
                "label": sector.label,
                "description": sector.description,
                "queries": [q.query_text for q in sector.queries],
            }
        return {"query_groups": query_groups}


def _require_mapping(value: Any, ctx: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise LiveQueryProtocolError(f"{ctx}: expected a mapping, got {type(value).__name__}")
    return value


def _require_sequence(value: Any, ctx: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise LiveQueryProtocolError(f"{ctx}: expected a sequence, got {type(value).__name__}")
    return value


def _require_non_empty_str(value: Any, ctx: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LiveQueryProtocolError(f"{ctx}: expected a non-empty string")
    return value


def _require_int(value: Any, ctx: str) -> int:
    # Reject booleans explicitly (bool is a subclass of int in Python).
    if isinstance(value, bool) or not isinstance(value, int):
        raise LiveQueryProtocolError(f"{ctx}: expected an integer, got {type(value).__name__}")
    return int(value)


def _parse_axis(value: Any, ctx: str) -> BlueDynamicsAxis:
    if not isinstance(value, str):
        raise LiveQueryProtocolError(f"{ctx}: axis must be a string")
    try:
        return BlueDynamicsAxis[value]
    except KeyError as exc:
        valid = ", ".join(a.name for a in BlueDynamicsAxis)
        raise LiveQueryProtocolError(
            f"{ctx}: unknown axis '{value}'. Valid axes: {valid}"
        ) from exc


def _parse_family(value: Any, ctx: str) -> LiveQueryFamily:
    if not isinstance(value, str):
        raise LiveQueryProtocolError(f"{ctx}: query_family must be a string")
    try:
        return LiveQueryFamily(value)
    except ValueError as exc:
        valid = ", ".join(f.value for f in LiveQueryFamily)
        raise LiveQueryProtocolError(
            f"{ctx}: unknown query_family '{value}'. Valid families: {valid}"
        ) from exc


def _parse_time_window(payload: Any, ctx: str) -> TimeWindow:
    mapping = _require_mapping(payload, ctx)
    for field_name in REQUIRED_TIME_WINDOW_FIELDS:
        if field_name not in mapping:
            raise LiveQueryProtocolError(f"{ctx}: missing time_window field '{field_name}'")
    from_year = _require_int(mapping["from_year"], f"{ctx}.from_year")
    to_year = _require_int(mapping["to_year"], f"{ctx}.to_year")
    if from_year > to_year:
        raise LiveQueryProtocolError(
            f"{ctx}: from_year ({from_year}) must not exceed to_year ({to_year})"
        )
    return TimeWindow(from_year=from_year, to_year=to_year)


def _parse_sort_strategy(payload: Any, ctx: str) -> SortStrategy:
    mapping = _require_mapping(payload, ctx)
    for field_name in REQUIRED_SORT_STRATEGY_FIELDS:
        if field_name not in mapping:
            raise LiveQueryProtocolError(f"{ctx}: missing sort_strategy field '{field_name}'")
    return SortStrategy(
        crossref=_require_non_empty_str(mapping["crossref"], f"{ctx}.crossref"),
        scopus=_require_non_empty_str(mapping["scopus"], f"{ctx}.scopus"),
        wos=_require_non_empty_str(mapping["wos"], f"{ctx}.wos"),
    )


def _parse_sampling_strategy(payload: Any, ctx: str) -> SamplingStrategy:
    mapping = _require_mapping(payload, ctx)
    for field_name in REQUIRED_SAMPLING_STRATEGY_FIELDS:
        if field_name not in mapping:
            raise LiveQueryProtocolError(f"{ctx}: missing sampling_strategy field '{field_name}'")
    pages = _require_int(mapping["pages"], f"{ctx}.pages")
    rows_per_page = _require_int(mapping["rows_per_page"], f"{ctx}.rows_per_page")
    if pages <= 0:
        raise LiveQueryProtocolError(f"{ctx}.pages: must be positive, got {pages}")
    if rows_per_page <= 0:
        raise LiveQueryProtocolError(
            f"{ctx}.rows_per_page: must be positive, got {rows_per_page}"
        )
    return SamplingStrategy(
        mode=_require_non_empty_str(mapping["mode"], f"{ctx}.mode"),
        pages=pages,
        rows_per_page=rows_per_page,
        dedupe_key=_require_non_empty_str(mapping["dedupe_key"], f"{ctx}.dedupe_key"),
    )


def _parse_expected_signal(payload: Any, ctx: str) -> List[str]:
    seq = _require_sequence(payload, ctx)
    if not seq:
        raise LiveQueryProtocolError(f"{ctx}: expected_signal must not be empty")
    signals: List[str] = []
    for idx, item in enumerate(seq):
        signals.append(_require_non_empty_str(item, f"{ctx}[{idx}]"))
    return signals


def _parse_query(payload: Any, ctx: str, sector_slug: str) -> LiveQuery:
    mapping = _require_mapping(payload, ctx)
    for field_name in REQUIRED_QUERY_FIELDS:
        if field_name not in mapping:
            raise LiveQueryProtocolError(f"{ctx}: missing required field '{field_name}'")

    declared_slug = _require_non_empty_str(mapping["sector_slug"], f"{ctx}.sector_slug")
    if declared_slug != sector_slug:
        raise LiveQueryProtocolError(
            f"{ctx}.sector_slug: declared '{declared_slug}' does not match containing "
            f"sector '{sector_slug}'"
        )

    return LiveQuery(
        query_id=_require_non_empty_str(mapping["query_id"], f"{ctx}.query_id"),
        sector=_require_non_empty_str(mapping["sector"], f"{ctx}.sector"),
        sector_slug=declared_slug,
        axis_target=_parse_axis(mapping["axis_target"], f"{ctx}.axis_target"),
        query_text=_require_non_empty_str(mapping["query_text"], f"{ctx}.query_text"),
        query_family=_parse_family(mapping["query_family"], f"{ctx}.query_family"),
        evidence_intent=_require_non_empty_str(
            mapping["evidence_intent"], f"{ctx}.evidence_intent"
        ),
        time_window=_parse_time_window(mapping["time_window"], f"{ctx}.time_window"),
        sort_strategy=_parse_sort_strategy(mapping["sort_strategy"], f"{ctx}.sort_strategy"),
        sampling_strategy=_parse_sampling_strategy(
            mapping["sampling_strategy"], f"{ctx}.sampling_strategy"
        ),
        expected_signal=_parse_expected_signal(
            mapping["expected_signal"], f"{ctx}.expected_signal"
        ),
    )


def _parse_sector(slug: str, payload: Any) -> LiveQuerySector:
    ctx = f"sectors.{slug}"
    mapping = _require_mapping(payload, ctx)
    for field_name in ("label", "description", "axis_primary", "queries"):
        if field_name not in mapping:
            raise LiveQueryProtocolError(f"{ctx}: missing required field '{field_name}'")

    queries_payload = _require_sequence(mapping["queries"], f"{ctx}.queries")
    queries = [
        _parse_query(item, f"{ctx}.queries[{idx}]", slug)
        for idx, item in enumerate(queries_payload)
    ]

    sector = LiveQuerySector(
        slug=slug,
        label=_require_non_empty_str(mapping["label"], f"{ctx}.label"),
        description=_require_non_empty_str(mapping["description"], f"{ctx}.description"),
        axis_primary=_parse_axis(mapping["axis_primary"], f"{ctx}.axis_primary"),
        queries=queries,
    )

    grouped = sector.queries_by_family()
    for family, minimum in FAMILY_MINIMUMS.items():
        count = len(grouped[family])
        if count < minimum:
            raise LiveQueryProtocolError(
                f"{ctx}: family '{family.value}' has {count} queries; "
                f"PR-190 requires at least {minimum}"
            )

    return sector


def _validate_unique_query_ids(sectors: Dict[str, LiveQuerySector]) -> None:
    seen: Dict[str, str] = {}
    for slug, sector in sectors.items():
        for query in sector.queries:
            existing_slug = seen.get(query.query_id)
            if existing_slug is not None:
                raise LiveQueryProtocolError(
                    f"duplicate query_id '{query.query_id}' in sectors "
                    f"'{existing_slug}' and '{slug}'"
                )
            seen[query.query_id] = slug


def load_live_query_protocol(path: Union[str, Path]) -> LiveQueryProtocol:
    """Parse and validate a live query protocol YAML file.

    Args:
        path: Path to the protocol YAML file (typically
            ``config/live_query_protocol.yml``).

    Returns:
        A validated ``LiveQueryProtocol`` instance.

    Raises:
        FileNotFoundError: if the file does not exist.
        LiveQueryProtocolError: on any schema, family-minimum, or uniqueness
            violation.
    """
    protocol_path = Path(path)
    if not protocol_path.is_file():
        raise FileNotFoundError(f"Live query protocol file not found: {protocol_path}")

    try:
        payload = yaml.safe_load(protocol_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise LiveQueryProtocolError(
            f"{protocol_path}: invalid YAML: {exc}"
        ) from exc

    if not isinstance(payload, Mapping):
        raise LiveQueryProtocolError(
            f"{protocol_path}: top-level YAML must be a mapping"
        )

    for field_name in ("protocol_version", "query_families", "sectors"):
        if field_name not in payload:
            raise LiveQueryProtocolError(
                f"{protocol_path}: missing top-level field '{field_name}'"
            )

    protocol_version = _require_non_empty_str(
        payload["protocol_version"], "protocol_version"
    )

    families_payload = _require_sequence(payload["query_families"], "query_families")
    families: List[LiveQueryFamily] = []
    for idx, item in enumerate(families_payload):
        families.append(_parse_family(item, f"query_families[{idx}]"))
    if set(families) != set(LiveQueryFamily):
        expected = ", ".join(f.value for f in LiveQueryFamily)
        raise LiveQueryProtocolError(
            f"query_families must declare exactly: {expected}"
        )

    sectors_payload = _require_mapping(payload["sectors"], "sectors")
    if not sectors_payload:
        raise LiveQueryProtocolError("sectors: must contain at least one sector")

    sectors: Dict[str, LiveQuerySector] = {}
    for slug, sector_payload in sectors_payload.items():
        if not isinstance(slug, str) or not slug.strip():
            raise LiveQueryProtocolError(f"sectors: invalid sector slug '{slug!r}'")
        sectors[slug] = _parse_sector(slug, sector_payload)

    _validate_unique_query_ids(sectors)

    return LiveQueryProtocol(
        protocol_version=protocol_version,
        query_families=families,
        sectors=sectors,
    )


def validate_legacy_projection_matches_protocol(
    protocol: LiveQueryProtocol,
    projection: Mapping[str, Any],
) -> None:
    """Fail when a legacy query_groups projection diverges from protocol queries."""
    query_groups = projection.get("query_groups")
    if not isinstance(query_groups, Mapping):
        raise LiveQueryProtocolError("projection must contain mapping key 'query_groups'")

    protocol_texts = protocol.flattened_query_texts()
    projected_texts: List[str] = []
    for _slug, group in query_groups.items():
        if not isinstance(group, Mapping):
            raise LiveQueryProtocolError("projection.query_groups entries must be mappings")
        queries = group.get("queries")
        if not isinstance(queries, Sequence) or isinstance(queries, (str, bytes)):
            raise LiveQueryProtocolError("projection.query_groups.*.queries must be a sequence")
        projected_texts.extend([_require_non_empty_str(q, "projection.query_text") for q in queries])

    if len(projected_texts) != len(protocol_texts):
        raise LiveQueryProtocolError(
            "projection query count mismatch: "
            f"{len(projected_texts)} projected != {len(protocol_texts)} protocol"
        )
    if projected_texts != protocol_texts:
        raise LiveQueryProtocolError(
            "projection query-text mismatch: projected query order/text does not "
            "exactly match config/live_query_protocol.yml"
        )
