"""MOR-21 negative controls for grain, missingness, joins and projections."""
import csv
import json
import sqlite3
from pathlib import Path

import pytest

from src.scientific_sources.publication_tables import (
    add_publication_sqlite, build_publication_tables, publication_artifacts,
    render_publication_tables, validate_publication_outputs, write_publication_tables,
)


def write_csv(path: Path, rows: list[dict], headers: list[str] | None = None) -> None:
    with path.open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=headers or list(rows[0]), lineterminator='\n')
        w.writeheader()
        w.writerows(rows)


def bundle(path: Path) -> Path:
    path.mkdir(exist_ok=True)
    (path / 'run_novelty_metrics.json').write_text(json.dumps({'current_run_id': 'snapshot-1'}))
    (path / 'cumulative_database_manifest.json').write_text(json.dumps({'schema_version': '1.0.0'}))
    write_csv(path / 'evidence_records.csv', [
        {'evidence_id': 'e1', 'year': '2020'}, {'evidence_id': 'e2', 'year': ''},
        {'evidence_id': 'e3', 'year': 'not_computable'},
    ])
    write_csv(path / 'competence_demand_signals.csv', [
        {'signal_id': 's1', 'evidence_id': 'e1', 'sector': 'blue_biotech', 'axis_group': 'MARINE',
         'signal_type': 'skill', 'confidence_score': '0.45', 'manual_review_status': 'review_required'},
        {'signal_id': 's2', 'evidence_id': 'e1', 'sector': 'blue_biotech', 'axis_group': 'MARINE',
         'signal_type': 'education', 'confidence_score': '', 'manual_review_status': 'review_required'},
        {'signal_id': 's3', 'evidence_id': 'e1', 'sector': 'desalination', 'axis_group': 'HYDRONIZATION',
         'signal_type': 'skill', 'confidence_score': 'broken', 'manual_review_status': 'review_required'},
        {'signal_id': 's4', 'evidence_id': 'e2', 'sector': 'blue_biotech', 'axis_group': 'MARINE',
         'signal_type': 'skill', 'confidence_score': '0.75', 'manual_review_status': 'review_required'},
    ])
    return path


def metric(model, name):
    return next(r for r in model['unit_reconciliation'] if r['metric_id'] == name)


def cell(model, sector, axis):
    return next(r for r in model['sector_qmbd'] if (r['sector'], r['axis_group']) == (sector, axis))


def test_multiple_signals_do_not_inflate_evidence_associations(tmp_path):
    model = build_publication_tables(bundle(tmp_path))
    total = cell(model, 'ALL', 'ALL')
    assert total['assignment_count'] == 3
    assert total['unique_evidence_n'] == 2
    assert cell(model, 'blue_biotech', 'MARINE')['row_pct'] == 100
    assert cell(model, 'blue_biotech', 'MARINE')['total_pct'] == 66.666667
    assert sum(r['unique_evidence_n'] for r in model['sector_qmbd'] if r['row_kind'] == 'cell') == 3
    assert model['audit']['duplicate_associations_collapsed'] == 1
    assert metric(model, 'competence_candidates')['value'] is None
    assert metric(model, 'provider_query_occurrences')['missing_n'] is None


def test_zero_denominator_and_empty_retained_table_differ_from_absent(tmp_path):
    p = bundle(tmp_path)
    rows = list(csv.DictReader((p / 'competence_demand_signals.csv').open()))
    write_csv(p / 'competence_demand_signals.csv', [], list(rows[0]))
    m = build_publication_tables(p)
    assert metric(m, 'semantic_signals')['value'] == 0
    assert cell(m, 'ALL', 'ALL')['row_pct'] is None
    assert cell(m, 'ALL', 'ALL')['reason'] == 'zero_denominator'
    (p / 'competence_demand_signals.csv').unlink()
    assert metric(build_publication_tables(p), 'semantic_signals')['value'] is None


@pytest.mark.parametrize('bad', ['oops', 'NaN', 'Infinity', '-1', '1.5', 'not_computable', ''])
def test_invalid_or_missing_year_never_coerced_to_zero(tmp_path, bad):
    p = bundle(tmp_path)
    write_csv(p / 'evidence_records.csv', [{'evidence_id': 'e1', 'year': bad}])
    m = build_publication_tables(p)
    assert m['evidence_facts'][0]['year'] is None
    assert m['evidence_facts'][0]['year_status'] in ('missing', 'invalid')


def test_duplicate_parent_exposes_join_expansion_and_suppresses_table(tmp_path):
    p = bundle(tmp_path)
    write_csv(p / 'evidence_records.csv', [{'evidence_id': 'e1'}, {'evidence_id': 'e1'}, {'evidence_id': 'e2'}])
    m = build_publication_tables(p)
    relation = next(r for r in m['audit']['relations'] if r['child'] == 'competence_demand_signals')
    assert relation['before_n'] == 4
    assert relation['inner_join_n'] == 7
    assert relation['excess_join_rows'] == 3
    assert cell(m, 'ALL', 'ALL')['assignment_count'] is None
    assert metric(m, 'unique_evidence')['value'] is None


def test_orphan_signal_suppresses_table_instead_of_publishing_incomplete_count(tmp_path):
    p = bundle(tmp_path)
    write_csv(p / 'evidence_records.csv', [{'evidence_id': 'unrelated'}])
    m = build_publication_tables(p)
    assert cell(m, 'ALL', 'ALL')['status'] == 'not_computable'
    assert 'invalid_relation:evidence_id' in m['audit']['table_blockers']


def test_missing_dimensions_have_explicit_exclusion_and_missing_grain(tmp_path):
    p = bundle(tmp_path)
    rows = list(csv.DictReader((p / 'competence_demand_signals.csv').open()))
    rows[0]['axis_group'] = ''
    rows[1]['manual_review_status'] = 'rejected'
    write_csv(p / 'competence_demand_signals.csv', rows)
    m = build_publication_tables(p)
    total = cell(m, 'ALL', 'ALL')
    assert total['assignment_count'] == 2
    assert total['missing_n'] == 1
    assert total['excluded_signal_n'] == 2


def test_unknown_axis_does_not_become_observed_zero(tmp_path):
    p = bundle(tmp_path)
    rows = list(csv.DictReader((p / 'competence_demand_signals.csv').open()))
    rows[0]['axis_group'] = 'TYPO'
    write_csv(p / 'competence_demand_signals.csv', rows)
    m = build_publication_tables(p)
    assert cell(m, 'ALL', 'ALL')['assignment_count'] is None


def test_modern_missing_signals_cannot_fall_back_to_legacy(tmp_path):
    p = bundle(tmp_path)
    (p / 'cumulative_database_manifest.json').write_text(json.dumps({'schema_version': '2.0.0'}))
    m = build_publication_tables(p)
    assert metric(m, 'semantic_signals')['value'] is None
    assert cell(m, 'ALL', 'ALL')['status'] == 'not_computable'


def test_typed_sqlite_preserves_nulls_and_explicit_relationships(tmp_path):
    m = build_publication_tables(bundle(tmp_path))
    with sqlite3.connect(':memory:') as c:
        add_publication_sqlite(c, m)
        assert c.execute(
            "SELECT typeof(year),year FROM analysis_evidence_v1 WHERE evidence_id='e1'").fetchone() == ('integer', 2020)
        assert c.execute(
            "SELECT confidence_score,confidence_status FROM analysis_signals_v1 "
            "WHERE signal_id='s3'").fetchone() == (None, 'invalid')
        assert c.execute('PRAGMA foreign_key_check').fetchall() == []
        with pytest.raises(sqlite3.IntegrityError):
            c.execute("INSERT INTO analysis_assignments_v1 VALUES ('absent', 'blue_biotech','MARINE')")
        assert c.execute("SELECT assignment_count,unique_evidence_n FROM analysis_sector_qmbd_v1 "
                         "WHERE sector='ALL' AND axis_group='ALL'").fetchone() == (3, 2)


@pytest.mark.parametrize('name', ['publication_tables.json', 'publication_data_audit.json',
                                  'unit_reconciliation.csv', 'sector_qmbd_publication.csv',
                                  'publication_metric_contract.csv', 'publication_tables.html'])
def test_cross_format_drift_rejected(tmp_path, name):
    p = bundle(tmp_path / 'input')
    out = tmp_path / 'report'
    m = build_publication_tables(p)
    write_publication_tables(m, out)
    validate_publication_outputs(m, out)
    (out / name).write_bytes((out / name).read_bytes() + b'tamper')
    with pytest.raises(ValueError, match='publication_projection_mismatch'):
        validate_publication_outputs(m, out)


def test_visible_html_and_sqlite_tampering_rejected(tmp_path):
    p = bundle(tmp_path / 'input')
    out = tmp_path / 'report'
    m = build_publication_tables(p)
    write_publication_tables(m, out)
    html_path = out / 'morskamary_statistical_report.html'
    html_path.write_text(render_publication_tables(m).replace('<td>66.666667</td>', '<td>99</td>'))
    with pytest.raises(ValueError, match='main_html'):
        validate_publication_outputs(m, out)
    html_path.unlink()
    with sqlite3.connect(':memory:') as conn:
        add_publication_sqlite(conn, m)
        validate_publication_outputs(m, out, conn)
        conn.execute("UPDATE analysis_sector_qmbd_v1 SET assignment_count=999 WHERE sector='ALL'")
        with pytest.raises(ValueError, match='sqlite'):
            validate_publication_outputs(m, out, conn)


def test_repeated_build_is_byte_identical_and_source_changes_detected(tmp_path):
    p = bundle(tmp_path / 'input')
    out = tmp_path / 'output'
    first = build_publication_tables(p)
    second = build_publication_tables(p)
    assert publication_artifacts(first) == publication_artifacts(second)
    write_publication_tables(first, out)
    with (p / 'evidence_records.csv').open('a') as f:
        f.write('e4,2026\n')
    with pytest.raises(ValueError, match='publication_projection_mismatch'):
        validate_publication_outputs(build_publication_tables(p), out)


def test_composite_signal_key_preserves_two_fragments(tmp_path):
    p = bundle(tmp_path)
    write_csv(p / 'evidence_fragments.csv', [
        {'fragment_id': 'f1', 'evidence_id': 'e1'}, {'fragment_id': 'f2', 'evidence_id': 'e1'}])
    write_csv(p / 'semantic_signals.csv', [
        {'signal_id': 'same', 'fragment_id': f, 'evidence_id': 'e1', 'sector': 'blue_biotech',
         'axis_group': 'MARINE', 'axis_code': 'M'} for f in ('f1', 'f2')])
    m = build_publication_tables(p)
    assert metric(m, 'semantic_signals')['value'] == 2
    assert cell(m, 'ALL', 'ALL')['assignment_count'] == 1
    with sqlite3.connect(':memory:') as c:
        add_publication_sqlite(c, m)
        assert c.execute('SELECT count(*) FROM analysis_signals_v1').fetchone() == (2,)


def test_claimed_validation_without_backing_decision_is_unavailable(tmp_path):
    p = bundle(tmp_path)
    write_csv(p / 'canonical_competences.csv', [
        {'canonical_competence_id': 'c1', 'source_candidate_id': 'absent', 'validation_decision_id': 'd1',
         'validation_status': 'accepted', 'provenance_guard_status': 'passed'}])
    m = build_publication_tables(p)
    assert metric(m, 'validated_canonical_competences')['value'] is None
    assert 'unverified_canonical_validation' in metric(m, 'validated_canonical_competences')['reason']


def test_sqlite_rejects_wrong_type_and_parity_covers_facts(tmp_path):
    m = build_publication_tables(bundle(tmp_path / 'input'))
    out = tmp_path / 'output'
    write_publication_tables(m, out)
    with sqlite3.connect(':memory:') as c:
        add_publication_sqlite(c, m)
        with pytest.raises(sqlite3.IntegrityError):
            c.execute("UPDATE analysis_evidence_v1 SET year='invalid'")
        c.execute("UPDATE analysis_evidence_v1 SET year=2019 WHERE evidence_id='e1'")
        with pytest.raises(ValueError, match='sqlite:evidence'):
            validate_publication_outputs(m, out, c)


def test_missing_parent_table_blocks_modern_signal_count(tmp_path):
    p = bundle(tmp_path)
    write_csv(p / 'semantic_signals.csv', [
        {'signal_id': 's', 'fragment_id': 'f', 'evidence_id': 'e1', 'sector': 'blue_biotech', 'axis_group': 'MARINE'}])
    m = build_publication_tables(p)
    assert metric(m, 'semantic_signals')['value'] is None
    assert cell(m, 'ALL', 'ALL')['assignment_count'] is None


def test_retained_protocol_binding_mismatch_is_rejected(tmp_path):
    p = bundle(tmp_path)
    (p / 'cumulative_database_manifest.json').write_text(json.dumps({
        'schema_version': '1.0.0', 'protocol_binding': {'protocol_sha256': 'wrong'}}))
    with pytest.raises(ValueError, match='protocol_binding_mismatch'):
        build_publication_tables(p)
