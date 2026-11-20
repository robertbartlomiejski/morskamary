"""Conservative second-pass route inventory for MOR-26 G2 evidence.

This is a risk inventory, not a proof that all network routes are governed.
Non-literal Python subprocess paths are UNKNOWN until explicitly dispositioned.
"""
from __future__ import annotations

import ast
import hashlib
import json
import re
from pathlib import Path
from typing import Iterable, List


_PROCESS_NAMES = {
    "run", "Popen", "call", "check_call", "check_output",
    "getoutput", "getstatusoutput",
}
_NETWORK_TOOLS = {"curl", "wget", "nc", "telnet", "ssh", "ftp", "pip"}
_ALLOWED_DISPOSITIONS = {
    "NON_NETWORK_LOCAL_PROCESS",
    "NON_PROVIDER_SCM_NETWORK",
    "TEST_ONLY",
    "EXPLICITLY_BLOCKED_IN_LIVE",
    "NON_NETWORK_LOCAL_IMPORT",
}


def find_unverified_network_routes(
    repo_root: Path, roots: Iterable[str] = ("src", "scripts"),
) -> List[str]:
    """List subprocess and dynamic-import patterns needing manual route review."""
    files = sorted(repo_root.glob("*.py"))
    for root in roots:
        files.extend(sorted((repo_root / root).rglob("*.py")))
    findings: List[str] = []
    for path in files:
        rel = path.relative_to(repo_root).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeError, OSError):
            findings.append(f"{rel}:0 UNVERIFIED unparseable")
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = node.func.attr if isinstance(node.func, ast.Attribute) else (
                node.func.id if isinstance(node.func, ast.Name) else ""
            )
            base = (
                node.func.value.id if isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name) else ""
            )
            if base == "subprocess" and name in _PROCESS_NAMES:
                arg = node.args[0] if node.args else None
                if isinstance(arg, (ast.List, ast.Tuple)):
                    words = [
                        e.value if isinstance(e, ast.Constant)
                        and isinstance(e.value, str) else None
                        for e in arg.elts
                    ]
                    if None in words:
                        findings.append(f"{rel}:{node.lineno} UNVERIFIED argv")
                    elif words and (
                        Path(words[0] or "").name in _NETWORK_TOOLS
                        or words[0] == "git"
                        and any(w in ("fetch", "pull", "push", "clone") for w in words)
                    ):
                        findings.append(f"{rel}:{node.lineno} network subprocess")
                elif isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    if any(s in arg.value for s in ("curl", "wget", "git fetch")):
                        findings.append(f"{rel}:{node.lineno} network shell")
                    else:
                        findings.append(f"{rel}:{node.lineno} UNVERIFIED shell")
                else:
                    findings.append(f"{rel}:{node.lineno} UNVERIFIED argv")
                if any(
                    kw.arg == "shell" and not isinstance(kw.value, ast.Constant)
                    or kw.arg == "shell" and isinstance(kw.value, ast.Constant)
                    and kw.value.value is True for kw in node.keywords
                ):
                    findings.append(f"{rel}:{node.lineno} UNVERIFIED shell option")
            elif base == "os" and (
                name in ("system", "popen") or name.startswith(("exec", "spawn"))
            ):
                findings.append(f"{rel}:{node.lineno} UNVERIFIED os.{name}")
            elif name in ("__import__", "import_module") and node.args:
                if not isinstance(node.args[0], ast.Constant):
                    findings.append(f"{rel}:{node.lineno} UNVERIFIED dynamic import")
    return sorted(set(findings))


def _finding_key(finding: str) -> str:
    path, rest = finding.split(":", 1)
    _, kind = rest.split(" ", 1)
    return f"{path}|{kind}"


def _git_blob_sha1(path: Path) -> str:
    """Return the content-bound Git blob identity for one reviewed source file."""
    data = path.read_bytes()
    header = f"blob {len(data)}\0".encode("ascii")
    return hashlib.sha1(header + data, usedforsecurity=False).hexdigest()


def validate_route_dispositions(
    repo_root: Path,
    disposition_path: Path | None = None,
) -> List[str]:
    """Fail closed unless every current conservative finding is explicitly reviewed."""
    path = disposition_path or repo_root / "config" / "mor26_route_dispositions.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return [f"route disposition manifest unavailable: {type(exc).__name__}"]
    rows = payload.get("dispositions") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return ["route disposition manifest must contain a dispositions list"]

    dispositions = {}
    errors: List[str] = []
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            errors.append(f"disposition row {index} must be an object")
            continue
        key = str(row.get("key", "")).strip()
        classification = str(row.get("classification", "")).strip()
        rationale = str(row.get("rationale", "")).strip()
        provider_reachable = row.get("scientific_provider_http_reachable")
        reviewed_blob = str(row.get("source_git_blob_sha1", "")).strip()
        if not key or key in dispositions:
            errors.append(f"invalid or duplicate disposition key at row {index}")
            continue
        if classification not in _ALLOWED_DISPOSITIONS:
            errors.append(f"{key}: invalid disposition classification")
        if not rationale:
            errors.append(f"{key}: missing disposition rationale")
        if provider_reachable is not False:
            errors.append(f"{key}: scientific provider HTTP must be explicitly false")
        if not re.fullmatch(r"[0-9a-f]{40}", reviewed_blob):
            errors.append(f"{key}: missing reviewed source blob identity")
        dispositions[key] = row

    findings = find_unverified_network_routes(repo_root)
    current_keys = {_finding_key(item) for item in findings}
    for finding in findings:
        key = _finding_key(finding)
        if key not in dispositions:
            errors.append(f"UNDISPOSITIONED: {finding}")
            continue
        source_path = repo_root / finding.split(":", 1)[0]
        try:
            current_blob = _git_blob_sha1(source_path)
        except OSError:
            errors.append(f"SOURCE_UNREADABLE: {key}")
            continue
        if dispositions[key].get("source_git_blob_sha1") != current_blob:
            errors.append(f"SOURCE_CHANGED: {key}")
    for key in sorted(set(dispositions) - current_keys):
        errors.append(f"STALE_DISPOSITION: {key}")
    return sorted(set(errors))
