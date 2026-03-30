from __future__ import annotations

import threading
from typing import Any, Callable

from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table


SnapshotProvider = Callable[[], list[dict[str, Any]]]


def _format_float(value: Any, decimals: int) -> str:
    try:
        return f"{float(value):.{int(decimals)}f}"
    except (TypeError, ValueError):
        return str(value)


class RichMonitor(threading.Thread):
    def __init__(
        self,
        sensor_provider: SnapshotProvider,
        variable_provider: SnapshotProvider,
        transaction_provider: SnapshotProvider,
        refresh_interval_s: float,
        stop_event: threading.Event,
    ) -> None:
        super().__init__(name="RichMonitor", daemon=True)
        self.sensor_provider = sensor_provider
        self.variable_provider = variable_provider
        self.transaction_provider = transaction_provider
        self.refresh_interval_s = max(0.1, float(refresh_interval_s))
        self.stop_event = stop_event
        self.console = Console()

    def run(self) -> None:
        with Live(self._build_group(), console=self.console, refresh_per_second=10, transient=False) as live:
            while not self.stop_event.wait(self.refresh_interval_s):
                live.update(self._build_group(), refresh=True)

    def _build_group(self) -> Group:
        sensors_panel = Panel(self._build_sensors_table(), title="Sensores Activos")
        variables_panel = Panel(self._build_variables_table(), title="Variables")
        transactions_panel = Panel(self._build_transactions_table(), title="Transacciones")
        return Group(sensors_panel, variables_panel, transactions_panel)

    def _build_sensors_table(self) -> Table:
        table = Table(expand=True)
        table.add_column("sensor")
        table.add_column("port")
        table.add_column("mode")
        table.add_column("command")
        table.add_column("variables", justify="right")
        table.add_column("ultimo mensaje enviado")

        for row in self.sensor_provider():
            table.add_row(
                str(row.get("sensor", "")),
                str(row.get("port", "")),
                str(row.get("mode", "")),
                str(row.get("command", "")),
                str(row.get("variables", "")),
                str(row.get("last_message", "")),
            )

        return table

    def _build_variables_table(self) -> Table:
        table = Table(expand=True)
        table.add_column("sensor")
        table.add_column("variable")
        table.add_column("position", justify="right")
        table.add_column("storage_addr", justify="right")
        table.add_column("value_mode")
        table.add_column("valor actual", justify="right")
        table.add_column("decimals", justify="right")
        table.add_column("unit")

        for row in self.variable_provider():
            decimals = int(row.get("decimals", 2))
            value_text = _format_float(row.get("current_value", 0.0), decimals)
            table.add_row(
                str(row.get("sensor", "")),
                str(row.get("variable", "")),
                str(row.get("position", "")),
                str(row.get("storage_address", "")),
                str(row.get("value_mode", "")),
                value_text,
                str(decimals),
                str(row.get("unit", "")),
            )

        return table

    def _build_transactions_table(self) -> Table:
        table = Table(expand=True)
        table.add_column("timestamp")
        table.add_column("sensor")
        table.add_column("comando recibido")
        table.add_column("respuesta enviada")
        table.add_column("status")

        for row in self.transaction_provider():
            table.add_row(
                str(row.get("timestamp", "")),
                str(row.get("sensor", "")),
                str(row.get("command", "")),
                str(row.get("response", "")),
                str(row.get("status", "")),
            )

        return table


class PlainMonitor:
    def __init__(self) -> None:
        self.console = Console()

    def print_startup(self) -> None:
        self.console.print("[plain] monitor deshabilitado (--no-monitor)")

    def print_transaction(self, tx: dict[str, Any]) -> None:
        self.console.print(
            "[tx] {timestamp} sensor={sensor} cmd={command} resp={response} status={status}".format(
                timestamp=tx.get("timestamp", ""),
                sensor=tx.get("sensor", ""),
                command=tx.get("command", ""),
                response=tx.get("response", ""),
                status=tx.get("status", ""),
            )
        )
