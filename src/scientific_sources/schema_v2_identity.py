"""Schema-v2 deterministic identity contract — shared hash builders.

All stable SHA-256-based identifiers for the schema-v2 scientific-lineage
chain are defined here and nowhere else.  Every consumer that needs to
recompute or verify a stored identifier MUST import from this module instead
of inlining its own formula.  Drift between producers, preflights, and
validation layers is therefore structurally impossible.

Identity contract
-----------------
* Algorithm : SHA-256 (hexdigest, 64 lowercase hex characters)
* Delimiter : ASCII Unit Separator ``\\x1f`` (U+001F) between payload fields
* Prefix    : lower-case alphabetic slug followed by ``:`` (e.g. ``prov:``)
* Encoding  : UTF-8 for all payload strings before hashing

Security boundary
-----------------
These identifiers are *deterministically reconstructable* and
*tamper-evident under the trusted validation boundary*.  They are NOT
cryptographic proof of external authenticity: a reviewer who controls the
full ledger (decisions + signals + fragments) can produce a self-consistent
forged chain.  The validation layer detects divergence *within* the
chain — a promoter cannot silently inject a fragment the reviewer never
examined.  External cryptographic signing of the ledger is out of scope for
this module.

``validation_decision_id`` contract
------------------------------------
Decision identifiers are externally supplied by the human reviewer (e.g.
``decision:v1``, ``decision:2024-01-15``).  They are an intentional public
contract and are NOT replaced by this module.  Callers that need integrity
assurance over the decision *content* should compute a
``decision_content_hash`` via :func:`make_decision_content_hash` and store it
alongside ``validation_decision_id``.

Preimage delimiter guard
------------------------
All payload-builder helpers call :func:`check_no_unit_sep` for every scalar
field value before joining.  A ``ValueError`` is raised if any field contains
the ASCII Unit Separator (``\\x1f``) so that injection via field-value
manipulation is detected at construction time.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Mapping

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

#: ASCII Unit Separator used as the preimage field delimiter.
UNIT_SEP: str = "\x1f"

#: Compiled pattern for a well-formed schema-v2 identifier:
#: ``<prefix>:<64-lowercase-hex-chars>``.
LINEAGE_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*:[0-9a-f]{64}$")


# ---------------------------------------------------------------------------
# Guard helpers
# ---------------------------------------------------------------------------

def check_no_unit_sep(field_name: str, value: str) -> None:
    """Raise ``ValueError`` if *value* contains the ASCII Unit Separator.

    Call this on every scalar field before constructing the ``\\x1f``-joined
    preimage.  A field value that itself contains ``\\x1f`` would corrupt the
    payload hash and is treated as a construction error.

    Args:
        field_name: Human-readable name used in the error message.
        value: The string value to check.

    Raises:
        ValueError: If *value* contains ``\\x1f``.
    """
    if UNIT_SEP in value:
        raise ValueError(
            f"preimage field '{field_name}' contains the ASCII Unit Separator "
            "(U+001F); this would corrupt the hash payload"
        )


# ---------------------------------------------------------------------------
# Normalisation helpers (must match cumulative_scientific_database.py exactly)
# ---------------------------------------------------------------------------

def normalize_source_id(source_id: Any) -> str:
    """Return the lowercased, stripped source identifier, or ``''`` if empty."""
    if not isinstance(source_id, str):
        return ""
    return source_id.strip().lower()


def normalize_canonical_label(value: Any) -> str:
    """Whitespace-collapse and strip a canonical competence label.

    This is the *exact* normalisation applied by the cumulative database
    producer before hashing the canonical competence identity::

        canonical_id = "canonical:" + sha256(normalize_canonical_label(label).lower())
    """
    return re.sub(r"\s+", " ", str(value or "")).strip()


def normalize_query_text(value: Any) -> str:
    """Whitespace-collapse, strip, and lowercase a source query text field."""
    return re.sub(r"\s+", " ", str(value or "")).strip().lower()


def normalize_matched_phrase(value: Any) -> str:
    """Whitespace-collapse, strip, and lowercase a matched phrase field."""
    return re.sub(r"\s+", " ", str(value or "")).strip().lower()


# ---------------------------------------------------------------------------
# Identity builders
# ---------------------------------------------------------------------------

def make_provenance_id(
    *,
    run_id: str,
    evidence_id: str,
    source_retrieved_at_utc: str,
    source_provider: str,
    source_provider_id: str,
    source_query_id: str,
    source_query_text: str,
) -> str:
    """Return the stable source-occurrence identifier ``prov:<sha256>``.

    Mirrors ``_make_provenance_id_from_fields`` in
    ``cumulative_scientific_database``.  ``source_provider_id`` is normalised
    with :func:`normalize_source_id`.  ``source_query_text`` is normalised
    with :func:`normalize_query_text`.

    Raises:
        ValueError: If any field value contains ``\\x1f``.
    """
    norm_provider_id = normalize_source_id(source_provider_id)
    norm_query_text = normalize_query_text(source_query_text)
    fields = {
        "run_id": run_id,
        "evidence_id": evidence_id,
        "source_retrieved_at_utc": source_retrieved_at_utc,
        "source_provider": source_provider,
        "source_provider_id": norm_provider_id,
        "source_query_id": source_query_id,
        "source_query_text": norm_query_text,
    }
    for name, val in fields.items():
        check_no_unit_sep(name, val)
    payload = UNIT_SEP.join([
        run_id,
        evidence_id,
        source_retrieved_at_utc,
        source_provider,
        norm_provider_id,
        source_query_id,
        norm_query_text,
    ])
    return "prov:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def make_signal_id(
    *,
    evidence_id: str,
    signal_type: str,
    matched_phrase: str,
    evidence_text_hash: str,
    classifier_version: str,
) -> str:
    """Return the stable semantic-signal identifier ``signal:<sha256>``.

    Mirrors ``_make_signal_id`` in ``cumulative_scientific_database``.
    ``matched_phrase`` is normalised with :func:`normalize_matched_phrase`.

    Raises:
        ValueError: If any field value contains ``\\x1f``.
    """
    norm_phrase = normalize_matched_phrase(matched_phrase)
    fields = {
        "evidence_id": evidence_id,
        "signal_type": signal_type,
        "matched_phrase": norm_phrase,
        "evidence_text_hash": evidence_text_hash,
        "classifier_version": classifier_version,
    }
    for name, val in fields.items():
        check_no_unit_sep(name, val)
    payload = UNIT_SEP.join([
        evidence_id, signal_type, norm_phrase, evidence_text_hash, classifier_version,
    ])
    return "signal:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def make_fragment_id(
    *,
    evidence_id: str,
    signal_id: str,
    provenance_id: str,
    source_field: str,
    span_start: int,
    span_end: int,
) -> str:
    """Return the stable evidence-fragment identifier ``fragment:<sha256>``.

    Mirrors ``_make_fragment_id`` in ``cumulative_scientific_database``.

    Raises:
        ValueError: If any string field value contains ``\\x1f``.
    """
    fields = {
        "evidence_id": evidence_id,
        "signal_id": signal_id,
        "provenance_id": provenance_id,
        "source_field": source_field,
    }
    for name, val in fields.items():
        check_no_unit_sep(name, val)
    payload = UNIT_SEP.join([
        evidence_id, signal_id, provenance_id, source_field,
        str(span_start), str(span_end),
    ])
    return "fragment:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def make_candidate_id(*, signal_id: str, evidence_id: str) -> str:
    """Return the stable competence-candidate identifier ``candidate:<sha256>``.

    Mirrors ``_make_candidate_id`` in ``cumulative_scientific_database``.

    Raises:
        ValueError: If any field value contains ``\\x1f``.
    """
    for name, val in [("signal_id", signal_id), ("evidence_id", evidence_id)]:
        check_no_unit_sep(name, val)
    payload = UNIT_SEP.join([signal_id, evidence_id, "candidate"])
    return "candidate:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def make_canonical_competence_id(preferred_label: Any) -> str:
    """Return the stable canonical-competence identifier ``canonical:<sha256>``.

    The preimage is the whitespace-normalised, lowercased preferred label.
    This matches the formula in ``cumulative_scientific_database`` line 3048/3063
    and all preflight validators.

    Raises:
        ValueError: If the normalised label contains ``\\x1f``.
    """
    label = normalize_canonical_label(preferred_label).lower()
    check_no_unit_sep("preferred_label", label)
    return "canonical:" + hashlib.sha256(label.encode("utf-8")).hexdigest()


def make_assignment_id(
    *,
    canonical_competence_id: str,
    validation_decision_id: str,
    sector: str,
    axis_group: str,
    axis_code: str,
) -> str:
    """Return the stable sector-assignment identifier ``assignment:<sha256>``.

    Mirrors the inline formula in ``cumulative_scientific_database``
    ``_build_sector_competence_assignments`` and the preflight recomputation
    in ``build_live_cumulative_release_package``.

    Raises:
        ValueError: If any field value contains ``\\x1f``.
    """
    fields = {
        "canonical_competence_id": canonical_competence_id,
        "validation_decision_id": validation_decision_id,
        "sector": sector,
        "axis_group": axis_group,
        "axis_code": axis_code,
    }
    for name, val in fields.items():
        check_no_unit_sep(name, val)
    payload = UNIT_SEP.join([
        canonical_competence_id,
        validation_decision_id,
        sector,
        axis_group,
        axis_code,
    ])
    return "assignment:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def make_decision_content_hash(
    *,
    validation_decision_id: str,
    decision_status: str,
    target_candidate_id: str,
    canonical_label: str,
    reviewer_identifier: str,
    decision_rationale: str,
    decision_at_utc: str,
    superseded_validation_decision_id: str,
) -> str:
    """Return a content-integrity hash over a canonicalised decision snapshot.

    This is NOT a replacement for the externally supplied
    ``validation_decision_id`` — that remains an opaque reviewer-controlled
    identifier.  This hash provides a tamper-evident digest of the decision
    *content*, enabling downstream consumers to detect silent mutations.

    The preimage is the ``\\x1f``-joined concatenation of all significant
    decision fields after whitespace normalisation and lowercasing of
    ``canonical_label``.  The result is stored as a plain hex string (no
    prefix) so it is unambiguous that it is a content digest, not a
    row identity.

    Raises:
        ValueError: If any field value contains ``\\x1f``.
    """
    norm_label = normalize_canonical_label(canonical_label).lower()
    fields_map = {
        "validation_decision_id": validation_decision_id,
        "decision_status": decision_status,
        "target_candidate_id": target_candidate_id,
        "canonical_label": norm_label,
        "reviewer_identifier": reviewer_identifier,
        "decision_rationale": decision_rationale,
        "decision_at_utc": decision_at_utc,
        "superseded_validation_decision_id": superseded_validation_decision_id,
    }
    for name, val in fields_map.items():
        check_no_unit_sep(name, val)
    payload = UNIT_SEP.join([
        validation_decision_id,
        decision_status,
        target_candidate_id,
        norm_label,
        reviewer_identifier,
        decision_rationale,
        decision_at_utc,
        superseded_validation_decision_id,
    ])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Row-level recomputation helpers (for validation consumers)
# ---------------------------------------------------------------------------

def recompute_provenance_id_from_row(row: Mapping[str, Any]) -> str:
    """Recompute ``prov:<sha256>`` from a provenance-row mapping.

    Returns ``""`` when any required field is absent, so callers can skip
    rows that pre-date the schema-v2 preimage contract.
    """
    run_id = str(row.get("run_id") or "").strip()
    evidence_id = str(row.get("evidence_id") or "").strip()
    source_retrieved_at_utc = str(row.get("source_retrieved_at_utc") or "").strip()
    source_provider = str(row.get("source_provider") or "").strip()
    source_provider_id = str(row.get("source_provider_id") or "").strip()
    source_query_id = str(row.get("source_query_id") or "").strip()
    source_query_text = str(row.get("source_query_text") or "")
    if not all([run_id, evidence_id, source_retrieved_at_utc,
                source_provider, source_query_id]):
        return ""
    return make_provenance_id(
        run_id=run_id,
        evidence_id=evidence_id,
        source_retrieved_at_utc=source_retrieved_at_utc,
        source_provider=source_provider,
        source_provider_id=source_provider_id,
        source_query_id=source_query_id,
        source_query_text=source_query_text,
    )


def recompute_signal_id_from_row(row: Mapping[str, Any]) -> str:
    """Recompute ``signal:<sha256>`` from a semantic-signal row mapping.

    Returns ``""`` when any required field is absent.
    """
    evidence_id = str(row.get("evidence_id") or "").strip()
    signal_type = str(row.get("signal_type") or "").strip()
    matched_phrase = str(row.get("matched_phrase") or "")
    evidence_text_hash = str(row.get("evidence_text_hash") or "").strip()
    classifier_version = str(row.get("classifier_version") or "").strip()
    if not all([evidence_id, signal_type, matched_phrase,
                evidence_text_hash, classifier_version]):
        return ""
    return make_signal_id(
        evidence_id=evidence_id,
        signal_type=signal_type,
        matched_phrase=matched_phrase,
        evidence_text_hash=evidence_text_hash,
        classifier_version=classifier_version,
    )


def recompute_fragment_id_from_row(
    row: Mapping[str, Any],
    *,
    signal_id: str,
    provenance_id: str,
) -> str:
    """Recompute ``fragment:<sha256>`` from a fragment row mapping.

    Returns ``""`` when any required field is absent or offsets are
    non-numeric.
    """
    evidence_id = str(row.get("evidence_id") or "").strip()
    source_field = str(row.get("source_field") or "").strip()
    try:
        span_start = int(row.get("span_start_offset", ""))
        span_end = int(row.get("span_end_offset", ""))
    except (ValueError, TypeError):
        return ""
    if not all([evidence_id, signal_id, provenance_id, source_field]):
        return ""
    return make_fragment_id(
        evidence_id=evidence_id,
        signal_id=signal_id,
        provenance_id=provenance_id,
        source_field=source_field,
        span_start=span_start,
        span_end=span_end,
    )


def recompute_candidate_id_from_row(row: Mapping[str, Any]) -> str:
    """Recompute ``candidate:<sha256>`` from a candidate row mapping.

    Returns ``""`` when any required field is absent.
    """
    signal_id = str(row.get("signal_id") or "").strip()
    evidence_id = str(row.get("evidence_id") or "").strip()
    if not signal_id or not evidence_id:
        return ""
    return make_candidate_id(signal_id=signal_id, evidence_id=evidence_id)


def recompute_assignment_id_from_row(row: Mapping[str, Any]) -> str:
    """Recompute ``assignment:<sha256>`` from an assignment row mapping.

    Returns ``""`` when any required field is absent.
    """
    canonical_competence_id = str(row.get("canonical_competence_id") or "").strip()
    validation_decision_id = str(row.get("validation_decision_id") or "").strip()
    sector = str(row.get("sector") or "").strip()
    axis_group = str(row.get("axis_group") or "").strip()
    axis_code = str(row.get("axis_code") or "").strip()
    if not all([canonical_competence_id, validation_decision_id,
                sector, axis_group, axis_code]):
        return ""
    return make_assignment_id(
        canonical_competence_id=canonical_competence_id,
        validation_decision_id=validation_decision_id,
        sector=sector,
        axis_group=axis_group,
        axis_code=axis_code,
    )
