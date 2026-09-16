import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ontology.build_schema import (  # noqa: E402
    build_initial_state,
    build_tools,
    load_ontology,
    render,
)

ROOT = Path(__file__).resolve().parent.parent
ONTO = load_ontology()
ID_RE = re.compile(r"^(set|get|search|call|send|start|stop)_[a-z0-9_]+$")
PRECOND_RE = re.compile(r"^(power_on|parked|speed_below_\d+)$")
DOMAINS = {"hvac", "media", "nav", "phone_manual", "settings", "status"}


def test_ids_unique_and_named():
    ids = [f["id"] for f in ONTO["functions"]]
    assert len(ids) == len(set(ids)), "duplicate id"
    for i in ids:
        assert ID_RE.match(i), f"bad id {i}"


def test_required_fields():
    for f in ONTO["functions"]:
        for k in ("id", "domain", "description", "params", "precondition", "ko"):
            assert k in f, f"{f.get('id')} missing {k}"
        assert f["domain"] in DOMAINS, f["id"]
        assert len(f["ko"]) >= 3, f"{f['id']} needs 3+ example utterances"
        assert len(f["params"]) <= 3, f"{f['id']} has more than 3 params"
        for p in f["precondition"]:
            assert PRECOND_RE.match(p), f"{f['id']} bad precondition {p}"
        if not f.get("ext"):
            assert f.get("vss"), f"{f['id']} needs vss path or ext: true"


def test_params_well_formed():
    for f in ONTO["functions"]:
        for name, spec in f["params"].items():
            assert spec["type"] in {"int", "float", "string", "bool", "enum"}, (f["id"], name)
            if spec["type"] == "enum":
                assert spec["values"], (f["id"], name)
            if "default" in spec and spec["type"] == "enum":
                assert spec["default"] in spec["values"], (f["id"], name)


def test_vss_paths_look_like_vss():
    for f in ONTO["functions"]:
        vss = f.get("vss")
        paths = list(vss.values()) if isinstance(vss, dict) else ([vss] if vss else [])
        for p in paths:
            assert p.startswith("Vehicle."), f"{f['id']}: {p}"


def test_build_tools_schema():
    tools = build_tools(ONTO)
    for t in tools:
        assert t["parameters"]["type"] == "object"
        assert set(t["parameters"]["required"]) <= set(t["parameters"]["properties"])


def test_initial_state_expands_instances():
    state = build_initial_state(ONTO)
    assert "Vehicle.Cabin.HVAC.Station.Row1.Driver.Temperature" in state
    assert "Vehicle.Cabin.HVAC.Station.Row2.Driver.Temperature" in state
    assert state["Vehicle.Speed"] == 0


def test_generated_is_up_to_date():
    gen = ROOT / "ontology" / "generated"
    for name, content in render(ONTO).items():
        assert (gen / name).exists(), f"run `make schema` ({name} missing)"
        assert json.loads((gen / name).read_text(encoding="utf-8")) == json.loads(content), (
            f"run `make schema` ({name} stale)"
        )
