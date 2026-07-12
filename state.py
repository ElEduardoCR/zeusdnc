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
        self.usb_device = None        # p.ej. "/dev/ttyUSB0" o None si no hay adaptador
        self.awaiting_machine = False  # True: hay adaptador pero aun no se eligio maquina
        self.active_machine_id = None
        self.files = []
        self.transfer = dict(_EMPTY_TRANSFER)

    def snapshot(self):
        with self._lock:
            return {
                "usb_device": self.usb_device,
                "awaiting_machine": self.awaiting_machine,
                "active_machine_id": self.active_machine_id,
                "files": list(self.files),
                "transfer": dict(self.transfer),
            }

    def on_usb_add(self, device_path):
        with self._lock:
            self.usb_device = device_path
            self.awaiting_machine = True
            self.active_machine_id = None

    def on_usb_remove(self, device_path):
        with self._lock:
            if self.usb_device == device_path:
                self.usb_device = None
                self.awaiting_machine = False
                self.active_machine_id = None

    def select_machine(self, machine_id):
        with self._lock:
            if not self.usb_device:
                return False
            self.active_machine_id = machine_id
            self.awaiting_machine = False
            return True

    def clear_machine(self):
        with self._lock:
            if self.usb_device:
                self.awaiting_machine = True
                self.active_machine_id = None

    def set_files(self, files):
        with self._lock:
            self.files = files

    def update_transfer(self, **kwargs):
        with self._lock:
            self.transfer.update(kwargs)

    def reset_transfer(self):
        with self._lock:
            self.transfer = dict(_EMPTY_TRANSFER)


state = AppState()
