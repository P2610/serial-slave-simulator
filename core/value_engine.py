from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Any


VALID_VALUE_MODES = {"static", "random", "sine", "ramp", "manual"}


@dataclass
class VariableState:
    name: str
    position: int
    storage_address: int
    value_mode: str
    value: float
    min_value: float
    max_value: float
    period_s: float
    decimals: int
    unit: str
    current_value: float

    @classmethod
    def from_config(cls, raw: dict[str, Any]) -> "VariableState":
        value_mode = str(raw.get("value_mode", "static")).strip().lower()
        if value_mode not in VALID_VALUE_MODES:
            raise ValueError(f"value_mode invalido para variable '{raw.get('name', '<sin nombre>')}': {value_mode}")

        value = float(raw.get("value", 0.0))
        min_value = float(raw.get("min", value))
        max_value = float(raw.get("max", value))
        period_s = float(raw.get("period_s", 1.0))

        if min_value > max_value:
            raise ValueError(f"Rango invalido en variable '{raw.get('name', '<sin nombre>')}': min > max")

        decimals = int(raw.get("decimals", 2))
        if decimals < 0:
            raise ValueError(f"decimals invalido en variable '{raw.get('name', '<sin nombre>')}': {decimals}")

        return cls(
            name=str(raw.get("name", "")),
            position=int(raw.get("position", 0)),
            storage_address=int(raw.get("storage_address", 0)),
            value_mode=value_mode,
            value=value,
            min_value=min_value,
            max_value=max_value,
            period_s=period_s,
            decimals=decimals,
            unit=str(raw.get("unit", "")),
            current_value=value,
        )

    def update(self, elapsed_s: float) -> None:
        mode = self.value_mode

        if mode == "static" or mode == "manual":
            self.current_value = self.value
            return

        if mode == "random":
            self.current_value = random.uniform(self.min_value, self.max_value)
            return

        if mode == "sine":
            if self.period_s <= 0:
                self.current_value = self.value
                return
            mid = (self.max_value + self.min_value) / 2.0
            amplitude = (self.max_value - self.min_value) / 2.0
            angle = (2.0 * math.pi * elapsed_s) / self.period_s
            self.current_value = mid + amplitude * math.sin(angle)
            return

        if mode == "ramp":
            if self.period_s <= 0:
                self.current_value = self.value
                return
            span = self.max_value - self.min_value
            if span == 0:
                self.current_value = self.min_value
                return
            progress = (elapsed_s % self.period_s) / self.period_s
            self.current_value = self.min_value + (span * progress)
            return

        raise ValueError(f"Modo de valor no soportado: {mode}")

    def set_manual(self, new_value: float) -> None:
        self.value_mode = "manual"
        self.value = float(new_value)
        self.current_value = self.value


class ValueEngine:
    def __init__(self, raw_variables: list[dict[str, Any]]) -> None:
        self.variables = [VariableState.from_config(raw_var) for raw_var in raw_variables]

    def update_all(self, elapsed_s: float) -> None:
        for variable in self.variables:
            variable.update(elapsed_s)

    def set_manual(self, variable_name: str, new_value: float) -> bool:
        target = variable_name.strip().lower()
        for variable in self.variables:
            if variable.name.strip().lower() == target:
                variable.set_manual(new_value)
                return True
        return False

    def get_variable(self, variable_name: str) -> VariableState | None:
        target = variable_name.strip().lower()
        for variable in self.variables:
            if variable.name.strip().lower() == target:
                return variable
        return None
