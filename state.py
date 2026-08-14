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
        # La Orange Pi vive dentro de una sola CNC. El puerto es un detalle de
        # hardware y nunca una decisión del operador.
        self.usb_devices = {}            # {ruta: descripcion}
        self.active_device = None        # puerto elegido para enviar
        self._active_user_pick = False   # True si el usuario lo eligio a mano
        self.active_machine_id = None    # se puede elegir aunque no haya cable
        self.files_version = 0           # se incrementa en cada cambio de la carpeta
        self.transfer = dict(_EMPTY_TRANSFER)

    def _recompute_active(self):
        # Debe llamarse con el lock tomado.
        if self.usb_devices:
            # Conserva el adaptador actual si sigue presente; si no, usa el
            # primero estable. Esto también evita pedir un "puerto" si udev
            # expone más de un nodo durante un reconectado.
            if self.active_device not in self.usb_devices:
                self.active_device = sorted(self.usb_devices)[0]
            self._active_user_pick = False
        else:
            self.active_device = None
            self._active_user_pick = False

    def snapshot(self):
        with self._lock:
            devices = [{"path": p, "desc": d} for p, d in sorted(self.usb_devices.items())]
            return {
                "usb_devices": devices,
                "active_device": self.active_device,
                "active_device_desc": self.usb_devices.get(self.active_device),
                "active_machine_id": self.active_machine_id,
                "files_version": self.files_version,
                "transfer": dict(self.transfer),
            }

    def on_usb_add(self, device_path, desc=None):
        # Conectar un cable no cambia la maquina elegida.
        with self._lock:
            self.usb_devices[device_path] = desc
            self._recompute_active()

    def on_usb_remove(self, device_path):
        with self._lock:
            self.usb_devices.pop(device_path, None)
            self._recompute_active()

    def select_device(self, device_path):
        with self._lock:
            if device_path in self.usb_devices:
                self.active_device = device_path
                self._active_user_pick = True
                return True
            return False

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
