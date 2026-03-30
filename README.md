![Protocol](https://img.shields.io/badge/Protocol-Serial-blue)
![Interface](https://img.shields.io/badge/Interface-UART%20%7C%20TTY-important)
![Type](https://img.shields.io/badge/Type-Device%20Simulator-success)
![Use Case](https://img.shields.io/badge/Use%20Case-Embedded%20Testing-yellow)
![Platform](https://img.shields.io/badge/Platform-Linux-lightgrey)
![Platform](https://img.shields.io/badge/Platform-Windows-lightgrey)
![License](https://img.shields.io/github/license/p2610/serial-slave-simulator)
![Debug](https://img.shields.io/badge/Debugging-Serial%20Sniffing-blueviolet)

# Serial Slave Simulator / Simulador de esclavos serie

Descripción (ES):
Este proyecto implementa un simulador de esclavos serie que emula sensores conectados a puertos serie y responde a comandos según una configuración JSON. Es útil para pruebas de integración, depuración de firmware y desarrollo de software que interactúe con dispositivos serie.

<img width="1372" height="614" alt="image" src="https://github.com/user-attachments/assets/8304f0c6-5791-4d1b-9fea-30ff1011e48a" />

---

## Quick Start / Inicio rápido

### Prerequisites / Requisitos
- Python 3.10+ (probado con Python 3.12).
- `pip`.

### Install / Instalación (system Python)

```bash
cd /mnt/develop/python/serial-slave-simulator
python --version
pip install -r ./requirements.txt
```

Opcional (venv incluido, se recomienda crear un entorno virtual "app" mínimo para aislar dependencias):

```bash
source app/bin/activate
# luego usar pip si necesitas instalar o actualizar dependencias
pip install -r ./requirements.txt
```

### Run / Ejecutar

Desde la raíz del repositorio:

```bash
python ./serial_simulator.py --config ./serial_simulator_config.json
```

Opciones relevantes del CLI:
- `--config PATH` : ruta al fichero JSON de configuración (por defecto usar `serial_simulator_config.json`).
- `--no-monitor` : desactivar la interfaz de monitor.
- `--log-file PATH` : registrar transacciones en PATH.
- `--refresh N` : intervalo de refresco en segundos.

Notas:
- El simulador intentará abrir los puertos serie configurados en el JSON. Si el puerto no existe o no hay permisos, el sensor entrará en estado de error; esto no debería colapsar el proceso principal.
- En sistemas Unix, puede ser necesario pertenecer al grupo `dialout` o usar `sudo` para acceder a dispositivos serie.

REPL (runtime) — comandos útiles:
- `set <sensor> <variable> <valor>` : fijar manualmente el valor de una variable.
- `get <sensor>` : mostrar variables del sensor.
- `dump` : volcar estado actual.
- `quit` : salir del REPL y detener el simulador.

---

## Configuration / Configuración

El archivo principal de configuración es `./serial_simulator_config.json`.

Campos principales:
- `simulator`: ajustes globales (p. ej. `update_interval_s`, `log_transactions`, `log_file`).
- `sensors`: lista de sensores; cada sensor tiene:
  - `name`, `port`, `baudrate`, `data_bits`, `stop_bits`, `parity`.
  - `header`, `separator`, `end_of_line`, `command`, `timeout`.
  - `mode`: `request_response` o `continuous`.
  - `variables`: lista de variables con campos `name`, `position`, `storage_address`, `value_mode` (`static`, `random`, `sine`, `ramp`, `manual`), `value`, `min`, `max`, `period_s`, `decimals`, `unit`.

Edita `./serial_simulator_config.json` para definir sensores, puertos y comportamiento.

---

## Examples / Ejemplos

- Archivo de ejemplo de configuración: `./serial_simulator_config.json`.
- Ejemplo de registro CSV generado: `./serial_sim.csv`.

Crear puertos serie virtuales para pruebas (Linux) — ejemplo con `socat`:

```bash
socat -d -d pty,link=/tmp/ttyV0,raw,echo=0 pty,link=/tmp/ttyV1,raw,echo=0
# esto crea dos dispositivos pty; conecta uno al simulador y usa el otro desde la aplicación cliente
```

---

## Development / Desarrollo

Sugerencias:
- Añadir pruebas unitarias para `./core/value_engine.py` y `./core/protocol.py`.
- Para pruebas en CI, simular puertos serie con `pty` / `socat` o usar mocks de `pyserial`.

Comandos rápidos de desarrollo:

```bash
# Instalar deps (si no están instaladas)
pip install -r ./requirements.txt
# Ejecutar el simulador (smoke test)
python ./serial_simulator.py --config ./serial_simulator_config.json
```

---

## Contributing / Contribuir

- Abre issues para bugs o peticiones de funciones.
- Envía PRs con descripciones claras y pruebas cuando sea posible.
- Indica en el PR los cambios en configuración y añade ejemplos si aplica.

---

## Maintainer / Mantenedor

- Paolo Arrunategui

---

## License / Licencia

Este proyecto se distribuye bajo la licencia MIT. Consulta el fichero `LICENSE` para el texto completo.

---

## Files of interest / Ficheros de interés

- `./serial_simulator.py` — lanzador principal y CLI.
- `./serial_simulator_config.json` — configuración por defecto.
- `./core/` — módulos internos: `sensor_server.py`, `monitor.py`, `protocol.py`, `value_engine.py`.

---
