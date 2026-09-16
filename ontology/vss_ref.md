# VSS 6.0 참고

경로를 넣기 전에 여기서 확인한다. 없는 경로를 AI가 그럴듯하게 만들어내는 일이 잦다.

## 파일 받기

https://github.com/COVESA/vehicle_signal_specification/releases/tag/v6.0 의 Assets에서
`vss.json`(코드용), `vss.csv`(엑셀로 훑기용)를 받아 `data/raw/`에 둔다. 커밋하지 않는다.

## 검색

```python
import json

d = json.load(open("data/raw/vss.json"))


def walk(node, path, out):
    if "children" in node:
        for k, c in node["children"].items():
            walk(c, f"{path}.{k}", out)
    else:
        out.append((path, node))


out = []
walk(d["Vehicle"], "Vehicle", out)
for p, n in out:
    if "HVAC" in p:
        print(p, n["type"], n.get("datatype"), n.get("unit"), n.get("allowed"))
```

## 타입 → 도구 대응

- `actuator` (읽고 쓰기) → set 도구
- `sensor` (읽기만) → get 도구
- `attribute` (거의 안 바뀜) → 초기 상태 또는 get 도구

## 우리가 쓰는 경로 (6.0 확인됨)

공조
- `Vehicle.Cabin.HVAC.Station.{Row1|Row2}.{Driver|Passenger}.Temperature` actuator float Celsius
- `...Station.*.FanSpeed` actuator uint8 0-100 percent
- `...Station.*.AirDistribution` allowed UP / MIDDLE / DOWN
- `Vehicle.Cabin.HVAC.IsAirConditioningActive`, `IsFrontDefrosterActive`, `IsRearDefrosterActive`, `IsRecirculationActive` boolean
- `Vehicle.Cabin.Seat.Row1.DriverSide.HeatingCooling` int8 -100~100 (음수 통풍, 양수 열선)

미디어
- `Vehicle.Cabin.Infotainment.Media.Action` allowed STOP / PLAY / FAST_FORWARD / FAST_BACKWARD / SKIP_FORWARD / SKIP_BACKWARD
- `...Media.Volume` uint8 0-100
- `...Media.Played.Source` allowed AM / FM / USB / BLUETOOTH / INTERNET 등
- `...Media.Played.Artist`, `.Track` sensor

내비 (표준은 좌표만. 장소명 검색은 확장 기능)
- `Vehicle.Cabin.Infotainment.Navigation.DestinationSet.Latitude / Longitude` actuator
- `...Navigation.Mute` allowed MUTED / ALERT_ONLY / UNMUTED
- `...Navigation.Volume` uint8 0-100
- `Vehicle.CurrentLocation.Latitude / Longitude` sensor

설정
- `Vehicle.Cabin.Door.{Row1|Row2}.{DriverSide|PassengerSide}.Window.Position` uint8 0-100
- `...Window.Switch` allowed INACTIVE / CLOSE / OPEN / ONE_SHOT_CLOSE / ONE_SHOT_OPEN
- `...IsLocked` boolean
- `Vehicle.Cabin.Sunroof.Switch` allowed OPEN / CLOSE / TILT_UP / TILT_DOWN 등

상태 (전부 sensor)
- `Vehicle.Speed` km/h, `Vehicle.IsMoving` boolean
- `Vehicle.LowVoltageSystemState` allowed OFF / ACC / ON / START (시동 여부)
- `Vehicle.Powertrain.FuelSystem.RelativeLevel` percent, `IsFuelLevelLow` boolean
- `Vehicle.Powertrain.TractionBattery.StateOfCharge.Displayed` percent
- `Vehicle.Powertrain.Range` m (km 아님)
- `Vehicle.Chassis.Axle.Row1.Wheel.Left.Tire.Pressure` kPa, `Tire.IsPressureLow` boolean
- `Vehicle.Diagnostics.DTCCount`, `DTCList`
- `Vehicle.Powertrain.Type` attribute COMBUSTION / HYBRID / ELECTRIC

주의: 공조는 `Driver/Passenger`, 문·좌석은 `DriverSide/PassengerSide`. 단위 `Celsius` 대문자.
