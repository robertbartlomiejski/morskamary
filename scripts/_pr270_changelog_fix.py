from pathlib import Path

path = Path(__file__).resolve().parents[1] / "CHANGELOG.txt"
text = path.read_text(encoding="utf-8")
entry = (
    "PR #270 review reconciliation: pandas>=1.5 compatibility; canonical "
    "axis_code; evidence-surface provenance; tourism citation boundary; "
    "deterministic generated-output validation.\n"
)
if text.startswith(entry):
    text = text[len(entry):]
elif entry in text:
    text = text.replace(entry, "", 1)
separator = "" if text.endswith("\n") else "\n"
path.write_text(text + separator + entry, encoding="utf-8")
