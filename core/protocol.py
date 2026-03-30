from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from core.value_engine import VariableState


FILLER_VALUE = "-9999"


@dataclass
class SensorProtocol:
    header: str
    separator: str
    command: str
    end_of_line: str

    def matches_command(self, received: str) -> bool:
        return received == self.command

    def build_message(self, variables: Iterable[VariableState]) -> str:
        sorted_vars = sorted(variables, key=lambda var: var.position)

        if not sorted_vars:
            return f"{self.header}{self.end_of_line}"

        max_position = sorted_vars[-1].position
        if max_position < 0:
            raise ValueError("Las posiciones no pueden ser negativas")

        slots = [FILLER_VALUE for _ in range(max_position + 1)]
        seen_positions: set[int] = set()

        for variable in sorted_vars:
            if variable.position < 0:
                raise ValueError(f"Posicion negativa en variable '{variable.name}'")
            if variable.position in seen_positions:
                raise ValueError(f"Posicion duplicada detectada: {variable.position}")
            seen_positions.add(variable.position)

            slots[variable.position] = format_value(variable.current_value, variable.decimals)

        body = self.separator.join(slots)
        return f"{self.header}{body}{self.end_of_line}"


def format_value(value: float, decimals: int) -> str:
    return f"{float(value):.{int(decimals)}f}"
