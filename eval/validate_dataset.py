"""평가셋이 온톨로지와 맞는지 검사. 없는 도구, enum 밖 값, 범위 밖 값, 중복 id.

python eval/validate_dataset.py eval/data/*.jsonl
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "ontology" / "generated" / "tools.json"
TYPES = {"direct", "indirect", "missing_arg", "multiturn", "unsafe", "no_tool"}


def load_tools() -> dict[str, dict]:
    with TOOLS.open(encoding="utf-8") as f:
        return {t["name"]: t for t in json.load(f)}


def check_case(case: dict, tools: dict[str, dict]) -> list[str]:
    errs = []
    if case.get("type") not in TYPES:
        errs.append(f"type must be one of {sorted(TYPES)}")
    exp = case.get("expected", {})
    if exp.get("ask") or exp.get("tool") is None:
        return errs
    tool = tools.get(exp["tool"])
    if tool is None:
        return errs + [f"unknown tool {exp['tool']!r}"]
    props = tool["parameters"]["properties"]
    for k, v in exp.get("args", {}).items():
        if k not in props:
            errs.append(f"unknown arg {k!r} for {exp['tool']}")
            continue
        p = props[k]
        if "enum" in p and v not in p["enum"]:
            errs.append(f"{k}={v!r} not in {p['enum']}")
        if "minimum" in p and v < p["minimum"] or "maximum" in p and v > p["maximum"]:
            errs.append(f"{k}={v} out of range")
    return errs


def main(paths: list[str]) -> int:
    tools = load_tools()
    bad = 0
    for path in paths:
        seen: set[str] = set()
        for lineno, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            case = json.loads(line)
            errs = check_case(case, tools)
            if case["id"] in seen:
                errs.append("duplicate id")
            seen.add(case["id"])
            for e in errs:
                print(f"{path}:{lineno} [{case['id']}] {e}")
                bad += 1
    print(f"{'ok' if not bad else bad} problems" if bad else "ok")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
