from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
PATCH_PATH = ROOT / "scripts" / "_pr270_consolidated_patch.py"


def _load_patch_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("pr270_consolidated_patch", PATCH_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load temporary patch module from {PATCH_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _indent_block(block: str, width: int) -> str:
    prefix = " " * width
    return "".join(
        prefix + line if line.strip() else line
        for line in block.splitlines(keepends=True)
    )


def robust_replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    if text.count(old) == 1:
        target.write_text(text.replace(old, new, 1), encoding="utf-8")
        return
    matches: list[tuple[str, str]] = []
    for width in range(4, 41, 4):
        candidate = _indent_block(old, width)
        if text.count(candidate) == 1:
            matches.append((candidate, _indent_block(new, width)))
    if len(matches) != 1:
        raise RuntimeError(
            f"{path}: expected one exact or consistently-indented match; "
            f"found {len(matches)} for {old[:100]!r}"
        )
    candidate, replacement = matches[0]
    target.write_text(text.replace(candidate, replacement, 1), encoding="utf-8")


patch = _load_patch_module()
patch.replace_once = robust_replace_once
patch.main()
