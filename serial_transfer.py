"""Transmision manual de un archivo por el puerto serial detectado.

Es una transferencia completa a la memoria de la maquina ("punch"), no un
drip-feed sincronizado con el ciclo de maquinado: se abre el puerto, se
manda el archivo completo respetando el control de flujo del perfil, y se
cierra.
"""
import threading

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

    thread = threading.Thread(
        target=_run_transfer,
        args=(device_path, machine_profile, filepath, display_name),
        daemon=True,
    )
    thread.start()
    return True, None


def _run_transfer(device_path, profile, filepath, display_name):
    machine_name = profile.get("name", profile.get("id"))
    try:
        terminator = TERMINATOR_MAP[profile["line_terminator"]]
        payload = _prepare_payload(filepath, terminator)
        total = len(payload)

        state.update_transfer(
            status="sending",
            filename=display_name,
            machine=machine_name,
            bytes_sent=0,
            total_bytes=total,
            percent=0,
            message="",
        )

        flow = profile.get("flow_control", "xonxoff")

        with serial.Serial(
            port=device_path,
            baudrate=profile["baudrate"],
            bytesize=BYTESIZE_MAP[profile["bytesize"]],
            parity=PARITY_MAP[profile["parity"]],
            stopbits=STOPBITS_MAP[profile["stopbits"]],
            xonxoff=(flow == "xonxoff"),
            rtscts=(flow == "rtscts"),
            timeout=5,
            write_timeout=30,
        ) as ser:
            sent = 0
            if total == 0:
                state.update_transfer(percent=100)
            for i in range(0, total, CHUNK_SIZE):
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

        state.update_transfer(status="success", percent=100, message="Transferencia completada")
    except serial.SerialException as e:
        state.update_transfer(status="error", message="Error de puerto serial: {}".format(e))
    except FileNotFoundError:
        state.update_transfer(status="error", message="El archivo ya no existe en la carpeta compartida")
    except Exception as e:  # noqa: BLE001 - reportar cualquier falla al usuario en pantalla
        state.update_transfer(status="error", message="Error inesperado: {}".format(e))
    finally:
        _transfer_lock.release()
