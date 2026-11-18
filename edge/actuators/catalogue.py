"""The actuator table of `actuators.yaml` and the routing of `act/` topics to actuators.

    python -m edge.actuators.catalogue           write the OPA data file
    python -m edge.actuators.catalogue --check   exit 1 when the data file is out of date
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

import yaml

from atra.config import ROOT
from atra.contracts import AutonomyLevel

HERE = Path(__file__).resolve().parent
TABLE = HERE / "actuators.yaml"
POLICY_DATA = ROOT / "policies" / "opa" / "ahdt" / "actuators" / "data.json"
POLICY_KEYS = ("action_classes", "approvers", "actuators")
ACT_TOPIC = "act/+/+/+"
FIXED_TARGETS = frozenset({"phone", "channels", "carer", "home"})


class UnknownActuator(LookupError):
    pass


@dataclass(frozen=True)
class Actuator:
    name: str
    text: str
    topic: str
    action_class: str
    level: AutonomyLevel
    device_classes: tuple[str, ...]
    approvers: tuple[str, ...]

    def topic_for(self, hdt_id: str, device_id: str | None = None) -> str:
        return self.topic.format(hdt_id=hdt_id, device_id=device_id or "")


@cache
def table() -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load(TABLE.read_text(encoding="utf-8"))
    return data


@cache
def actuators() -> dict[str, Actuator]:
    t = table()
    out = {}
    for name, a in t["actuators"].items():
        out[name] = Actuator(
            name=name, text=a["text"], topic=a["topic"], action_class=a["class"],
            level=AutonomyLevel(t["action_classes"][a["class"]]["level"]),
            device_classes=tuple(a.get("device_classes", ())),
            approvers=tuple(a.get("approvers", t["approvers"])))
    return out


def resolve(topic: str, device_class_of: Callable[[str], str | None]
            ) -> tuple[Actuator, str | None]:
    """The actuator and device of an `act/{hdt_id}/{target}/{kind}` topic.

    `phone/notify`, `channels/{sms,ussd,voice}` and `carer/message` name the actuator;
    `home/{device_id}` and `{device_id}/{haptic,therapy}` resolve through the device's class.
    """
    parts = topic.split("/")
    if len(parts) != 4 or parts[0] != "act":
        raise UnknownActuator(f"{topic} is not an act/{{hdt_id}}/{{target}}/{{kind}} topic")
    _, hdt_id, target, kind = parts
    for a in actuators().values():
        if not a.device_classes and a.topic_for(hdt_id) == topic:
            return a, None
    device_id = kind if target == "home" else target
    if target != "home" and target in FIXED_TARGETS:
        raise UnknownActuator(f"no actuator at {topic}")
    device_class = device_class_of(device_id)
    for a in actuators().values():
        if device_class in a.device_classes and a.topic_for(hdt_id, device_id) == topic:
            return a, device_id
    raise UnknownActuator(f"device {device_id} ({device_class}) has no actuator at {topic}")


def policy_data() -> dict[str, Any]:
    """OPA reads the file at `data.ahdt.actuators`, the path of its directory."""
    t = table()
    return {k: t[k] for k in POLICY_KEYS}


def policy_data_json(data: Mapping[str, Any] | None = None) -> str:
    return json.dumps(data or policy_data(), indent=2, sort_keys=True) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m edge.actuators.catalogue")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    text = policy_data_json()
    if args.check:
        current = POLICY_DATA.read_text(encoding="utf-8") if POLICY_DATA.exists() else ""
        if current != text:
            print(f"{POLICY_DATA} is out of date")
            return 1
        return 0
    POLICY_DATA.parent.mkdir(parents=True, exist_ok=True)
    POLICY_DATA.write_text(text, encoding="utf-8")
    print(f"wrote {POLICY_DATA}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
