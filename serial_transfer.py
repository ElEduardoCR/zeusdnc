"""Transmision manual de un archivo por el puerto serial detectado.

Es una transferencia completa a la memoria de la maquina ("punch"), no un
drip-feed sincronizado con el ciclo de maquinado: se abre el puerto, se
manda el archivo completo respetando el control de flujo del perfil, y se
cierra.
"""
import hashlib
import json
import logging
import threading
import time
import uuid

import serial

from state import state
from zeuz_core.operation_guard import OperationLease, Busy
from zeuz_core.serial_diagnostics import read_open_port, unavailable

BYTESIZE_MAP = {
    5: serial.FIVEBITS,
    6: serial.SIXBITS,
    7: serial.SEVENBITS,
    8: serial.EIGHTBITS,
}
PARITY_MAP = {
    "N": serial.PARITY_NONE,
    "E": serial.PARITY_EVEN,
    "O": serial.PARITY_ODD,
    "M": serial.PARITY_MARK,
    "S": serial.PARITY_SPACE,
}
STOPBITS_MAP = {
    1: serial.STOPBITS_ONE,
    2: serial.STOPBITS_TWO,
}
TERMINATOR_MAP = {
    "CR": "\r",
    "CRLF": "\r\n",
    "LF": "\n",
}

CHUNK_SIZE = 256
# Match the direct iPhone transport: a CNC may hold XOFF for more than 30 s
# while preparing to receive. Drip-feed still has no write timeout.
PUNCH_TIMEOUT_SECONDS = 120
_logger = logging.getLogger("zeuz.serial")

_transfer_lock = threading.Lock()

# Para cancelar un envio en curso sin apagar ni forzar un error.
_cancel_event = threading.Event()
_ser_lock = threading.Lock()
_current_ser = None
_serial_observation = {"phase": "idle", "transfer_id": None}
_baseline_serial_snapshot = None
_last_serial_snapshot = None


def _observe(**fields):
    global _serial_observation
    with _ser_lock:
        _serial_observation = {**_serial_observation, **fields}


def _begin_observation(transfer_id, started):
    global _serial_observation, _baseline_serial_snapshot, _last_serial_snapshot
    with _ser_lock:
        _baseline_serial_snapshot = _last_serial_snapshot = None
        _serial_observation = dict(phase="prepare", transfer_id=transfer_id,
            bytes_queued=0, total_bytes=0, started_monotonic=started,
            last_progress_monotonic=started, write_started_monotonic=None,
            failure_phase=None, error_type=None, error_detected_monotonic=None,
            close_started_monotonic=None, close_completed_monotonic=None,
            finished_monotonic=None, outcome=None)


def _capture_serial(ser):
    try:
        return read_open_port(ser)
    except Exception:
        return unavailable("observation_failed")


def get_serial_diagnostics():
    """Observe the existing descriptor under its retirement lock, never reopen it."""
    global _last_serial_snapshot
    if not _ser_lock.acquire(timeout=0.02):
        return {**_serial_observation, "port_open": None, "observation": unavailable("busy")}
    try:
        current = _current_ser
        observation = _capture_serial(current) if current is not None else unavailable("port_closed")
        if current is not None:
            _last_serial_snapshot = observation
        result = {**_serial_observation, "port_open": current is not None,
                  "observation": observation, "baseline": _baseline_serial_snapshot,
                  "last_observation": _last_serial_snapshot}
    finally:
        _ser_lock.release()
    now = time.monotonic()
    result["observed_monotonic"] = now
    for target, origin in (("elapsed_seconds", "started_monotonic"),
                           ("seconds_since_progress", "last_progress_monotonic")):
        started = result.get(origin)
        end = result.get("finished_monotonic") if target == "elapsed_seconds" else None
        result[target] = round(max(0.0, (now if end is None else end) - started), 3) if started is not None else None
    return result


def _capture_baseline(ser):
    global _baseline_serial_snapshot, _last_serial_snapshot
    with _ser_lock:
        _baseline_serial_snapshot = _capture_serial(ser)
        _last_serial_snapshot = _baseline_serial_snapshot


def _retire_serial(ser, phase, error):
    """Finish observations before __exit__ closes (and may reuse) the fd."""
    global _current_ser, _serial_observation, _last_serial_snapshot
    with _ser_lock:
        now = time.monotonic()
        _last_serial_snapshot = _capture_serial(ser)
        _serial_observation = {**_serial_observation, "phase": "closing",
            "failure_phase": phase if error is not None else None,
            "error_type": type(error).__name__[:64] if error is not None else None,
            "error_detected_monotonic": now if error is not None else None,
            "close_started_monotonic": now}
        _current_ser = None
        report = {**_serial_observation, "snapshot": _last_serial_snapshot}
    # Closing can itself block. Persist the timeout and final passive sample first.
    # Logging and serial.close never hold the lock used by cancellation.
    try:
        log = _logger.error if error is not None and not isinstance(error, _Cancelled) else _logger.info
        log("serial_transfer closing %s", json.dumps(report, separators=(",", ":"), sort_keys=True))
    except Exception:
        pass


class _Cancelled(Exception):
    pass


def request_cancel():
    """Solicita abortar la transferencia en curso (si la hay). Ademas de
    marcar el flag, interrumpe una escritura bloqueada (p.ej. la maquina
    dejo de aceptar datos) con cancel_write()."""
    _cancel_event.set()
    with _ser_lock:
        ser = _current_ser
    if ser is not None:
        try:
            ser.cancel_write()
        except Exception:  # noqa: BLE001 - best effort
            pass


def _prepare_payload(filepath, terminator):
    with open(filepath, "rb") as f:
        raw = f.read()
    # latin-1 mapea 1 a 1 cada byte: evita errores de decodificacion en
    # archivos de texto plano (G-code/ISO) sin alterar el contenido.
    text = raw.decode("latin-1")
    lines = text.splitlines()
    body = terminator.join(lines)
    if lines:
        body += terminator
    return body.encode("latin-1")


def start_transfer(device_path, machine_profile, filepath, display_name):
    """Lanza la transferencia en un hilo aparte. No bloquea al llamador.

    filepath es la ruta absoluta ya validada dentro de la carpeta
    compartida; display_name es el nombre a mostrar en la interfaz.
    """
    if not _transfer_lock.acquire(blocking=False):
        return False, "Ya hay una transferencia en curso"

    try:
        lease = OperationLease()
    except (Busy, OSError) as exc:
        _transfer_lock.release()
        return False, str(exc)
    _cancel_event.clear()
    # Solo quien ya tiene el puerto reemplaza el estado visible. Un segundo
    # "Enviar" rechazado ya no borra el progreso del envío en curso, y los
    # clientes ven "sending" desde la respuesta, no un "idle" o el resultado
    # del envío anterior mientras se prepara el archivo.
    state.reset_transfer()
    state.update_transfer(status="sending", filename=display_name,
                          machine=machine_profile.get("name", machine_profile.get("id")),
                          message="Preparando el envío…")
    def guarded_transfer():
        try:
            _run_transfer(device_path, machine_profile, filepath, display_name)
        finally:
            lease.close()
    thread = threading.Thread(target=guarded_transfer, daemon=True)
    try:
        thread.start()
    except Exception:
        lease.close()
        _transfer_lock.release()
        state.update_transfer(status="error", message="No se pudo iniciar el envío")
        raise
    return True, None


def _run_transfer(device_path, profile, filepath, display_name):
    global _current_ser
    machine_name = profile.get("name", profile.get("id"))
    phase = "prepare"
    sent = 0
    total = 0
    started_at = time.monotonic()
    failure = None
    outcome = "error"
    transfer_id = uuid.uuid4().hex
    _begin_observation(transfer_id, started_at)
    prepared_sha256 = None
    settings = {key: profile.get(key) for key in (
        "baudrate", "bytesize", "parity", "stopbits", "flow_control",
        "line_terminator", "dtr", "rts", "dripfeed")}
    settings.update(flow_control=profile.get("flow_control", "xonxoff"),
                    dtr=bool(profile.get("dtr", False)), rts=bool(profile.get("rts", False)),
                    dripfeed=bool(profile.get("dripfeed", False)))
    try:
        _logger.info("serial_transfer started transfer_id=%s port=%r settings=%r",
                     transfer_id, device_path, settings)
        terminator = TERMINATOR_MAP[profile["line_terminator"]]
        payload = _prepare_payload(filepath, terminator)
        total = len(payload)
        _observe(total_bytes=total)
        prepared_sha256 = hashlib.sha256(payload).hexdigest()

        dripfeed = bool(profile.get("dripfeed", False))
        state.update_transfer(
            status="sending",
            filename=display_name,
            machine=machine_name,
            bytes_sent=0,
            total_bytes=total,
            percent=0,
            message="Goteo (drip-feed) en curso…" if dripfeed else "",
        )

        flow = profile.get("flow_control", "xonxoff")
        # Modo drip-feed (goteo): la maquina ejecuta mientras recibe y frena el
        # envio con el control de flujo por minutos (movimientos largos, cambios
        # de herramienta, feed-hold). En ese modo NO se ponen timeouts: se
        # alimenta indefinidamente y solo se detiene con CANCELAR. En modo punch
        # (normal) si hay timeouts como red de seguridad.

        phase = "open"
        _observe(phase=phase)
        with serial.Serial(
            port=device_path,
            baudrate=profile["baudrate"],
            bytesize=BYTESIZE_MAP[profile["bytesize"]],
            parity=PARITY_MAP[profile["parity"]],
            stopbits=STOPBITS_MAP[profile["stopbits"]],
            xonxoff=(flow == "xonxoff"),
            rtscts=(flow == "rtscts"),
            timeout=5,
            write_timeout=(None if dripfeed else PUNCH_TIMEOUT_SECONDS),
        ) as ser:
            with _ser_lock:
                _current_ser = ser
            closing_error = None
            try:
                phase = "control_lines"
                _observe(phase=phase)
                # Estado de las lineas DTR/RTS. pyserial las ENCIENDE por defecto
                # al abrir; muchas configuraciones de PC que funcionan las tienen
                # APAGADAS ("Enable DTR/RTS" desmarcados), y algunas maquinas no
                # aceptan datos si no coinciden. Por defecto las dejamos apagadas
                # (igual que esa config); se pueden encender por perfil.
                try:
                    ser.dtr = bool(profile.get("dtr", False))
                    if flow != "rtscts":   # en rtscts la RTS la maneja el driver
                        ser.rts = bool(profile.get("rts", False))
                except (OSError, ValueError):
                    pass

                phase = "write"
                _capture_baseline(ser)
                _observe(phase=phase)
                if total == 0:
                    state.update_transfer(percent=100)
                for i in range(0, total, CHUNK_SIZE):
                    if _cancel_event.is_set():
                        raise _Cancelled()
                    chunk = payload[i:i + CHUNK_SIZE]
                    # Con xonxoff/rtscts activado, pyserial pausa la escritura
                    # automaticamente hasta que la maquina mande XON (o baje
                    # RTS/CTS), respetando write_timeout, asi que no hace falta
                    # manejar el flow control a mano. Ojo: no se usa ser.flush()
                    # (tcdrain) aqui a proposito: aunque libera el GIL, no tiene
                    # un timeout propio y requiere otra estrategia de cancelacion.
                    remaining = chunk
                    while remaining:
                        _observe(write_started_monotonic=time.monotonic())
                        written = ser.write(remaining)
                        if _cancel_event.is_set():
                            raise _Cancelled()
                        # cancel_write() may return a short write. Never skip the
                        # unwritten tail or count bytes the driver did not accept.
                        if not isinstance(written, int) or not 0 < written <= len(remaining):
                            raise serial.SerialException("El puerto no aceptó los datos del programa")
                        sent += written
                        _observe(bytes_queued=sent, last_progress_monotonic=time.monotonic(),
                                 write_started_monotonic=None)
                        remaining = remaining[written:]
                        percent = int(sent * 100 / total) if total else 100
                        state.update_transfer(bytes_sent=sent, percent=percent)

                # IMPORTANTE: write() solo mete los bytes al buffer del sistema y
                # del adaptador; regresa al instante. Si cerramos el puerto aqui,
                # a baja velocidad (4800/9600) se descarta lo que aun no salio
                # fisicamente y la maquina no recibe (o recibe incompleto). Por eso
                # esperamos a que el buffer de salida se vacie antes de cerrar.
                # Se usa out_waiting + sleep (no tcdrain) para no congelar la app y
                # poder poner un timeout si la maquina se queda en XOFF.
                state.update_transfer(
                    message="Finalizando goteo…" if dripfeed else "Finalizando envio..."
                )
                phase = "drain"
                _observe(phase=phase)
                # En goteo no hay limite de tiempo. En punch, los 120 s limitan
                # una pausa sin avance, no la duración de un archivo a baja
                # velocidad. El reloj monotónico no cambia con NTP o la fecha.
                drain_deadline = None if dripfeed else time.monotonic() + PUNCH_TIMEOUT_SECONDS
                previous_pending = None
                while True:
                    if _cancel_event.is_set():
                        raise _Cancelled()
                    pending = ser.out_waiting
                    if pending == 0:
                        break
                    if previous_pending is not None and pending < previous_pending:
                        _observe(last_progress_monotonic=time.monotonic())
                    if previous_pending is not None and pending < previous_pending and not dripfeed:
                        drain_deadline = time.monotonic() + PUNCH_TIMEOUT_SECONDS
                    previous_pending = pending
                    if drain_deadline is not None and time.monotonic() > drain_deadline:
                        raise serial.SerialException(
                            "Se agoto el tiempo esperando a que la maquina reciba "
                            "(¿esta en modo recepcion? ¿control de flujo/cable correctos?)"
                        )
                    # No ocultar OSError: SerialException también deriva de él.
                    # Un fallo al consultar la cola no confirma que llegó todo.
                    time.sleep(0.05)
                # margen para que el FIFO interno del adaptador USB termine de salir
                time.sleep(0.3)
                if _cancel_event.is_set():
                    raise _Cancelled()
                phase = "close"
            except BaseException as error:
                closing_error = error
                raise
            finally:
                _retire_serial(ser, phase, closing_error)

        state.update_transfer(status="success", percent=100, message="Transferencia completada")
        outcome = "success"
    except _Cancelled:
        outcome = "cancelled"
        state.update_transfer(status="cancelled", message="Envío cancelado")
    except serial.SerialException as e:
        # cancel_write() puede hacer que write() lance SerialException; si se
        # pidio cancelar, lo tratamos como cancelacion, no como error.
        if _cancel_event.is_set():
            outcome = "cancelled"
            state.update_transfer(status="cancelled", message="Envío cancelado")
        else:
            failure = e
            if isinstance(e, serial.SerialTimeoutException):
                message = (
                    f"Se agotó el tiempo de escritura ({PUNCH_TIMEOUT_SECONDS} s). "
                    "Revisa el modo de recepción y el control de flujo de la máquina."
                )
            else:
                message = "Error de puerto serial: {}".format(e)
            state.update_transfer(status="error", message=message)
    except FileNotFoundError as e:
        failure = e
        state.update_transfer(status="error", message="El archivo ya no existe en la carpeta compartida")
    except Exception as e:  # noqa: BLE001 - reportar cualquier falla al usuario en pantalla
        failure = e
        state.update_transfer(status="error", message="Error inesperado: {}".format(e))
    finally:
        with _ser_lock:
            observation = _serial_observation
        finished = time.monotonic()
        error_fields = {}
        if failure is not None and observation.get("error_type") is None:
            error_fields = dict(failure_phase=phase, error_type=type(failure).__name__[:64],
                                error_detected_monotonic=finished)
        _observe(phase="finished", outcome=outcome, finished_monotonic=finished,
                 close_completed_monotonic=finished if observation.get("close_started_monotonic") is not None else None,
                 **error_fields)
        # One bounded terminal event also preserves successes/cancellations.
        # Progress counts accepted writes, not receipt at the CNC. A write
        # interrupted by an error/cancel can have accepted additional bytes.
        # Do not add program contents or network credentials to these events.
        log = _logger.error if failure is not None else _logger.info
        log(
            "serial_transfer finished transfer_id=%s outcome=%s phase=%s port=%r "
            "bytes_queued=%d total_bytes=%d prepared_sha256=%s elapsed_seconds=%.3f "
            "cnc_receipt_confirmed=false queued_count_may_be_incomplete=%s settings=%r error=%r",
            transfer_id, outcome, phase, device_path, sent, total, prepared_sha256,
            time.monotonic() - started_at, outcome != "success", settings, failure,
            exc_info=(type(failure), failure, failure.__traceback__) if failure is not None else None,
        )
        _transfer_lock.release()
