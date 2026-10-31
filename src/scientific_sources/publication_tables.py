"""Versioned descriptive publication tables from retained, unmodified CSVs.

The primary table counts distinct evidence/sector/axis associations supported by
semantic signals. It does not count validated capabilities or infer supply.
"""
from __future__ import annotations

import csv
import hashlib
import html
import io
import json
import math
import re
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml  # type: ignore[import-untyped]

VERSION = "1.0.0"
AXES = {"MARINE": "M", "MARITIME": "T", "OCEANIC": "O", "HYDRONIZATION": "H"}
ROOT = Path(__file__).resolve().parents[2]
KEYS = {
    "evidence_records": "evidence_id",
    "evidence_occurrences": "occurrence_pk",
    "evidence_fragments": "fragment_id",
    "semantic_signals": "signal_id",
    "competence_demand_signals": "signal_id",
    "competence_candidates": "candidate_id",
    "canonical_competences": "canonical_competence_id",
    "sector_competence_assignments": "assignment_id",
    "validation_decisions": "validation_decision_id",
    "derived_competence_demands": "competence_demand_id",
    "credential_translation_eqf4_7": "credential_id",
    "learning_outcomes": "outcome_id",
    "hypothesis_semantic_fragments": "fragment_id",
    "sector_axis_gap_model": "sector|axis_group",
    "run_novelty_metrics": "current_run_id",
    "VARIABLE_LABELS": "variable_name",
    "VALUE_LABELS": "variable_name|value_code",
}
INTEGER_FIELDS = {
    "year", "citation_count", "provider_count", "record_recurrence_count",
    "span_start_offset", "span_end_offset", "exact_span_start_offset",
    "exact_span_end_offset", "eqf_level", "evidence_record_count",
    "unique_doi_count", "record_occurrence_count", "query_count",
}
REAL_FIELDS = {
    "confidence_score", "demand_strength_score", "provider_diversity_score",
    "query_diversity_score", "temporal_recency_score", "semantic_confidence_mean",
    "cross_sector_recurrence_score", "ects",
}
RELATIONS = (
    ("semantic_signals", "evidence_id", "evidence_records", "evidence_id"),
    ("competence_demand_signals", "evidence_id", "evidence_records", "evidence_id"),
    ("evidence_fragments", "evidence_id", "evidence_records", "evidence_id"),
    ("semantic_signals", "fragment_id", "evidence_fragments", "fragment_id"),
    ("competence_candidates", "signal_id|fragment_id", "semantic_signals", "signal_id|fragment_id"),
    ("competence_candidates", "fragment_id", "evidence_fragments", "fragment_id"),
    ("competence_candidates", "evidence_id", "evidence_records", "evidence_id"),
    ("canonical_competences", "source_candidate_id", "competence_candidates", "candidate_id"),
    ("canonical_competences", "validation_decision_id", "validation_decisions", "validation_decision_id"),
    ("sector_competence_assignments", "canonical_competence_id", "canonical_competences", "canonical_competence_id"),
    ("sector_competence_assignments", "validation_decision_id", "validation_decisions", "validation_decision_id"),
    ("validation_decisions", "target_candidate_id", "competence_candidates", "candidate_id"),
    ("learning_outcomes", "credential_id", "credential_translation_eqf4_7", "credential_id"),
    ("learning_outcomes", "competence_demand_id", "derived_competence_demands", "competence_demand_id"),
    ("learning_outcomes", "evidence_id", "evidence_records", "evidence_id"),
)
FILES = ("publication_tables.json", "publication_data_audit.json",
         "unit_reconciliation.csv", "sector_qmbd_publication.csv",
         "publication_metric_contract.csv", "publication_tables.html")
CELL_COLUMNS = (
    "sector", "axis_group", "axis_code", "row_kind", "observational_unit",
    "assignment_count", "unique_evidence_n", "row_denominator", "column_denominator",
    "grand_denominator", "row_pct", "column_pct", "total_pct", "missing_n",
    "excluded_signal_n", "status", "reason", "warning", "run_id",
)
UNIT_COLUMNS = (
    "metric_id", "observational_unit", "value", "n", "missing_n",
    "missing_n_reason", "status", "reason", "source", "run_id",
)
METRIC_COLUMNS = (
    "metric_id", "observational_unit", "numerator", "denominator",
    "eligible_population", "n_definition", "missing_n_definition", "exclusions",
    "formula", "source", "run_id",
)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"


def _number(raw: str, field: str) -> Tuple[Optional[float], str]:
    """Strict parsing: unavailable and invalid tokens never become zero."""
    text = raw.strip()
    if not text or text.lower() in {"null", "none", "na", "n/a", "unknown"} or text.startswith("not_computable"):
        return None, "missing"
    if field in INTEGER_FIELDS and not re.fullmatch(r"[+-]?\d+", text):
        return None, "invalid"
    if field in INTEGER_FIELDS:
        integer = int(text)
        return (integer, "valid") if 0 <= integer <= 2**63 - 1 else (None, "invalid")
    try:
        value = float(text)
    except ValueError:
        return None, "invalid"
    if not math.isfinite(value) or value < 0:
        return None, "invalid"
    if field == "confidence_score" and value > 1:
        return None, "invalid"
    return value, "valid"


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def build_publication_tables(database_dir: Path, protocol_path: Optional[Path] = None) -> Dict[str, Any]:
    """Profile source CSVs and calculate a single reproducible publication model."""
    protocol_path = protocol_path or (
        database_dir / "retained_protocol/live_query_protocol.yml"
        if (database_dir / "retained_protocol/live_query_protocol.yml").is_file()
        else ROOT / "config/live_query_protocol.yml"
    )
    protocol = yaml.safe_load(protocol_path.read_text(encoding="utf-8"))
    sector_config = protocol.get("sectors", {}) if isinstance(protocol, dict) else {}
    sectors = sorted(sector_config) if isinstance(sector_config, dict) else []
    manifests = {name: _load(database_dir / name) for name in (
        "cumulative_database_manifest.json", "run_novelty_metrics.json",
        "layer4_manifest.json", "layer5_manifest.json",
    )}
    if any(not isinstance(value, dict) for value in manifests.values()):
        raise ValueError("publication_manifest_must_be_object")
    binding = manifests["cumulative_database_manifest.json"].get("protocol_binding", {})
    if binding and (not isinstance(binding, dict) or binding.get("protocol_sha256") !=
                    hashlib.sha256(protocol_path.read_bytes()).hexdigest()):
        raise ValueError("publication_protocol_binding_mismatch")
    run_ids = {str(v.get("current_run_id", "")).strip() for v in manifests.values()
               if isinstance(v, dict) and v.get("current_run_id")}
    run_id = next(iter(run_ids)) if len(run_ids) == 1 else ""
    source_version = str(manifests["cumulative_database_manifest.json"].get("schema_version", "unknown"))
    sources: Dict[str, Any] = {}
    rows: Dict[str, List[Dict[str, str]]] = {}
    headers: Dict[str, List[str]] = {}
    profiles: List[Dict[str, Any]] = []
    columns: List[Dict[str, Any]] = []
    problems: Dict[str, List[str]] = {name: [] for name in KEYS}
    for name, key in KEYS.items():
        path = database_dir / (name + ".csv")
        if not path.is_file():
            profiles.append({"table": name, "status": "unavailable", "reason": "source_not_retained"})
            continue
        data = path.read_bytes()
        sources[path.name] = hashlib.sha256(data).hexdigest()
        reader = csv.DictReader(io.StringIO(data.decode("utf-8")))
        headers[name] = list(reader.fieldnames or [])
        parsed = list(reader)
        if len(set(headers[name])) != len(headers[name]) or any(
            None in r or any(v is None for v in r.values()) for r in parsed
        ):
            raise ValueError(f"Malformed publication CSV shape: {path.name}")
        rows[name] = parsed
        key_fields = (key, "fragment_id") if name == "semantic_signals" else tuple(key.split("|"))
        counts = Counter(tuple(r.get(k, "") for k in key_fields) for r in parsed
                         if all(r.get(k, "").strip() for k in key_fields))
        missing_keys = sum(any(not r.get(k, "").strip() for k in key_fields) for r in parsed)
        duplicate_rows = sum(c - 1 for c in counts.values())
        if any(k not in headers[name] for k in key_fields):
            problems[name].append("key_column_unavailable")
        if missing_keys:
            problems[name].append("missing_key")
        if duplicate_rows:
            problems[name].append("duplicate_key")
        profiles.append({"table": name, "status": "retained", "row_count": len(parsed),
                         "key": "|".join(key_fields), "missing_key_n": missing_keys,
                         "duplicate_key_rows": duplicate_rows,
                         "exact_duplicate_rows": len(parsed) - len({tuple(sorted(r.items())) for r in parsed})})
        for field in headers[name]:
            typ = "INTEGER" if field in INTEGER_FIELDS else "REAL" if field in REAL_FIELDS else "TEXT"
            states = Counter(_number(r[field], field)[1] if typ != "TEXT"
                             else "missing" if not r[field].strip() else "valid" for r in parsed)
            columns.append({"table": name, "column": field, "declared_analytical_type": typ,
                            "physical_source_type": "CSV text", "n": len(parsed),
                            "missing_n": states["missing"], "invalid_n": states["invalid"]})
    for name in manifests:
        path = database_dir / name
        if path.is_file():
            sources[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    relations: List[Dict[str, Any]] = []
    for child, field, parent, parent_key in RELATIONS:
        item: Dict[str, Any] = {"child": child, "field": field, "parent": parent, "parent_key": parent_key}
        child_fields, parent_fields = field.split("|"), parent_key.split("|")
        if (child not in rows or parent not in rows
                or any(f not in headers[child] for f in child_fields)
                or any(f not in headers[parent] for f in parent_fields)):
            item.update(status="unavailable", reason="table_or_join_key_not_retained")
            if rows.get(child):
                problems[child].append("unavailable_relation:" + field)
        else:
            parent_counts = Counter(tuple(r[f] for f in parent_fields) for r in rows[parent]
                                    if all(r[f] for f in parent_fields))
            child_keys = [tuple(r[f] for f in child_fields) for r in rows[child]]
            orphan = sum(all(k) and k not in parent_counts for k in child_keys)
            missing = sum(not all(k) for k in child_keys)
            joined = sum(parent_counts.get(k, 0) for k in child_keys)
            matched = sum(k in parent_counts for k in child_keys)
            item.update(status="invalid" if orphan or missing or joined != matched else "valid",
                        before_n=len(rows[child]), matched_child_n=matched,
                        inner_join_n=joined, left_join_n=joined + len(rows[child]) - matched,
                        orphan_n=orphan, missing_key_n=missing, excess_join_rows=joined - matched)
            if item["status"] == "invalid":
                problems[child].append("invalid_relation:" + field)
        relations.append(item)
    # Propagate invalid ancestry without counting joined rows as new observations.
    for _ in range(len(KEYS)):
        changed = False
        for child, field, parent, _key in RELATIONS:
            reason = "invalid_parent:" + parent
            if rows.get(child) and problems[parent] and reason not in problems[child]:
                problems[child].append(reason)
                changed = True
        if not changed:
            break
    decisions = {r.get("validation_decision_id"): r for r in rows.get("validation_decisions", [])}
    accepted_canonical = set()
    for r in rows.get("canonical_competences", []):
        decision = decisions.get(r.get("validation_decision_id"), {})
        if (r.get("validation_status") == "accepted" and r.get("provenance_guard_status") == "passed"
                and decision.get("decision_status") == "accepted"
                and decision.get("target_candidate_id") == r.get("source_candidate_id")):
            accepted_canonical.add(r.get("canonical_competence_id"))
        else:
            problems["canonical_competences"].append("unverified_canonical_validation")
    for r in rows.get("sector_competence_assignments", []):
        if (r.get("canonical_competence_id") not in accepted_canonical
                or decisions.get(r.get("validation_decision_id"), {}).get("decision_status") != "accepted"
                or problems["canonical_competences"] or problems["validation_decisions"]):
            problems["sector_competence_assignments"].append("unverified_assignment_validation")
    modern = "semantic_signals" in rows or source_version.startswith("2.")
    signal_table = "semantic_signals" if modern else "competence_demand_signals"
    evidence = {r["evidence_id"]: r for r in rows.get("evidence_records", []) if r.get("evidence_id")}
    signals = rows.get(signal_table, [])
    complete_dimensions = all(f in headers.get(signal_table, []) for f in ("sector", "axis_group", "evidence_id"))
    missing_dimensions = sum(not r.get("sector") or not r.get("axis_group") for r in signals)
    invalid_dimensions = sum(bool(r.get("sector")) and r["sector"] not in sectors or
                             bool(r.get("axis_group")) and r["axis_group"] not in AXES or
                             ("axis_code" in r and r.get("axis_code") != AXES.get(r.get("axis_group", "")))
                             for r in signals)
    eligible = [r for r in signals if r.get("evidence_id") in evidence
                and r.get("sector") in sectors and r.get("axis_group") in AXES
                and r.get("manual_review_status") != "rejected"]
    reasons = list(problems["evidence_records"] + problems[signal_table])
    if "evidence_records" not in rows or signal_table not in rows:
        reasons.append("source_not_retained")
    if not complete_dimensions:
        reasons.append("dimension_columns_unavailable")
    if invalid_dimensions:
        reasons.append("unknown_sector_or_axis")
    if not sectors:
        reasons.append("protocol_sectors_unavailable")
    if not run_id:
        reasons.append("missing_or_inconsistent_current_run_id")
    if reasons:
        eligible = []
    assignments = sorted({(r["evidence_id"], r["sector"], r["axis_group"]) for r in eligible})
    evidence_facts = [{"evidence_id": key,
                       "year": _number(r.get("year", ""), "year")[0],
                       "year_status": _number(r.get("year", ""), "year")[1]}
                      for key, r in sorted(evidence.items())]
    signal_facts = [{"signal_id": r["signal_id"], "fragment_id": r.get("fragment_id", ""),
                     "evidence_id": r["evidence_id"],
                     "sector": r["sector"], "axis_group": r["axis_group"],
                     "confidence_score": _number(r.get("confidence_score", ""), "confidence_score")[0],
                     "confidence_status": _number(r.get("confidence_score", ""), "confidence_score")[1]}
                    for r in sorted(eligible, key=lambda r: (r["signal_id"], r.get("fragment_id", "")))]
    assignment_facts = [{"evidence_id": e, "sector": s, "axis_group": a} for e, s, a in assignments]
    units: List[Dict[str, Any]] = []
    definitions: List[Dict[str, Any]] = []

    def unit(metric: str, source: str, grain: str, value: Optional[int], reason: str = "",
             missing: Optional[int] = 0, missing_reason: str = "") -> None:
        units.append(dict(zip(UNIT_COLUMNS, (
            metric, grain, value, value, missing, missing_reason,
            "computable" if value is not None else "not_computable", reason, source, run_id,
        ))))
        definitions.append(dict(zip(METRIC_COLUMNS, (
            metric, grain, "count of retained distinct unit identifiers", "not_applicable_count",
            "retained cumulative snapshot; not the entire literature", "retained counted units",
            "missing required identifiers in retained rows; absent universe is unknown", reason,
            "COUNT(DISTINCT governed identifier)", source, run_id,
        ))))

    table_units = [
        ("unique_evidence", "evidence_records", "canonical evidence record"),
        ("provider_query_occurrences", "evidence_occurrences", "provider-query occurrence"),
        ("evidence_fragments", "evidence_fragments", "retained evidence fragment"),
        ("semantic_signals", signal_table, "semantic signal"),
        ("competence_candidates", "competence_candidates", "competence candidate"),
        ("validated_canonical_competences", "canonical_competences", "accepted canonical competence"),
        ("validated_sector_assignments", "sector_competence_assignments", "canonical competence-sector-axis assignment"),
        ("legacy_demand_aggregates", "derived_competence_demands", "screening aggregate; not validated competence"),
        ("credential_design_candidates", "credential_translation_eqf4_7", "credential-design candidate"),
        ("learning_outcome_candidates", "learning_outcomes", "learning-outcome candidate"),
    ]
    for metric, table, grain in table_units:
        issue = "source_not_retained" if table not in rows else "|".join(sorted(set(problems[table])))
        counted = rows.get(table, [])
        if table == "canonical_competences":
            counted = [r for r in counted if r.get("validation_status") == "accepted"
                       and r.get("provenance_guard_status") == "passed"]
        fields = (KEYS[table], "fragment_id") if table == "semantic_signals" else (KEYS[table],)
        value = None if issue else len({tuple(r[f] for f in fields) for r in counted})
        unit(metric, table + ".csv", grain, value, issue,
             None if table not in rows else sum(any(not r.get(f) for f in fields) for r in rows[table]),
             "population_not_retained" if table not in rows else "")
        definitions[-1].update(
            numerator="distinct " + ", ".join(fields),
            formula="COUNT(DISTINCT (" + ", ".join(fields) + "))",
            exclusions=("requires accepted decision and passed provenance guard; invalid ancestry suppresses count"
                        if metric.startswith("validated_") else "invalid keys or relations suppress count"),
        )
    categories = {r["signal_type"] for r in signals if r.get("signal_type")}
    category_available = signal_table in rows and "signal_type" in headers.get(signal_table, [])
    unit("signal_categories", signal_table + ".csv", "signal type", len(categories) if category_available else None,
         "" if category_available else "source_or_field_not_retained", None,
         "missing signal rows cannot identify the number of missing distinct categories")
    unit("validated_supply_mappings", "independently validated supply registry", "validated supply mapping", None,
         "no_row_level_supply_registry_consumed; credentials are proposals", None, "population_not_retained")
    unit("screening_evidence_assignments", signal_table + ".csv", "distinct evidence-sector-axis association",
         None if reasons else len(assignments), "|".join(sorted(set(reasons))),
         None if not complete_dimensions else missing_dimensions,
         "missing dimensions counted at signal-row grain, not unknown distinct associations")
    unit("evidence_with_screening_assignment", signal_table + ".csv", "unique evidence with eligible semantic signal",
         None if reasons else len({e for e, _, _ in assignments}), "|".join(sorted(set(reasons))), None,
         "source-wide unobserved semantic coverage cannot be measured")
    for definition in definitions:
        if definition["metric_id"] in {"screening_evidence_assignments", "evidence_with_screening_assignment"}:
            definition.update(
                numerator=("distinct evidence_id, sector, axis_group" if definition["metric_id"] ==
                           "screening_evidence_assignments" else "distinct evidence_id"),
                eligible_population="retained signals with valid dimensions and evidence reference; non-rejected",
                formula="COUNT(DISTINCT eligible " + definition["observational_unit"] + ")",
                exclusions="rejected signals and missing dimensions; structural errors suppress result",
                missing_n_definition="global signal rows lacking dimensions; distinct missing units unknown",
            )
    grand = len(assignments)
    cells: List[Dict[str, Any]] = []
    pairs = [(s, a) for s in sectors for a in AXES] + [(s, "ALL") for s in sectors]
    pairs += [("ALL", a) for a in AXES] + [("ALL", "ALL")]
    for sector, axis in pairs:
        selected = [(e, s, a) for e, s, a in assignments
                    if (sector == "ALL" or s == sector) and (axis == "ALL" or a == axis)]
        count = len(selected)
        row_n = sum(sector == "ALL" or s == sector for _, s, _ in assignments)
        col_n = sum(axis == "ALL" or a == axis for _, _, a in assignments)
        status = "not_computable" if reasons or grand == 0 else "computable"
        cells.append(dict(zip(CELL_COLUMNS, (
            sector, axis, AXES.get(axis, ""), "total" if "ALL" in (sector, axis) else "cell",
            "distinct evidence-sector-axis association", None if reasons else count,
            None if reasons else len({e for e, _, _ in selected}),
            None if reasons else row_n, None if reasons else col_n, None if reasons else grand,
            round(100 * count / row_n, 6) if row_n and not reasons else None,
            round(100 * count / col_n, 6) if col_n and not reasons else None,
            round(100 * count / grand, 6) if grand and not reasons else None,
            None if not complete_dimensions else missing_dimensions, len(signals) - len(eligible),
            status, "|".join(sorted(set(reasons))) if reasons else "zero_denominator" if not grand else
            "zero_row_denominator" if not row_n else "zero_column_denominator" if not col_n else "",
            "small_cell_n_lt_5" if count < 5 and not reasons else "", run_id,
        ))))
    for metric, denominator in (("row_pct", "sector marginal association count"),
                                ("column_pct", "axis marginal association count"),
                                ("total_pct", "grand association count")):
        definitions.append(dict(zip(METRIC_COLUMNS, (
            metric, "distinct evidence-sector-axis association", "cell assignment_count", denominator,
            "retained semantic signals with valid evidence link and both dimensions; non-rejected",
            "grand number of distinct evidence/sector/axis tuples", "signal rows lacking sector or axis",
            "rejected signals; missing dimensions; structural errors suppress table",
            "100 * numerator / denominator; NULL if denominator=0",
            signal_table + ".csv; evidence_records.csv", run_id,
        ))))
    return {
        "schema_version": VERSION, "run_id": run_id, "source_schema_version": source_version,
        "scope": "retained cumulative snapshot; screening evidence associations, not validated capabilities",
        "protocol_sha256": hashlib.sha256(protocol_path.read_bytes()).hexdigest(),
        "sources_sha256": sources, "unit_reconciliation": units, "sector_qmbd": cells,
        "metric_contract": definitions,
        "audit": {"tables": profiles, "columns": columns, "relations": relations,
                  "table_blockers": sorted(set(reasons)), "missing_dimension_signal_n": missing_dimensions,
                  "invalid_dimension_signal_n": invalid_dimensions,
                  "duplicate_associations_collapsed": len(eligible) - len(assignments),
                  "source_unit_warning": "run_id identifies the cumulative snapshot, not a filter on source run_id"},
        "evidence_facts": evidence_facts, "signal_facts": signal_facts, "assignment_facts": assignment_facts,
    }


def _cell(value: Any) -> str:
    return "" if value is None else str(value)


def _csv(rows: List[Dict[str, Any]], fields: Tuple[str, ...]) -> str:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


def render_publication_tables(model: Dict[str, Any]) -> str:
    """Render visible values from the same rows exported to CSV/JSON/SQLite."""
    text = ('<section id="publication-tables-v1"><h2>Observational unit reconciliation and sector × QMBD</h2>'
            '<p>Counts describe retained screening evidence. A source may contribute to several cells. '
            'Unique-source totals are recomputed, not summed across overlapping groups. '
            'Percentages use association counts. Missing values and unavailable results are not zero. '
            'Small-cell warning: fewer than 5 associations; descriptive threshold, not a significance test. '
            'missing_n counts signal rows lacking dimensions, not missing distinct associations. '
            'The snapshot includes source history; its run ID is not a source-run filter.</p>')
    for label, key, fields in (("Unit reconciliation", "unit_reconciliation", UNIT_COLUMNS),
                               ("Sector × QMBD", "sector_qmbd", CELL_COLUMNS)):
        text += '<h3>' + label + '</h3><table data-publication-table="' + key + '"><thead><tr>'
        text += ''.join('<th>' + f + '</th>' for f in fields) + '</tr></thead><tbody>'
        for row in model[key]:
            text += '<tr>' + ''.join('<td>' + html.escape(_cell(row[f])) + '</td>' for f in fields) + '</tr>'
        text += '</tbody></table>'
    return text + '</section>'


def publication_artifacts(model: Dict[str, Any]) -> Dict[str, bytes]:
    """Pure, deterministic projections; never modify retained input artifacts."""
    return {
        "publication_tables.json": _json(model).encode(),
        "publication_data_audit.json": _json(model["audit"]).encode(),
        "unit_reconciliation.csv": _csv(model["unit_reconciliation"], UNIT_COLUMNS).encode(),
        "sector_qmbd_publication.csv": _csv(model["sector_qmbd"], CELL_COLUMNS).encode(),
        "publication_metric_contract.csv": _csv(model["metric_contract"], METRIC_COLUMNS).encode(),
        "publication_tables.html": ("<!doctype html><html lang=\"en\"><meta charset=\"utf-8\">"
                                    "<title>Publication tables</title><body>" + render_publication_tables(model)
                                    + "</body></html>\n").encode(),
    }


def write_publication_tables(model: Dict[str, Any], output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    for name, data in publication_artifacts(model).items():
        (output / name).write_bytes(data)


def add_publication_sqlite(conn: sqlite3.Connection, model: Dict[str, Any]) -> None:
    """Add versioned typed tables alongside untouched legacy TEXT projections."""
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript('''
CREATE TABLE analysis_metadata_v1 (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE analysis_evidence_v1 (evidence_id TEXT NOT NULL PRIMARY KEY,
 year INTEGER CHECK(year IS NULL OR typeof(year)='integer'),
 year_status TEXT NOT NULL CHECK(year_status IN ('valid','missing','invalid')));
CREATE TABLE analysis_signals_v1 (signal_id TEXT NOT NULL, fragment_id TEXT NOT NULL,
 evidence_id TEXT NOT NULL REFERENCES analysis_evidence_v1(evidence_id),
 sector TEXT NOT NULL, axis_group TEXT NOT NULL CHECK(axis_group IN ('MARINE','MARITIME','OCEANIC','HYDRONIZATION')),
 confidence_score REAL CHECK(confidence_score IS NULL OR
 (typeof(confidence_score)='real' AND confidence_score BETWEEN 0 AND 1)),
 confidence_status TEXT NOT NULL CHECK(confidence_status IN ('valid','missing','invalid')),
 PRIMARY KEY(signal_id, fragment_id));
CREATE TABLE analysis_assignments_v1 (
 evidence_id TEXT NOT NULL REFERENCES analysis_evidence_v1(evidence_id),
 sector TEXT NOT NULL, axis_group TEXT NOT NULL CHECK(axis_group IN ('MARINE','MARITIME','OCEANIC','HYDRONIZATION')),
 PRIMARY KEY(evidence_id, sector, axis_group));
''')
    meta = {k: model[k] for k in ("schema_version", "run_id", "source_schema_version", "scope", "protocol_sha256")}
    meta.update({"sources_sha256": _json(model["sources_sha256"]), "audit": _json(model["audit"])})
    conn.executemany("INSERT INTO analysis_metadata_v1 VALUES (?,?)", sorted(meta.items()))
    for table, key in (("evidence", "evidence_facts"), ("signals", "signal_facts"), ("assignments", "assignment_facts")):
        for row in model[key]:
            conn.execute(f"INSERT INTO analysis_{table}_v1 VALUES ({','.join('?' for _ in row)})", tuple(row.values()))
    int_fields = {"value", "n", "missing_n", "assignment_count", "unique_evidence_n", "row_denominator",
                  "column_denominator", "grand_denominator", "excluded_signal_n"}
    for key, fields in (("unit_reconciliation", UNIT_COLUMNS),
                        ("sector_qmbd", CELL_COLUMNS), ("metric_contract", METRIC_COLUMNS)):
        declarations = ','.join(f'"{f}" ' + ("INTEGER" if f in int_fields else "REAL" if f.endswith("_pct") else "TEXT")
                                for f in fields)
        primary = "sector,axis_group" if key == "sector_qmbd" else "metric_id"
        conn.execute(f'CREATE TABLE analysis_{key}_v1 ({declarations}, PRIMARY KEY({primary}))')
        conn.executemany(f'INSERT INTO analysis_{key}_v1 VALUES ({",".join("?" for _ in fields)})',
                         [tuple(row[f] for f in fields) for row in model[key]])
    if conn.execute("PRAGMA foreign_key_check").fetchall():
        raise ValueError("Publication SQLite foreign-key violation")


def validate_publication_outputs(model: Dict[str, Any], output: Path,
                                 conn: Optional[sqlite3.Connection] = None) -> None:
    """Reject stale or divergent projections, including visible HTML values."""
    for name, expected in publication_artifacts(model).items():
        if not (output / name).is_file() or (output / name).read_bytes() != expected:
            raise ValueError("publication_projection_mismatch:" + name)
    report = output / "morskamary_statistical_report.html"
    if report.is_file() and render_publication_tables(model) not in report.read_text(encoding="utf-8"):
        raise ValueError("publication_projection_mismatch:main_html")
    if conn is not None:
        validate_publication_sqlite(model, conn)


def validate_publication_sqlite(model: Dict[str, Any], conn: sqlite3.Connection) -> None:
    """Check facts, metadata and summaries in the actual SQLite projection."""
    reference = sqlite3.connect(":memory:")
    try:
        add_publication_sqlite(reference, model)
        for table in ("metadata", "evidence", "signals", "assignments"):
            query = f"SELECT * FROM analysis_{table}_v1"
            if sorted(conn.execute(query).fetchall(), key=str) != sorted(reference.execute(query).fetchall(), key=str):
                raise ValueError("publication_projection_mismatch:sqlite:" + table)
        if conn.execute("PRAGMA foreign_key_check").fetchall():
            raise ValueError("publication_projection_mismatch:sqlite:foreign_keys")
    finally:
        reference.close()
    for key, fields in (("unit_reconciliation", UNIT_COLUMNS),
                        ("sector_qmbd", CELL_COLUMNS), ("metric_contract", METRIC_COLUMNS)):
        actual = conn.execute(f'SELECT {",".join(fields)} FROM analysis_{key}_v1').fetchall()
        expected_rows = [tuple(row[f] for f in fields) for row in model[key]]
        if sorted(actual, key=str) != sorted(expected_rows, key=str):
            raise ValueError("publication_projection_mismatch:sqlite:" + key)
