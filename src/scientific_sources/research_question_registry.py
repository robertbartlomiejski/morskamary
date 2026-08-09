"""Typed, fail-closed research-question and accountability-ledger validation."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence, Tuple, cast

import yaml  # type: ignore[import-untyped]
from jsonschema import Draft202012Validator, FormatChecker


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REGISTRY_PATH = REPO_ROOT / "config" / "research_question_registry.yml"
DEFAULT_PROTOCOL_PATH = REPO_ROOT / "config" / "live_query_protocol.yml"
DEFAULT_REGISTRY_SCHEMA_PATH = (
    REPO_ROOT / "schemas" / "research_question_registry.schema.json"
)
DEFAULT_ACCOUNTABILITY_SCHEMA_PATH = (
    REPO_ROOT / "schemas" / "research_question_accountability.schema.json"
)

CANONICAL_AXES: Tuple[Tuple[str, str], ...] = (
    ("MARINE", "M"),
    ("MARITIME", "T"),
    ("OCEANIC", "O"),
    ("HYDRONIZATION", "H"),
)
REQUIRED_QUESTION_IDS: Tuple[str, ...] = (
    "RQ1",
    "RQ2",
    "RQ3",
    "RQ4",
    "RQ4.1",
    "RQ4.2",
    "RQ4.3",
    "RQ4.4",
    "RQ5",
    "RQ6",
    "RQ7",
    "RQ8",
)
REQUIRED_EXTENDED_QUESTION_IDS: Tuple[str, ...] = (
    "ETQ1",
    "ETQ2",
    "ETQ3",
    "ETQ4",
    "ETQ5",
    "ETQ6",
    "ETQ7",
)
RQ4_AXIS_CONTRACT: Mapping[str, Tuple[str, str]] = {
    "RQ4.1": ("MARINE", "M"),
    "RQ4.2": ("MARITIME", "T"),
    "RQ4.3": ("OCEANIC", "O"),
    "RQ4.4": ("HYDRONIZATION", "H"),
}
ALLOWED_RESULT_STATUSES: Tuple[str, ...] = (
    "answered",
    "partially_answered",
    "not_computable",
    "not_operationalised",
    "not_collected",
    "review_required",
)
BASELINE_ACCOUNTABILITY_FIELDS = frozenset(
    {
        "question_id",
        "result_status",
        "view_kind",
        "scientific_status",
        "observational_unit",
        "n",
        "missing_n",
        "denominator",
        "method",
        "evidence_references",
        "validity_threats",
        "permitted_interpretation",
        "prohibited_interpretation",
    }
)
ETQ_STATUS_BY_ID: Mapping[str, str] = {
    "ETQ1": "not_operationalised",
    "ETQ2": "not_operationalised",
    "ETQ3": "not_operationalised",
    "ETQ4": "not_operationalised",
    "ETQ5": "not_operationalised",
    "ETQ6": "not_operationalised",
    "ETQ7": "not_collected",
}
SCIENTIFIC_STATUS_BY_RESULT: Mapping[str, str] = {
    "answered": "answer_established",
    "partially_answered": "answer_not_established",
    "not_computable": "computation_blocked",
    "not_operationalised": "operationalisation_required",
    "not_collected": "collection_not_started",
    "review_required": "review_required",
}


class ResearchQuestionRegistryError(ValueError):
    """Raised when a registry or accountability ledger violates its contract."""


@dataclass(frozen=True)
class AxisIdentity:
    """Canonical axis name/code pair."""

    canonical_name: str
    display_code: str
    meaning: str


@dataclass(frozen=True)
class MethodSpecification:
    """A declared analytical method and its readiness boundary."""

    name: str
    readiness: str
    approval_status: str
    prerequisite: str
    implementation_reference: str = ""


@dataclass(frozen=True)
class ResearchQuestion:
    """A typed operational research-question declaration."""

    question_id: str
    parent_id: str
    text: str
    status: str
    axis_name: str
    axis_code: str
    construct: str
    population_definition: str
    target_view: str
    view_kind: str
    observational_unit: str
    variables: Tuple[str, ...]
    indicators: Tuple[str, ...]
    measures: Tuple[str, ...]
    denominator: str
    missing_handling: str
    excluded_handling: str
    evidence_boundary: str
    methods: Tuple[MethodSpecification, ...]
    permitted_interpretation: str
    prohibited_interpretation: str
    materialization_status: str
    materialization_readiness: str
    artifact_path: str
    repository_source_basis: Tuple[str, ...]


@dataclass(frozen=True)
class ExtendedQuestion:
    """A typed, explicitly non-operationalised or non-collected question."""

    question_id: str
    text: str
    status: str
    prerequisites: Tuple[str, ...]
    permitted_interpretation: str
    prohibited_interpretation: str
    repository_source_basis: Tuple[str, ...]


@dataclass(frozen=True)
class ProtocolReference:
    """Versioned reference to authoritative protocol hypotheses."""

    version: str
    ordered_hypothesis_ids: Tuple[str, ...]
    declared_outcomes: Mapping[str, Tuple[str, ...]]
    fingerprint: str


@dataclass(frozen=True)
class ResearchQuestionRegistry:
    """Validated research-question registry."""

    version: str
    status: str
    fingerprint: str
    axes: Tuple[AxisIdentity, ...]
    questions: Tuple[ResearchQuestion, ...]
    extended_questions: Tuple[ExtendedQuestion, ...]
    protocol: ProtocolReference

    @property
    def all_question_ids(self) -> Tuple[str, ...]:
        """Return the complete deterministic accountability order."""

        return tuple(question.question_id for question in self.questions) + tuple(
            question.question_id for question in self.extended_questions
        )


@dataclass(frozen=True)
class AccountabilityEntry:
    """Typed accountability row after schema and scientific validation."""

    question_id: str
    item_type: str
    result_status: str
    view_kind: str
    scientific_status: str
    observational_unit: str
    population_definition: str
    n: int | None
    missing_n: int | None
    excluded_n: int | None
    denominator: str
    method: str
    method_readiness: str
    evidence_references: Tuple[str, ...]
    validity_threats: Tuple[str, ...]
    permitted_interpretation: str
    prohibited_interpretation: str
    registry_version: str
    registry_fingerprint: str
    protocol_version: str
    protocol_fingerprint: str
    identity_schema_version: str
    classifier_version: str
    analysis_timestamp: str
    warnings: Tuple[str, ...]
    hypothesis_results: Tuple["HypothesisAccountability", ...]


@dataclass(frozen=True)
class HypothesisAccountability:
    """One protocol-declared hypothesis outcome retained under RQ8."""

    hypothesis_id: str
    outcome: str
    validated_supply_status: str
    evidence_references: Tuple[str, ...]
    warnings: Tuple[str, ...]


@dataclass(frozen=True)
class AccountabilityLedger:
    """Complete, validated accountability ledger."""

    version: str
    entries: Tuple[AccountabilityEntry, ...]


def _load_yaml_mapping(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise ResearchQuestionRegistryError(f"{label} does not exist: {path}")
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ResearchQuestionRegistryError(f"{label} is not valid YAML: {exc}") from exc
    if not isinstance(payload, dict):
        raise ResearchQuestionRegistryError(f"{label} must contain a top-level object")
    return cast(dict[str, Any], payload)


def _load_schema(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ResearchQuestionRegistryError(f"schema does not exist: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ResearchQuestionRegistryError(f"schema is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ResearchQuestionRegistryError("schema must contain a top-level object")
    Draft202012Validator.check_schema(payload)
    return cast(dict[str, Any], payload)


def _json_fingerprint(payload: Mapping[str, Any]) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _schema_issues(
    payload: Mapping[str, Any],
    schema_path: Path,
) -> list[str]:
    validator = Draft202012Validator(
        _load_schema(schema_path),
        format_checker=FormatChecker(),
    )
    issues: list[str] = []
    for error in sorted(validator.iter_errors(payload), key=lambda item: list(item.path)):
        location = ".".join(str(part) for part in error.path) or "<root>"
        issues.append(f"{location}: {error.message}")
    return issues


def _protocol_reference(protocol_path: Path) -> ProtocolReference:
    payload = _load_yaml_mapping(protocol_path, "authoritative protocol")
    hypotheses = payload.get("hypotheses")
    if not isinstance(hypotheses, dict) or not hypotheses:
        raise ResearchQuestionRegistryError(
            "authoritative protocol must declare a non-empty hypotheses object"
        )
    version = payload.get("protocol_version")
    if not isinstance(version, str) or not version.strip():
        raise ResearchQuestionRegistryError(
            "authoritative protocol must declare protocol_version"
        )
    declared_outcomes: dict[str, Tuple[str, ...]] = {}
    for hypothesis_id, declaration in hypotheses.items():
        if not isinstance(declaration, dict):
            raise ResearchQuestionRegistryError(
                f"authoritative protocol hypothesis {hypothesis_id} must be an object"
            )
        outcomes = declaration.get("declared_outcomes")
        if not isinstance(outcomes, list) or not outcomes:
            raise ResearchQuestionRegistryError(
                f"authoritative protocol hypothesis {hypothesis_id} must declare outcomes"
            )
        declared_outcomes[str(hypothesis_id)] = tuple(str(item) for item in outcomes)
    return ProtocolReference(
        version=version.strip(),
        ordered_hypothesis_ids=tuple(str(key) for key in hypotheses),
        declared_outcomes=declared_outcomes,
        fingerprint=hashlib.sha256(protocol_path.read_bytes()).hexdigest(),
    )


def _resolve_repository_path(repo_root: Path, value: str) -> Path | None:
    candidate = Path(value)
    if candidate.is_absolute():
        return None
    resolved_root = repo_root.resolve()
    resolved = (resolved_root / candidate).resolve()
    try:
        resolved.relative_to(resolved_root)
    except ValueError:
        return None
    return resolved


def _semantic_registry_issues(
    payload: Mapping[str, Any],
    protocol: ProtocolReference,
    repo_root: Path,
) -> list[str]:
    issues: list[str] = []
    axes = cast(Sequence[Mapping[str, Any]], payload.get("canonical_axes", []))
    axis_pairs = tuple(
        (str(axis.get("canonical_name", "")), str(axis.get("display_code", "")))
        for axis in axes
    )
    if axis_pairs != CANONICAL_AXES:
        issues.append(
            "canonical_axes must preserve ordered pairs "
            "MARINE/M, MARITIME/T, OCEANIC/O, HYDRONIZATION/H"
        )

    questions = cast(Sequence[Mapping[str, Any]], payload.get("questions", []))
    extended = cast(
        Sequence[Mapping[str, Any]], payload.get("extended_questions", [])
    )
    question_ids = tuple(str(item.get("id", "")) for item in questions)
    extended_ids = tuple(str(item.get("id", "")) for item in extended)
    all_ids = question_ids + extended_ids
    if len(all_ids) != len(set(all_ids)):
        issues.append("question IDs must be unique across questions and extended_questions")
    if question_ids != REQUIRED_QUESTION_IDS:
        issues.append(
            "questions must preserve the approved order: "
            + ", ".join(REQUIRED_QUESTION_IDS)
        )
    if extended_ids != REQUIRED_EXTENDED_QUESTION_IDS:
        issues.append(
            "extended_questions must preserve the approved order: "
            + ", ".join(REQUIRED_EXTENDED_QUESTION_IDS)
        )

    question_id_set = set(question_ids)
    for question in questions:
        question_id = str(question.get("id", ""))
        parent_id = str(question.get("parent_id", ""))
        if parent_id and (parent_id == question_id or parent_id not in question_id_set):
            issues.append(f"{question_id}: parent_id must reference another RQ")
        if "." in question_id and not parent_id:
            issues.append(f"{question_id}: child question requires parent_id")
        expected_axis = RQ4_AXIS_CONTRACT.get(question_id)
        if expected_axis is not None:
            actual_axis = (
                str(question.get("axis_name", "")),
                str(question.get("axis_code", "")),
            )
            if parent_id != "RQ4":
                issues.append(f"{question_id}: parent_id must be RQ4")
            if actual_axis != expected_axis:
                issues.append(
                    f"{question_id}: expected canonical axis "
                    f"{expected_axis[0]}/{expected_axis[1]}"
                )
        elif "axis_name" in question or "axis_code" in question:
            name = str(question.get("axis_name", ""))
            code = str(question.get("axis_code", ""))
            if (name, code) not in CANONICAL_AXES:
                issues.append(f"{question_id}: noncanonical axis pair {name}/{code}")

        method_names: set[str] = set()
        methods = cast(Sequence[Mapping[str, Any]], question.get("methods", []))
        for method in methods:
            name = str(method.get("name", ""))
            if name in method_names:
                issues.append(f"{question_id}: duplicate method {name}")
            method_names.add(name)
            if str(method.get("readiness", "")) == "implemented":
                if str(method.get("approval_status", "")) != "repository_approved":
                    issues.append(
                        f"{question_id}.{name}: implemented method requires "
                        "repository_approved"
                    )
                reference = str(method.get("implementation_reference", ""))
                resolved_reference = _resolve_repository_path(repo_root, reference)
                if not reference or resolved_reference is None or not resolved_reference.is_file():
                    issues.append(
                        f"{question_id}.{name}: implemented method requires an "
                        "existing repository implementation_reference"
                    )

        materialization = cast(
            Mapping[str, Any], question.get("materialization", {})
        )
        if str(materialization.get("status", "")) == "materialized":
            artifact_path = str(materialization.get("artifact_path", ""))
            resolved_artifact = _resolve_repository_path(repo_root, artifact_path)
            if (
                not artifact_path
                or resolved_artifact is None
                or not resolved_artifact.exists()
            ):
                issues.append(
                    f"{question_id}: materialized target requires an existing "
                    "repository artifact_path"
                )

        for source in cast(
            Sequence[str], question.get("repository_source_basis", [])
        ):
            resolved_source = _resolve_repository_path(repo_root, str(source))
            if resolved_source is None or not resolved_source.is_file():
                issues.append(
                    f"{question_id}: repository_source_basis does not resolve: {source}"
                )

    for question in extended:
        question_id = str(question.get("id", ""))
        expected_status = ETQ_STATUS_BY_ID.get(question_id)
        if expected_status and question.get("status") != expected_status:
            issues.append(
                f"{question_id}: expected status {expected_status}, "
                f"got {question.get('status')}"
            )
        for source in cast(
            Sequence[str], question.get("repository_source_basis", [])
        ):
            resolved_source = _resolve_repository_path(repo_root, str(source))
            if resolved_source is None or not resolved_source.is_file():
                issues.append(
                    f"{question_id}: repository_source_basis does not resolve: {source}"
                )

    hypothesis_reference = cast(
        Mapping[str, Any], payload.get("hypothesis_reference", {})
    )
    registry_hypothesis_ids = tuple(
        str(item) for item in hypothesis_reference.get("ordered_ids", [])
    )
    if registry_hypothesis_ids != protocol.ordered_hypothesis_ids:
        issues.append(
            "hypothesis_reference.ordered_ids must exactly match the authoritative "
            "protocol order"
        )
    h2_rule = cast(
        Mapping[str, Any], hypothesis_reference.get("h2_supply_rule", {})
    )
    if (
        h2_rule.get("minimum_eqf_levels") != [6, 7]
        or h2_rule.get("required_supply_status") != "independently_validated"
        or h2_rule.get("generated_designs_are_supply") is not False
        or h2_rule.get("default_without_supply") != "not_computable"
    ):
        issues.append(
            "H2 must remain not_computable without independently validated "
            "EQF 6-7 supply, and generated designs cannot count as supply"
        )

    allowed_statuses = tuple(
        str(item) for item in payload.get("allowed_result_statuses", [])
    )
    if allowed_statuses != ALLOWED_RESULT_STATUSES:
        issues.append("allowed_result_statuses must preserve the approved contract")
    required_fields = {
        str(item) for item in payload.get("required_accountability_fields", [])
    }
    missing_baseline = BASELINE_ACCOUNTABILITY_FIELDS - required_fields
    if missing_baseline:
        issues.append(
            "required_accountability_fields is missing: "
            + ", ".join(sorted(missing_baseline))
        )
    return issues


def _parse_method(payload: Mapping[str, Any]) -> MethodSpecification:
    return MethodSpecification(
        name=str(payload["name"]),
        readiness=str(payload["readiness"]),
        approval_status=str(payload["approval_status"]),
        prerequisite=str(payload["prerequisite"]),
        implementation_reference=str(payload.get("implementation_reference", "")),
    )


def _parse_research_question(payload: Mapping[str, Any]) -> ResearchQuestion:
    materialization = cast(Mapping[str, Any], payload["materialization"])
    return ResearchQuestion(
        question_id=str(payload["id"]),
        parent_id=str(payload.get("parent_id", "")),
        text=str(payload["text"]),
        status=str(payload["status"]),
        axis_name=str(payload.get("axis_name", "")),
        axis_code=str(payload.get("axis_code", "")),
        construct=str(payload["construct"]),
        population_definition=str(payload["population_definition"]),
        target_view=str(payload["target_view"]),
        view_kind=str(payload["view_kind"]),
        observational_unit=str(payload["observational_unit"]),
        variables=tuple(str(item) for item in payload["variables"]),
        indicators=tuple(str(item) for item in payload["indicators"]),
        measures=tuple(str(item) for item in payload["measures"]),
        denominator=str(payload["denominator"]),
        missing_handling=str(payload["missing_handling"]),
        excluded_handling=str(payload["excluded_handling"]),
        evidence_boundary=str(payload["evidence_boundary"]),
        methods=tuple(
            _parse_method(cast(Mapping[str, Any], item))
            for item in payload["methods"]
        ),
        permitted_interpretation=str(payload["permitted_interpretation"]),
        prohibited_interpretation=str(payload["prohibited_interpretation"]),
        materialization_status=str(materialization["status"]),
        materialization_readiness=str(materialization["readiness"]),
        artifact_path=str(materialization["artifact_path"]),
        repository_source_basis=tuple(
            str(item) for item in payload["repository_source_basis"]
        ),
    )


def _parse_extended_question(payload: Mapping[str, Any]) -> ExtendedQuestion:
    return ExtendedQuestion(
        question_id=str(payload["id"]),
        text=str(payload["text"]),
        status=str(payload["status"]),
        prerequisites=tuple(str(item) for item in payload["prerequisites"]),
        permitted_interpretation=str(payload["permitted_interpretation"]),
        prohibited_interpretation=str(payload["prohibited_interpretation"]),
        repository_source_basis=tuple(
            str(item) for item in payload["repository_source_basis"]
        ),
    )


def load_research_question_registry(
    path: Path = DEFAULT_REGISTRY_PATH,
    *,
    protocol_path: Path = DEFAULT_PROTOCOL_PATH,
    schema_path: Path = DEFAULT_REGISTRY_SCHEMA_PATH,
    repo_root: Path = REPO_ROOT,
) -> ResearchQuestionRegistry:
    """Load and validate the proposed registry against schema and protocol."""

    payload = _load_yaml_mapping(path, "research-question registry")
    issues = _schema_issues(payload, schema_path)
    protocol = _protocol_reference(protocol_path)
    if not issues:
        issues.extend(_semantic_registry_issues(payload, protocol, repo_root))
    if issues:
        raise ResearchQuestionRegistryError(
            "research-question registry validation failed:\n- "
            + "\n- ".join(issues)
        )

    axes = tuple(
        AxisIdentity(
            canonical_name=str(axis["canonical_name"]),
            display_code=str(axis["display_code"]),
            meaning=str(axis["meaning"]),
        )
        for axis in cast(Sequence[Mapping[str, Any]], payload["canonical_axes"])
    )
    questions = tuple(
        _parse_research_question(question)
        for question in cast(Sequence[Mapping[str, Any]], payload["questions"])
    )
    extended_questions = tuple(
        _parse_extended_question(question)
        for question in cast(
            Sequence[Mapping[str, Any]], payload["extended_questions"]
        )
    )
    return ResearchQuestionRegistry(
        version=str(payload["registry_version"]),
        status=str(payload["status"]),
        fingerprint=_json_fingerprint(payload),
        axes=axes,
        questions=questions,
        extended_questions=extended_questions,
        protocol=protocol,
    )


def _accountability_semantic_issues(
    payload: Mapping[str, Any],
    registry: ResearchQuestionRegistry,
) -> list[str]:
    issues: list[str] = []
    entries = cast(Sequence[Mapping[str, Any]], payload.get("entries", []))
    entry_ids = tuple(str(entry.get("question_id", "")) for entry in entries)
    if len(entry_ids) != len(set(entry_ids)):
        issues.append("accountability ledger contains duplicate question_id values")
    expected_ids = registry.all_question_ids
    if set(entry_ids) != set(expected_ids):
        missing = sorted(set(expected_ids) - set(entry_ids))
        unexpected = sorted(set(entry_ids) - set(expected_ids))
        if missing:
            issues.append("accountability ledger omits: " + ", ".join(missing))
        if unexpected:
            issues.append(
                "accountability ledger contains unregistered IDs: "
                + ", ".join(unexpected)
            )
    if entry_ids != expected_ids:
        issues.append("accountability ledger entries must preserve registry order")

    research_questions = {
        question.question_id: question for question in registry.questions
    }
    extended_questions = {
        question.question_id: question for question in registry.extended_questions
    }
    metadata_tuples: set[tuple[str, ...]] = set()
    for entry in entries:
        question_id = str(entry.get("question_id", ""))
        result_status = str(entry.get("result_status", ""))
        expected_scientific_status = SCIENTIFIC_STATUS_BY_RESULT.get(result_status)
        if entry.get("scientific_status") != expected_scientific_status:
            issues.append(
                f"{question_id}: scientific_status must be "
                f"{expected_scientific_status} for {result_status}"
            )

        metadata = (
            str(entry.get("registry_version", "")),
            str(entry.get("registry_fingerprint", "")),
            str(entry.get("protocol_version", "")),
            str(entry.get("protocol_fingerprint", "")),
            str(entry.get("identity_schema_version", "")),
            str(entry.get("classifier_version", "")),
            str(entry.get("analysis_timestamp", "")),
        )
        metadata_tuples.add(metadata)
        if entry.get("registry_version") != registry.version:
            issues.append(f"{question_id}: registry_version mismatch")
        if entry.get("registry_fingerprint") != registry.fingerprint:
            issues.append(f"{question_id}: registry_fingerprint mismatch")
        if entry.get("protocol_version") != registry.protocol.version:
            issues.append(f"{question_id}: protocol_version mismatch")
        if entry.get("protocol_fingerprint") != registry.protocol.fingerprint:
            issues.append(f"{question_id}: protocol_fingerprint mismatch")

        if question_id in extended_questions:
            extended_question = extended_questions[question_id]
            expected_result = extended_question.status
            if result_status != expected_result:
                issues.append(
                    f"{question_id}: extended question result_status must remain "
                    f"{expected_result}"
                )
            if entry.get("item_type") != "extended_question":
                issues.append(f"{question_id}: item_type must be extended_question")
            if entry.get("view_kind") != "not_defined":
                issues.append(f"{question_id}: view_kind must be not_defined")
            if entry.get("observational_unit") != "not_defined_pending_operationalisation":
                issues.append(
                    f"{question_id}: observational_unit must remain undefined"
                )
            if entry.get("population_definition") != "not_defined_pending_operationalisation":
                issues.append(
                    f"{question_id}: population_definition must remain undefined"
                )
            if entry.get("denominator") != "not_defined_pending_operationalisation":
                issues.append(f"{question_id}: denominator must remain undefined")
            if entry.get("method") != "not_applicable":
                issues.append(f"{question_id}: method must be not_applicable")
            if entry.get("method_readiness") != "not_applicable":
                issues.append(
                    f"{question_id}: method_readiness must be not_applicable"
                )
            if any(entry.get(field) is not None for field in ("n", "missing_n", "excluded_n")):
                issues.append(
                    f"{question_id}: counts must be null while not operationalised "
                    "or not collected"
                )
            if entry.get("evidence_references"):
                issues.append(
                    f"{question_id}: non-operationalised/non-collected entry "
                    "cannot contain evidence_references"
                )
            if (
                entry.get("permitted_interpretation")
                != extended_question.permitted_interpretation
            ):
                issues.append(f"{question_id}: permitted_interpretation drift")
            if (
                entry.get("prohibited_interpretation")
                != extended_question.prohibited_interpretation
            ):
                issues.append(f"{question_id}: prohibited_interpretation drift")
        elif question_id in research_questions:
            research_question = research_questions[question_id]
            if entry.get("item_type") != "research_question":
                issues.append(f"{question_id}: item_type must be research_question")
            if entry.get("view_kind") != research_question.view_kind:
                issues.append(f"{question_id}: view_kind must match the registry")
            if (
                entry.get("observational_unit")
                != research_question.observational_unit
            ):
                issues.append(
                    f"{question_id}: observational_unit must match the registry"
                )
            if (
                entry.get("population_definition")
                != research_question.population_definition
            ):
                issues.append(
                    f"{question_id}: population_definition must match the registry"
                )
            if entry.get("denominator") != research_question.denominator:
                issues.append(f"{question_id}: denominator must match the registry")
            if (
                entry.get("permitted_interpretation")
                != research_question.permitted_interpretation
            ):
                issues.append(f"{question_id}: permitted_interpretation drift")
            if (
                entry.get("prohibited_interpretation")
                != research_question.prohibited_interpretation
            ):
                issues.append(f"{question_id}: prohibited_interpretation drift")

            selected_method = next(
                (
                    method
                    for method in research_question.methods
                    if method.name == entry.get("method")
                ),
                None,
            )
            if selected_method is None:
                issues.append(f"{question_id}: method is not declared by the registry")
            elif entry.get("method_readiness") != selected_method.readiness:
                issues.append(
                    f"{question_id}: method_readiness must match the registry method"
                )

            if result_status in {"answered", "partially_answered"}:
                if research_question.materialization_status != "materialized":
                    issues.append(
                        f"{question_id}: answered state requires a materialized target"
                    )
                if selected_method is None or selected_method.readiness != "implemented":
                    issues.append(
                        f"{question_id}: answered state requires an implemented method"
                    )
                if entry.get("n") is None:
                    issues.append(f"{question_id}: answered state requires n")
                if not entry.get("evidence_references"):
                    issues.append(
                        f"{question_id}: answered state requires evidence_references"
                    )
            if result_status in {
                "not_computable",
                "not_operationalised",
                "not_collected",
                "review_required",
            } and not entry.get("warnings"):
                issues.append(f"{question_id}: unresolved state requires warnings")

            hypothesis_results = cast(
                Sequence[Mapping[str, Any]], entry.get("hypothesis_results", [])
            )
            if question_id == "RQ8":
                hypothesis_ids = tuple(
                    str(result.get("hypothesis_id", ""))
                    for result in hypothesis_results
                )
                if hypothesis_ids != registry.protocol.ordered_hypothesis_ids:
                    issues.append(
                        "RQ8: hypothesis_results must preserve every authoritative "
                        "protocol hypothesis in order"
                    )
                for result in hypothesis_results:
                    hypothesis_id = str(result.get("hypothesis_id", ""))
                    outcome = str(result.get("outcome", ""))
                    if outcome not in registry.protocol.declared_outcomes.get(
                        hypothesis_id, ()
                    ):
                        issues.append(
                            f"RQ8.{hypothesis_id}: outcome is not declared by the "
                            "authoritative protocol"
                        )
                    supply_status = str(
                        result.get("validated_supply_status", "")
                    )
                    if hypothesis_id == "H2":
                        if (
                            supply_status != "independently_validated"
                            and outcome != "not_computable"
                        ):
                            issues.append(
                                "RQ8.H2: outcome must remain not_computable without "
                                "independently validated EQF 6-7 supply"
                            )
                    elif supply_status != "not_applicable":
                        issues.append(
                            f"RQ8.{hypothesis_id}: validated_supply_status must be "
                            "not_applicable"
                        )
            elif hypothesis_results:
                issues.append(
                    f"{question_id}: hypothesis_results are only permitted for RQ8"
                )

    if len(metadata_tuples) > 1:
        issues.append(
            "all accountability entries must use one registry, protocol, identity, "
            "classifier and analysis timestamp snapshot"
        )
    return issues


def _parse_accountability_entry(payload: Mapping[str, Any]) -> AccountabilityEntry:
    return AccountabilityEntry(
        question_id=str(payload["question_id"]),
        item_type=str(payload["item_type"]),
        result_status=str(payload["result_status"]),
        view_kind=str(payload["view_kind"]),
        scientific_status=str(payload["scientific_status"]),
        observational_unit=str(payload["observational_unit"]),
        population_definition=str(payload["population_definition"]),
        n=cast(int | None, payload["n"]),
        missing_n=cast(int | None, payload["missing_n"]),
        excluded_n=cast(int | None, payload["excluded_n"]),
        denominator=str(payload["denominator"]),
        method=str(payload["method"]),
        method_readiness=str(payload["method_readiness"]),
        evidence_references=tuple(
            str(item) for item in payload["evidence_references"]
        ),
        validity_threats=tuple(str(item) for item in payload["validity_threats"]),
        permitted_interpretation=str(payload["permitted_interpretation"]),
        prohibited_interpretation=str(payload["prohibited_interpretation"]),
        registry_version=str(payload["registry_version"]),
        registry_fingerprint=str(payload["registry_fingerprint"]),
        protocol_version=str(payload["protocol_version"]),
        protocol_fingerprint=str(payload["protocol_fingerprint"]),
        identity_schema_version=str(payload["identity_schema_version"]),
        classifier_version=str(payload["classifier_version"]),
        analysis_timestamp=str(payload["analysis_timestamp"]),
        warnings=tuple(str(item) for item in payload["warnings"]),
        hypothesis_results=tuple(
            HypothesisAccountability(
                hypothesis_id=str(item["hypothesis_id"]),
                outcome=str(item["outcome"]),
                validated_supply_status=str(item["validated_supply_status"]),
                evidence_references=tuple(
                    str(reference) for reference in item["evidence_references"]
                ),
                warnings=tuple(str(warning) for warning in item["warnings"]),
            )
            for item in cast(
                Sequence[Mapping[str, Any]],
                payload.get("hypothesis_results", []),
            )
        ),
    )


def validate_accountability_payload(
    payload: Mapping[str, Any],
    registry: ResearchQuestionRegistry,
    *,
    schema_path: Path = DEFAULT_ACCOUNTABILITY_SCHEMA_PATH,
) -> AccountabilityLedger:
    """Validate complete accountability coverage and reject manufactured answers."""

    issues = _schema_issues(payload, schema_path)
    if not issues:
        issues.extend(_accountability_semantic_issues(payload, registry))
    if issues:
        raise ResearchQuestionRegistryError(
            "research-question accountability validation failed:\n- "
            + "\n- ".join(issues)
        )
    return AccountabilityLedger(
        version=str(payload["ledger_version"]),
        entries=tuple(
            _parse_accountability_entry(entry)
            for entry in cast(Sequence[Mapping[str, Any]], payload["entries"])
        ),
    )


def load_accountability_ledger(
    path: Path,
    registry: ResearchQuestionRegistry,
    *,
    schema_path: Path = DEFAULT_ACCOUNTABILITY_SCHEMA_PATH,
) -> AccountabilityLedger:
    """Load a YAML or JSON accountability ledger and validate full coverage."""

    payload = _load_yaml_mapping(path, "research-question accountability ledger")
    return validate_accountability_payload(
        payload,
        registry,
        schema_path=schema_path,
    )
