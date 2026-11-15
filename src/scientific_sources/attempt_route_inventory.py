"""Conservative second-pass route inventory for MOR-26 G2 evidence.

This is a risk inventory, not a proof that all network routes are governed.
Non-literal Python subprocess paths are UNKNOWN and must not be marked safe.
"""
from __future__ import annotations

import ast
from pathlib import Path
from typing import Iterable, List


_PROCESS_NAMES = {
    "run", "Popen", "call", "check_call", "check_output",
    "getoutput", "getstatusoutput",
}
_NETWORK_TOOLS = {"curl", "wget", "nc", "telnet", "ssh", "ftp", "pip"}


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
                        Path(words[0]).name in _NETWORK_TOOLS
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
