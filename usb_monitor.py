"""Deteccion en tiempo real del adaptador USB-RS232 con pyudev.

El adaptador es unico y movil (se conecta/desconecta segun la maquina a
usar), por lo que nunca se hardcodea /dev/ttyUSBx: se detecta el nodo real
cada vez que aparece o desaparece.
"""
import re

import pyudev

from state import state

USB_TTY_RE = re.compile(r"^/dev/ttyUSB\d+$")


def _handle_event(action, device):
    devnode = device.device_node
    if not devnode or not USB_TTY_RE.match(devnode):
        return
    if action == "add":
        state.on_usb_add(devnode)
    elif action == "remove":
        state.on_usb_remove(devnode)


def start_usb_monitor():
    context = pyudev.Context()

    # Si el adaptador ya estaba conectado cuando arranco el servicio, lo
    # tomamos como recien conectado para que el usuario deba confirmar la
    # maquina de todas formas.
    for device in context.list_devices(subsystem="tty"):
        devnode = device.device_node
        if devnode and USB_TTY_RE.match(devnode):
            state.on_usb_add(devnode)
            break

    monitor = pyudev.Monitor.from_netlink(context)
    monitor.filter_by(subsystem="tty")
    observer = pyudev.MonitorObserver(monitor, _handle_event)
    observer.daemon = True
    observer.start()
    return observer
