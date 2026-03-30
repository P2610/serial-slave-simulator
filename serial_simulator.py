# CLI START
# 1) source /mnt/develop/python/serial-slave-simulator/app/bin/activate
# 2) cd /mnt/develop/python/serial-slave-simulator/serial_simulator
# 3) python serial_simulator.py --config serial_simulator_config.json
# Optional startup flags:
#   --no-monitor
#   --log-file PATH
#   --refresh N
#   --help
# Runtime commands on stdin:
#   set <sensor> <variable> <valor> | get <sensor> | dump | quit

from __future__ import annotations

import csv
import json
import shlex
import threading
from collections import deque
from pathlib import Path
from typing import Any

import click
from rich.console import Console

from core.monitor import PlainMonitor, RichMonitor
from core.sensor_server import SensorServer
from core.value_engine import VALID_VALUE_MODES


VALID_SENSOR_MODES = {"request_response", "continuous"}
VALID_PARITY = {"none", "even", "odd", "mark", "space"}


def decode_escaped_text(value: str) -> str:
    try:
        return bytes(value, "utf-8").decode("unicode_escape")
    except UnicodeDecodeError:
        return value


def escape_display(value: str) -> str:
    return value.replace("\r", "\\r").replace("\n", "\\n")


class SimulatorRuntime:
    def __init__(
        self,
        config_path: Path,
        no_monitor: bool,
        log_file_override: Path | None,
        refresh_override: float | None,
    ) -> None:
        self.console = Console()
        self.stop_event = threading.Event()

        self.config = self._load_config(config_path)
        simulator_cfg = dict(self.config.get("simulator", {}))

        interval = refresh_override if refresh_override is not None else simulator_cfg.get("update_interval_s", 1.0)
        max_rows = int(simulator_cfg.get("max_monitor_rows", 5))
        self.update_interval_s = float(interval)
        if self.update_interval_s <= 0:
            raise ValueError("update_interval_s debe ser mayor a 0")

        self.log_transactions = bool(simulator_cfg.get("log_transactions", True))
        if log_file_override is not None:
            self.log_transactions = True
            self.log_file = log_file_override
        else:
            self.log_file = Path(str(simulator_cfg.get("log_file", "serial_sim.csv")))

        self.no_monitor = no_monitor
        self.plain_monitor = PlainMonitor() if self.no_monitor else None
        self.rich_monitor: RichMonitor | None = None

        self._tx_lock = threading.RLock()
        self._csv_lock = threading.RLock()
        self._transactions: deque[dict[str, str]] = deque(maxlen=max_rows)
        self._csv_file = None
        self._csv_writer = None

        self.sensors: dict[str, SensorServer] = {}
        self._build_sensors()

    def run(self) -> None:
        self._open_csv_logger()
        self._start_sensors()
        self._start_monitor()

        self.console.print("Simulador iniciado.")
        self.console.print("Comandos: set <sensor> <variable> <valor> | get <sensor> | dump | quit")

        try:
            self._run_repl()
        except KeyboardInterrupt:
            self.console.print("Interrupcion detectada. Cerrando simulador...")
        finally:
            self.shutdown()

    def shutdown(self) -> None:
        self.stop_event.set()

        if self.rich_monitor is not None and self.rich_monitor.is_alive():
            self.rich_monitor.join(timeout=2.0)

        for sensor in self.sensors.values():
            if sensor.is_alive():
                sensor.join(timeout=2.0)

        with self._csv_lock:
            if self._csv_file is not None:
                self._csv_file.flush()
                self._csv_file.close()
                self._csv_file = None
                self._csv_writer = None

        self.console.print("Simulador detenido.")

    def _load_config(self, config_path: Path) -> dict[str, Any]:
        with config_path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)

        if not isinstance(data, dict):
            raise ValueError("El archivo de configuracion debe ser un objeto JSON")
        if "sensors" not in data:
            raise ValueError("Falta el campo 'sensors' en configuracion")
        if not isinstance(data["sensors"], list) or not data["sensors"]:
            raise ValueError("El campo 'sensors' debe contener al menos un sensor")

        return data

    def _build_sensors(self) -> None:
        for raw_sensor in self.config["sensors"]:
            sensor_cfg = self._normalize_sensor(raw_sensor)
            sensor = SensorServer(
                sensor_config=sensor_cfg,
                update_interval_s=self.update_interval_s,
                stop_event=self.stop_event,
                transaction_callback=self._record_transaction,
            )

            key = sensor.name.strip().lower()
            if key in self.sensors:
                raise ValueError(f"Nombre de sensor duplicado: {sensor.name}")
            self.sensors[key] = sensor

    def _normalize_sensor(self, raw_sensor: dict[str, Any]) -> dict[str, Any]:
        required_keys = [
            "name",
            "port",
            "baudrate",
            "data_bits",
            "stop_bits",
            "parity",
            "header",
            "separator",
            "command",
            "end_of_line",
            "timeout",
            "mode",
            "variables",
        ]
        missing = [key for key in required_keys if key not in raw_sensor]
        if missing:
            raise ValueError(f"Sensor invalido. Faltan campos: {', '.join(missing)}")

        normalized = dict(raw_sensor)
        normalized["mode"] = str(raw_sensor["mode"]).strip().lower()
        if normalized["mode"] not in VALID_SENSOR_MODES:
            raise ValueError(f"mode invalido en sensor '{raw_sensor.get('name', '')}': {normalized['mode']}")

        normalized["parity"] = str(raw_sensor["parity"]).strip().lower()
        if normalized["parity"] not in VALID_PARITY:
            raise ValueError(f"parity invalido en sensor '{raw_sensor.get('name', '')}': {normalized['parity']}")

        normalized["header"] = decode_escaped_text(str(raw_sensor["header"]))
        normalized["separator"] = decode_escaped_text(str(raw_sensor["separator"]))
        normalized["command"] = decode_escaped_text(str(raw_sensor["command"]))
        normalized["end_of_line"] = decode_escaped_text(str(raw_sensor["end_of_line"]))

        normalized["baudrate"] = int(raw_sensor["baudrate"])
        normalized["data_bits"] = int(raw_sensor["data_bits"])
        normalized["stop_bits"] = float(raw_sensor["stop_bits"])
        normalized["timeout"] = int(raw_sensor["timeout"])

        raw_variables = raw_sensor["variables"]
        if not isinstance(raw_variables, list) or not raw_variables:
            raise ValueError(f"El sensor '{raw_sensor.get('name', '')}' debe tener variables")

        seen_positions: set[int] = set()
        normalized_variables: list[dict[str, Any]] = []

        for raw_var in raw_variables:
            normalized_var = dict(raw_var)
            for key in ["name", "position", "storage_address", "value_mode", "value", "decimals"]:
                if key not in normalized_var:
                    raise ValueError(
                        f"Variable invalida en sensor '{raw_sensor.get('name', '')}'. Falta campo '{key}'"
                    )

            position = int(normalized_var["position"])
            if position < 0:
                raise ValueError(
                    f"Position negativa en variable '{normalized_var.get('name', '')}' del sensor '{raw_sensor.get('name', '')}'"
                )
            if position in seen_positions:
                raise ValueError(
                    f"Position duplicada ({position}) en sensor '{raw_sensor.get('name', '')}'"
                )
            seen_positions.add(position)
            normalized_var["position"] = position

            value_mode = str(normalized_var["value_mode"]).strip().lower()
            if value_mode not in VALID_VALUE_MODES:
                raise ValueError(
                    f"value_mode invalido en variable '{normalized_var.get('name', '')}' del sensor '{raw_sensor.get('name', '')}'"
                )
            normalized_var["value_mode"] = value_mode

            normalized_var["storage_address"] = int(normalized_var["storage_address"])
            normalized_var["value"] = float(normalized_var.get("value", 0.0))
            normalized_var["min"] = float(normalized_var.get("min", normalized_var["value"]))
            normalized_var["max"] = float(normalized_var.get("max", normalized_var["value"]))
            normalized_var["period_s"] = float(normalized_var.get("period_s", self.update_interval_s))
            normalized_var["decimals"] = int(normalized_var.get("decimals", 2))
            normalized_var["unit"] = str(normalized_var.get("unit", ""))

            normalized_variables.append(normalized_var)

        normalized["variables"] = normalized_variables
        return normalized

    def _start_sensors(self) -> None:
        for sensor in self.sensors.values():
            sensor.start()

    def _start_monitor(self) -> None:
        if self.no_monitor:
            if self.plain_monitor is not None:
                self.plain_monitor.print_startup()
            return

        self.rich_monitor = RichMonitor(
            sensor_provider=self._sensor_snapshots,
            variable_provider=self._variable_snapshots,
            transaction_provider=self._transaction_snapshots,
            refresh_interval_s=self.update_interval_s,
            stop_event=self.stop_event,
        )
        self.rich_monitor.start()

    def _run_repl(self) -> None:
        while not self.stop_event.is_set():
            raw = input("sim> ").strip()
            if not raw:
                continue

            try:
                args = shlex.split(raw)
            except ValueError as exc:
                self.console.print(f"Comando invalido: {exc}")
                continue

            command = args[0].lower()

            if command == "quit":
                self.stop_event.set()
                return

            if command == "dump":
                self._cmd_dump()
                continue

            if command == "get":
                self._cmd_get(args)
                continue

            if command == "set":
                self._cmd_set(args)
                continue

            self.console.print("Comando no soportado. Usa: set, get, dump, quit")

    def _cmd_set(self, args: list[str]) -> None:
        if len(args) != 4:
            self.console.print("Uso: set <sensor> <variable> <valor>")
            return

        sensor_name = args[1].strip().lower()
        variable_name = args[2]
        try:
            new_value = float(args[3])
        except ValueError:
            self.console.print("Valor invalido. Debe ser numerico")
            return

        sensor = self.sensors.get(sensor_name)
        if sensor is None:
            self.console.print(f"Sensor no encontrado: {args[1]}")
            return

        if sensor.set_manual_value(variable_name, new_value):
            self.console.print(
                f"OK: {args[1]}.{variable_name} actualizado a {new_value} en modo manual"
            )
            return

        self.console.print(f"Variable no encontrada: {variable_name}")

    def _cmd_get(self, args: list[str]) -> None:
        if len(args) != 2:
            self.console.print("Uso: get <sensor>")
            return

        sensor_name = args[1].strip().lower()
        sensor = self.sensors.get(sensor_name)
        if sensor is None:
            self.console.print(f"Sensor no encontrado: {args[1]}")
            return

        message = sensor.get_last_message()
        if not message:
            self.console.print(f"{args[1]} aun no envio mensajes")
            return

        self.console.print(f"{args[1]} -> {escape_display(message)}")

    def _cmd_dump(self) -> None:
        for sensor_key in sorted(self.sensors.keys()):
            sensor = self.sensors[sensor_key]
            values = sensor.dump_values()
            values_text = ", ".join(f"{name}={value}" for name, value in values.items())
            self.console.print(f"{sensor.name}: {values_text}")

    def _record_transaction(self, transaction: dict[str, str]) -> None:
        with self._tx_lock:
            self._transactions.append(transaction)

        if self.no_monitor and self.plain_monitor is not None:
            self.plain_monitor.print_transaction(transaction)

        if not self.log_transactions:
            return

        with self._csv_lock:
            if self._csv_writer is None or self._csv_file is None:
                return
            self._csv_writer.writerow(
                {
                    "timestamp": transaction.get("timestamp", ""),
                    "sensor": transaction.get("sensor", ""),
                    "command": transaction.get("command", ""),
                    "response": transaction.get("response", ""),
                }
            )
            self._csv_file.flush()

    def _transaction_snapshots(self) -> list[dict[str, str]]:
        with self._tx_lock:
            return list(self._transactions)

    def _sensor_snapshots(self) -> list[dict[str, Any]]:
        rows = [sensor.get_sensor_snapshot() for sensor in self.sensors.values()]
        rows.sort(key=lambda row: str(row.get("sensor", "")).lower())
        return rows

    def _variable_snapshots(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for sensor in self.sensors.values():
            rows.extend(sensor.get_variable_snapshots())
        rows.sort(key=lambda row: (str(row.get("sensor", "")).lower(), int(row.get("position", 0))))
        return rows

    def _open_csv_logger(self) -> None:
        if not self.log_transactions:
            return

        log_path = self.log_file
        if log_path.parent and str(log_path.parent) not in {"", "."}:
            log_path.parent.mkdir(parents=True, exist_ok=True)

        file_exists = log_path.exists()
        self._csv_file = log_path.open("a", newline="", encoding="utf-8")
        self._csv_writer = csv.DictWriter(
            self._csv_file,
            fieldnames=["timestamp", "sensor", "command", "response"],
        )

        if not file_exists or log_path.stat().st_size == 0:
            self._csv_writer.writeheader()
            self._csv_file.flush()


@click.command()
@click.option(
    "--config",
    "config_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    required=True,
    help="Ruta al JSON de configuracion.",
)
@click.option("--no-monitor", is_flag=True, help="Deshabilita monitor Rich y usa log plano")
@click.option(
    "--log-file",
    "log_file",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="Sobrescribe ruta de CSV de transacciones.",
)
@click.option(
    "--refresh",
    "refresh_seconds",
    type=float,
    default=None,
    help="Sobrescribe simulator.update_interval_s",
)
def main(config_path: Path, no_monitor: bool, log_file: Path | None, refresh_seconds: float | None) -> None:
    try:
        runtime = SimulatorRuntime(
            config_path=config_path,
            no_monitor=no_monitor,
            log_file_override=log_file,
            refresh_override=refresh_seconds,
        )
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc

    runtime.run()


if __name__ == "__main__":
    main()
