import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sim.state import PreconditionError, VehicleState  # noqa: E402


def make(**overrides):
    s = VehicleState()
    for k, v in overrides.items():
        s.set(k, v)
    return s


def test_power_on_check():
    s = make(**{"Vehicle.LowVoltageSystemState": "OFF"})
    with pytest.raises(PreconditionError) as e:
        s.check(["power_on"])
    assert e.value.code == "engine_off"


def test_speed_below():
    s = make(**{"Vehicle.Speed": 80})
    with pytest.raises(PreconditionError) as e:
        s.check(["speed_below_60"])
    assert e.value.code == "unsafe_while_driving"
    make(**{"Vehicle.Speed": 30}).check(["speed_below_60"])


def test_unknown_key_rejected():
    with pytest.raises(KeyError):
        VehicleState().set("Vehicle.Made.Up.Signal", 1)
