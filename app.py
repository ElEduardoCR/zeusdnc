"""Backend Flask del sistema DNC: sirve la interfaz tactil y expone las
rutas para listar maquinas/archivos, elegir maquina activa, enviar un
archivo por serial y consultar el progreso de la transferencia.
"""
from flask import Flask, jsonify, render_template, request

import folder_monitor
import serial_transfer
import usb_monitor
from machines import get_machine, load_machines
from state import state

app = Flask(__name__)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/state")
def api_state():
    snap = state.snapshot()
    machines = load_machines()
    active = None
    if snap["active_machine_id"]:
        active = next((m for m in machines if m["id"] == snap["active_machine_id"]), None)

    return jsonify({
        "usb_connected": snap["usb_device"] is not None,
        "usb_device": snap["usb_device"],
        "awaiting_machine": snap["awaiting_machine"],
        "machines": machines,
        "active_machine": active,
        "files": snap["files"],
        "transfer": snap["transfer"],
    })


@app.route("/api/machines")
def api_machines():
    return jsonify(load_machines())


@app.route("/api/machine/select", methods=["POST"])
def api_machine_select():
    data = request.get_json(force=True, silent=True) or {}
    machine_id = data.get("id")
    if not machine_id or not get_machine(machine_id):
        return jsonify({"ok": False, "error": "Maquina invalida"}), 400

    if not state.select_machine(machine_id):
        return jsonify({"ok": False, "error": "No hay adaptador USB conectado"}), 409
    return jsonify({"ok": True})


@app.route("/api/machine/clear", methods=["POST"])
def api_machine_clear():
    state.clear_machine()
    return jsonify({"ok": True})


@app.route("/api/send", methods=["POST"])
def api_send():
    snap = state.snapshot()
    if not snap["usb_device"] or not snap["active_machine_id"]:
        return jsonify({"ok": False, "error": "Selecciona una maquina antes de enviar"}), 409
    if snap["transfer"]["status"] == "sending":
        return jsonify({"ok": False, "error": "Ya hay una transferencia en curso"}), 409

    data = request.get_json(force=True, silent=True) or {}
    filename = data.get("filename")
    valid_names = {f["name"] for f in snap["files"]}
    if not filename or filename not in valid_names:
        return jsonify({"ok": False, "error": "Archivo invalido"}), 400

    profile = get_machine(snap["active_machine_id"])
    if not profile:
        return jsonify({"ok": False, "error": "Perfil de maquina no encontrado"}), 500

    state.reset_transfer()
    ok, err = serial_transfer.start_transfer(snap["usb_device"], profile, filename)
    if not ok:
        return jsonify({"ok": False, "error": err}), 409
    return jsonify({"ok": True})


@app.route("/api/transfer/status")
def api_transfer_status():
    return jsonify(state.snapshot()["transfer"])


def main():
    usb_monitor.start_usb_monitor()
    folder_monitor.start_folder_monitor()
    app.run(host="0.0.0.0", port=5000, threaded=True, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
