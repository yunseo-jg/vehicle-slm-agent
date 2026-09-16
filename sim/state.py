"""차량 시뮬레이터. 실제 차량 대신 상태 dict를 들고 있다.

- 키는 VSS 경로 문자열 그대로 (예: "Vehicle.Speed")
- 초기값은 ontology/generated/initial_state.json 에서 읽는다
- precondition 검사는 여기서만 한다 (모델이 아니라 코드가 안전을 책임진다)
"""

from __future__ import annotations

import json
import re
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INITIAL_STATE = ROOT / "ontology" / "generated" / "initial_state.json"

POWER_ON_STATES = {"ON", "START"}
_SPEED_BELOW = re.compile(r"^speed_below_(\d+)$")


class PreconditionError(Exception):
    def __init__(self, code: str, message: str = ""):
        super().__init__(message or code)
        self.code = code


class VehicleState:
    def __init__(self, initial: dict | None = None):
        if initial is None:
            with INITIAL_STATE.open(encoding="utf-8") as f:
                initial = json.load(f)
        self._s: dict[str, object] = deepcopy(initial)

    # 기본 접근
    def get(self, key: str) -> object:
        if key not in self._s:
            raise KeyError(key)
        return self._s[key]

    def set(self, key: str, value: object) -> None:
        if key not in self._s:
            raise KeyError(key)
        self._s[key] = value

    def snapshot(self) -> dict[str, object]:
        return deepcopy(self._s)

    def reset(self, initial: dict | None = None) -> None:
        self.__init__(initial)

    # 자주 쓰는 판단
    @property
    def power_on(self) -> bool:
        return self._s.get("Vehicle.LowVoltageSystemState") in POWER_ON_STATES

    @property
    def speed(self) -> float:
        return float(self._s.get("Vehicle.Speed", 0))

    # precondition
    def check(self, preconditions: list[str]) -> None:
        """위반 시 PreconditionError(code). code 는 CONTRIBUTING.md 의 에러 코드 목록 중 하나."""
        for p in preconditions:
            if p == "power_on":
                if not self.power_on:
                    raise PreconditionError("engine_off", "vehicle power is off")
            elif p == "parked":
                if self.speed > 0:
                    raise PreconditionError("unsafe_while_driving", "vehicle must be parked")
            elif m := _SPEED_BELOW.match(p):
                if self.speed >= int(m.group(1)):
                    raise PreconditionError(
                        "unsafe_while_driving", f"speed must be below {m.group(1)} km/h"
                    )
            else:
                raise ValueError(f"unknown precondition: {p}")


def ok(state: VehicleState, changed: dict[str, object] | None = None) -> dict:
    return {"status": "ok", "code": None, "state_after": changed or {}}


def err(code: str, message: str = "") -> dict:
    return {"status": "error", "code": code, "message": message, "state_after": {}}
