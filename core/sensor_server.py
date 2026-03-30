from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable

import serial

from core.protocol import SensorProtocol
from core.value_engine import ValueEngine


TransactionCallback = Callable[[dict[str, str]], None]


def _escape_text(value: str) -> str:
    return value.replace("\r", "\\r").replace("\n", "\\n")


def _map_parity(parity: str) -> str:
    normalized = parity.strip().lower()
    mapping = {
        "none": serial.PARITY_NONE,
        "even": serial.PARITY_EVEN,
        "odd": serial.PARITY_ODD,
        "mark": serial.PARITY_MARK,
        "space": serial.PARITY_SPACE,
    }
    if normalized not in mapping:
        raise ValueError(f"Paridad no soportada: {parity}")
    return mapping[normalized]


def _map_bytesize(data_bits: int) -> int:
    mapping = {
        5: serial.FIVEBITS,
        6: serial.SIXBITS,
        7: serial.SEVENBITS,
        8: serial.EIGHTBITS,
    }
    if data_bits not in mapping:
        raise ValueError(f"data_bits no soportado: {data_bits}")
    return mapping[data_bits]


def _map_stopbits(stop_bits: float) -> float:
    mapping = {
        1: serial.STOPBITS_ONE,
        1.0: serial.STOPBITS_ONE,
        1.5: serial.STOPBITS_ONE_POINT_FIVE,
        2: serial.STOPBITS_TWO,
        2.0: serial.STOPBITS_TWO,
    }
    if stop_bits not in mapping:
        raise ValueError(f"stop_bits no soportado: {stop_bits}")
    return mapping[stop_bits]


class SensorServer(threading.Thread):
    def __init__(
        self,
        sensor_config: dict[str, Any],
        update_interval_s: float,
        stop_event: threading.Event,
        transaction_callback: TransactionCallback | None = None,
    ) -> None:
        name = str(sensor_config.get("name", "Sensor"))
        super().__init__(name=f"SensorServer-{name}", daemon=True)

        self.name = name
        self.port = str(sensor_config.get("port", ""))
        self.baudrate = int(sensor_config.get("baudrate", 9600))
        self.data_bits = int(sensor_config.get("data_bits", 8))
        self.stop_bits = float(sensor_config.get("stop_bits", 1))
        self.parity = str(sensor_config.get("parity", "none"))
        self.timeout_ms = int(sensor_config.get("timeout", 200))

        mode = str(sensor_config.get("mode", "request_response")).strip().lower()
        if mode not in {"request_response", "continuous"}:
            raise ValueError(f"Modo no soportado en sensor '{self.name}': {mode}")
        self.mode = mode

        self.protocol = SensorProtocol(
            header=str(sensor_config.get("header", "")),
            separator=str(sensor_config.get("separator", ";")),
            command=str(sensor_config.get("command", "")),
            end_of_line=str(sensor_config.get("end_of_line", "\n")),
        )

        self.value_engine = ValueEngine(list(sensor_config.get("variables", [])))
        self.update_interval_s = float(update_interval_s)
        if self.update_interval_s <= 0:
            raise ValueError("update_interval_s debe ser mayor a 0")

        self.stop_event = stop_event
        self.transaction_callback = transaction_callback

        self._lock = threading.RLock()
        self._serial: serial.Serial | None = None
        self._started_at = 0.0
        self._rx_buffer = ""

        self.last_message = ""
        self.last_command = ""
        self.last_status = "INIT"

    def run(self) -> None:
        try:
            self._open_serial()
        except Exception as exc:
            self.last_status = f"ERROR_OPEN: {exc}"
            self._record_transaction("", "", self.last_status)
            return

        self._started_at = time.monotonic()
        next_tick = self._started_at
        next_continuous_tx = self._started_at

        try:
            while not self.stop_event.is_set():
                now = time.monotonic()

                if now >= next_tick:
                    self._update_values(now)
                    next_tick = now + self.update_interval_s

                if self.mode == "continuous":
                    if now >= next_continuous_tx:
                        self._send_response(command_received="")
                        next_continuous_tx = now + self.update_interval_s
                    self.stop_event.wait(0.01)
                    continue

                self._read_and_handle_requests()
        finally:
            self._close_serial()

    def set_manual_value(self, variable_name: str, value: float) -> bool:
        with self._lock:
            return self.value_engine.set_manual(variable_name, value)

    def get_last_message(self) -> str:
        with self._lock:
            return self.last_message

    def get_sensor_snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "sensor": self.name,
                "port": self.port,
                "mode": self.mode,
                "command": _escape_text(self.protocol.command),
                "variables": len(self.value_engine.variables),
                "last_message": _escape_text(self.last_message),
                "status": self.last_status,
            }

    def get_variable_snapshots(self) -> list[dict[str, Any]]:
        with self._lock:
            snapshots: list[dict[str, Any]] = []
            for variable in self.value_engine.variables:
                snapshots.append(
                    {
                        "sensor": self.name,
                        "variable": variable.name,
                        "position": variable.position,
                        "storage_address": variable.storage_address,
                        "value_mode": variable.value_mode,
                        "current_value": variable.current_value,
                        "decimals": variable.decimals,
                        "unit": variable.unit,
                    }
                )
            return snapshots

    def dump_values(self) -> dict[str, float]:
        with self._lock:
            return {variable.name: variable.current_value for variable in self.value_engine.variables}

    def _open_serial(self) -> None:
        timeout_s = max(self.timeout_ms / 1000.0, 0.01)
        self._serial = serial.Serial(
            port=self.port,
            baudrate=self.baudrate,
            bytesize=_map_bytesize(self.data_bits),
            parity=_map_parity(self.parity),
            stopbits=_map_stopbits(self.stop_bits),
            timeout=timeout_s,
            write_timeout=timeout_s,
        )
        self.last_status = "READY"

    def _close_serial(self) -> None:
        if self._serial is None:
            return
        try:
            if self._serial.is_open:
                self._serial.close()
        finally:
            self._serial = None

    def _update_values(self, now_monotonic: float) -> None:
        elapsed = max(0.0, now_monotonic - self._started_at)
        with self._lock:
            self.value_engine.update_all(elapsed)

    def _read_and_handle_requests(self) -> None:
        if self._serial is None:
            return

        pending = self._serial.in_waiting
        if pending <= 0:
            chunk = self._serial.read(1)
        else:
            chunk = self._serial.read(pending)

        if not chunk:
            return

        self._rx_buffer += chunk.decode("utf-8", errors="ignore")

        while "\n" in self._rx_buffer:
            separator_index = self._rx_buffer.find("\n")
            command = self._rx_buffer[: separator_index + 1]
            self._rx_buffer = self._rx_buffer[separator_index + 1 :]
            self._handle_command(command)

    def _handle_command(self, command: str) -> None:
        with self._lock:
            self.last_command = command

        if self.protocol.matches_command(command):
            self._send_response(command_received=command)
            return

        with self._lock:
            self.last_status = "IGNORED_COMMAND"
        self._record_transaction(command, "", "IGNORED_COMMAND")

    def _send_response(self, command_received: str) -> None:
        if self._serial is None:
            return

        with self._lock:
            message = self.protocol.build_message(self.value_engine.variables)
            encoded = message.encode("utf-8")
            self._serial.write(encoded)
            self._serial.flush()

            self.last_message = message
            self.last_status = "SENT"

        self._record_transaction(command_received, message, "SENT")

    def _record_transaction(self, command: str, response: str, status: str) -> None:
        if self.transaction_callback is None:
            return
        timestamp = datetime.now(timezone.utc).isoformat()
        self.transaction_callback(
            {
                "timestamp": timestamp,
                "sensor": self.name,
                "command": _escape_text(command),
                "response": _escape_text(response),
                "status": status,
            }
        )
