"""Transmision manual de un archivo por el puerto serial detectado.

Es una transferencia completa a la memoria de la maquina ("punch"), no un
drip-feed sincronizado con el ciclo de maquinado: se abre el puerto, se
manda el archivo completo respetando el control de flujo del perfil, y se
cierra.
"""
import threading
import time

import serial

from state import state

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

_transfer_lock = threading.Lock()

# Para cancelar un envio en curso sin apagar ni forzar un error.
_cancel_event = threading.Event()
_ser_lock = threading.Lock()
_current_ser = None


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

    _cancel_event.clear()
    thread = threading.Thread(
        target=_run_transfer,
        args=(device_path, machine_profile, filepath, display_name),
        daemon=True,
    )
    thread.start()
    return True, None


def _run_transfer(device_path, profile, filepath, display_name):
    global _current_ser
    machine_name = profile.get("name", profile.get("id"))
    try:
        terminator = TERMINATOR_MAP[profile["line_terminator"]]
        payload = _prepare_payload(filepath, terminator)
        total = len(payload)

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

        with serial.Serial(
            port=device_path,
            baudrate=profile["baudrate"],
            bytesize=BYTESIZE_MAP[profile["bytesize"]],
            parity=PARITY_MAP[profile["parity"]],
            stopbits=STOPBITS_MAP[profile["stopbits"]],
            xonxoff=(flow == "xonxoff"),
            rtscts=(flow == "rtscts"),
            timeout=5,
            write_timeout=(None if dripfeed else 30),
        ) as ser:
            with _ser_lock:
                _current_ser = ser
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

            sent = 0
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
                # (tcdrain) aqui a proposito - tcdrain() no tiene timeout y
                # no libera el GIL en CPython, asi que si la maquina se
                # queda en XOFF, congelaria TODA la app (no solo este hilo).
                ser.write(chunk)
                sent += len(chunk)
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
            # En goteo no hay limite de tiempo (la maquina puede tardar mucho
            # en consumir); en punch, red de seguridad de 120 s.
            drain_deadline = None if dripfeed else time.time() + 120
            try:
                while ser.out_waiting > 0:
                    if _cancel_event.is_set():
                        raise _Cancelled()
                    if drain_deadline is not None and time.time() > drain_deadline:
                        raise serial.SerialException(
                            "Se agoto el tiempo esperando a que la maquina reciba "
                            "(¿esta en modo recepcion? ¿control de flujo/cable correctos?)"
                        )
                    time.sleep(0.05)
            except (OSError, ValueError):
                pass  # algunos drivers no reportan out_waiting; seguimos
            # margen para que el FIFO interno del adaptador USB termine de salir
            time.sleep(0.3)

        state.update_transfer(status="success", percent=100, message="Transferencia completada")
    except _Cancelled:
        state.update_transfer(status="cancelled", message="Envío cancelado")
    except serial.SerialException as e:
        # cancel_write() puede hacer que write() lance SerialException; si se
        # pidio cancelar, lo tratamos como cancelacion, no como error.
        if _cancel_event.is_set():
            state.update_transfer(status="cancelled", message="Envío cancelado")
        else:
            state.update_transfer(status="error", message="Error de puerto serial: {}".format(e))
    except FileNotFoundError:
        state.update_transfer(status="error", message="El archivo ya no existe en la carpeta compartida")
    except Exception as e:  # noqa: BLE001 - reportar cualquier falla al usuario en pantalla
        state.update_transfer(status="error", message="Error inesperado: {}".format(e))
    finally:
        with _ser_lock:
            _current_ser = None
        _transfer_lock.release()
