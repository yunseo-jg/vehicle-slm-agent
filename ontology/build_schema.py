"""ontology/vehicle.yaml → ontology/generated/{tools.json, initial_state.json}

tools.json          : 도구별 JSON Schema (MCP 서버, 평가셋 검증, 프롬프트에서 공통 사용)
initial_state.json  : 시뮬레이터 초기 상태. 키는 VSS 경로 그대로

사용: python ontology/build_schema.py [--check]
--check 는 생성물이 최신인지만 확인 (CI용)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "vehicle.yaml"
OUT_DIR = ROOT / "generated"

TYPE_MAP = {"int": "integer", "float": "number", "string": "string", "bool": "boolean"}


def load_ontology(path: Path = SRC) -> dict:
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def param_to_schema(name: str, spec: dict) -> dict:
    if spec["type"] == "enum":
        schema: dict = {"type": "string", "enum": list(spec["values"])}
    else:
        schema = {"type": TYPE_MAP[spec["type"]]}
        if "min" in spec:
            schema["minimum"] = spec["min"]
        if "max" in spec:
            schema["maximum"] = spec["max"]
    desc = []
    if spec.get("unit"):
        desc.append(f"unit: {spec['unit']}")
    if "default" in spec:
        schema["default"] = spec["default"]
        desc.append(f"default: {spec['default']}")
    if desc:
        schema["description"] = ", ".join(desc)
    return schema


def build_tools(onto: dict) -> list[dict]:
    tools = []
    for fn in onto["functions"]:
        props = {n: param_to_schema(n, s) for n, s in fn.get("params", {}).items()}
        required = [n for n, s in fn.get("params", {}).items() if s.get("required")]
        tools.append(
            {
                "name": fn["id"],
                "domain": fn["domain"],
                "description": " ".join(str(fn["description"]).split()),
                "parameters": {
                    "type": "object",
                    "properties": props,
                    "required": required,
                    "additionalProperties": False,
                },
                "precondition": fn.get("precondition", []),
                "vss": fn.get("vss"),
                "ext": bool(fn.get("ext", False)),
            }
        )
    return tools


def expand_vss(fn: dict, instance_map: dict) -> dict[str, object]:
    """함수 하나가 건드리는 VSS 경로들과 초기값. {경로: 초기값}"""
    vss = fn.get("vss")
    initial = fn.get("initial")
    if vss is None:
        return {}
    if isinstance(vss, dict):  # field → path 형태 (get 계열)
        return {path: (initial or {}).get(field) for field, path in vss.items()}
    # 템플릿 문자열. {zone} 같은 자리표시자를 instance_map 으로 펼친다
    paths = {vss: initial}
    for pname, mapping in instance_map.items():
        token = "{" + pname + "}"
        if token in vss:
            paths = {vss.replace(token, inst): initial for inst in mapping.values()}
    return paths


def build_initial_state(onto: dict) -> dict[str, object]:
    state: dict[str, object] = dict(onto.get("state_signals", {}))
    for fn in onto["functions"]:
        state.update(expand_vss(fn, onto.get("instance_map", {})))
    return dict(sorted(state.items()))


def render(onto: dict) -> dict[str, str]:
    return {
        "tools.json": json.dumps(build_tools(onto), ensure_ascii=False, indent=2) + "\n",
        "initial_state.json": json.dumps(build_initial_state(onto), ensure_ascii=False, indent=2)
        + "\n",
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="생성물이 최신인지만 확인")
    args = ap.parse_args()

    outputs = render(load_ontology())
    OUT_DIR.mkdir(exist_ok=True)
    stale = []
    for name, content in outputs.items():
        target = OUT_DIR / name
        if args.check:
            if not target.exists() or target.read_text(encoding="utf-8") != content:
                stale.append(name)
        else:
            target.write_text(content, encoding="utf-8")
            print(f"wrote {target.relative_to(ROOT.parent)}")
    if stale:
        print(f"stale: {', '.join(stale)}. run `make schema`", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
