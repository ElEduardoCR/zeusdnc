"""Estado compartido en memoria entre el monitor USB, el monitor de carpeta,
el hilo de transferencia serial y las rutas Flask. Todo acceso pasa por un
lock para que los distintos hilos no pisen datos entre si.
"""
import threading

_EMPTY_TRANSFER = {
    "status": "idle",       # idle | sending | success | error
    "filename": None,
    "machine": None,
    "bytes_sent": 0,
    "total_bytes": 0,
    "percent": 0,
    "message": "",
}


class AppState:
    def __init__(self):
        self._lock = threading.Lock()
        self.usb_device = None          # p.ej. "/dev/ttyUSB0" o None si no hay cable
        self.active_machine_id = None   # se puede elegir aunque no haya cable
        self.files_version = 0          # se incrementa en cada cambio de la carpeta
        self.transfer = dict(_EMPTY_TRANSFER)

    def snapshot(self):
        with self._lock:
            return {
                "usb_device": self.usb_device,
                "active_machine_id": self.active_machine_id,
                "files_version": self.files_version,
                "transfer": dict(self.transfer),
            }

    def on_usb_add(self, device_path):
        # Conectar el cable no cambia la maquina elegida: el usuario pudo
        # haberla seleccionado antes de conectar.
        with self._lock:
            self.usb_device = device_path

    def on_usb_remove(self, device_path):
        with self._lock:
            if self.usb_device == device_path:
                self.usb_device = None

    def select_machine(self, machine_id):
        with self._lock:
            self.active_machine_id = machine_id

    def clear_machine(self):
        with self._lock:
            self.active_machine_id = None

    def bump_files_version(self):
        with self._lock:
            self.files_version += 1

    def update_transfer(self, **kwargs):
        with self._lock:
            self.transfer.update(kwargs)

    def reset_transfer(self):
        with self._lock:
            self.transfer = dict(_EMPTY_TRANSFER)


state = AppState()
