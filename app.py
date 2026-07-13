"""Backend Flask del sistema DNC: sirve la interfaz tactil de 3 columnas y
expone las rutas para navegar la carpeta de programas (con subcarpetas),
ver el contenido de un programa, elegir maquina activa, enviar un archivo
por serial y consultar el progreso.
"""
import os

from flask import Flask, jsonify, render_template, request

import folder_monitor
import serial_transfer
import usb_monitor
from machines import delete_machine, get_machine, load_machines, save_machine
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
        "machines": machines,
        "active_machine": active,
        "active_machine_id": snap["active_machine_id"],
        "files_version": snap["files_version"],
        "transfer": snap["transfer"],
    })


@app.route("/api/files")
def api_files():
    return jsonify(folder_monitor.list_dir(request.args.get("path", "")))


@app.route("/api/file")
def api_file():
    data = folder_monitor.read_file(request.args.get("path", ""))
    if data is None:
        return jsonify({"ok": False, "error": "Archivo no encontrado"}), 404
    return jsonify(data)


@app.route("/api/search")
def api_search():
    return jsonify(folder_monitor.search_files(request.args.get("q", "")))


@app.route("/api/file/save", methods=["POST"])
def api_file_save():
    data = request.get_json(force=True, silent=True) or {}
    ok, err = folder_monitor.save_file(data.get("path"), data.get("content", ""))
    if not ok:
        return jsonify({"ok": False, "error": err}), 400
    return jsonify({"ok": True})


@app.route("/api/file/new", methods=["POST"])
def api_file_new():
    data = request.get_json(force=True, silent=True) or {}
    rel, err = folder_monitor.create_file(data.get("dir", ""), data.get("name", ""))
    if err:
        return jsonify({"ok": False, "error": err}), 400
    return jsonify({"ok": True, "path": rel})


@app.route("/api/file/delete", methods=["POST"])
def api_file_delete():
    data = request.get_json(force=True, silent=True) or {}
    ok, err = folder_monitor.delete_file(data.get("path"))
    if not ok:
        return jsonify({"ok": False, "error": err}), 400
    return jsonify({"ok": True})


@app.route("/api/machines")
def api_machines():
    return jsonify(load_machines())


@app.route("/api/machine/save", methods=["POST"])
def api_machine_save():
    data = request.get_json(force=True, silent=True) or {}
    machine, err = save_machine(data)
    if err:
        return jsonify({"ok": False, "error": err}), 400
    return jsonify({"ok": True, "machine": machine})


@app.route("/api/machine/delete", methods=["POST"])
def api_machine_delete():
    data = request.get_json(force=True, silent=True) or {}
    machine_id = data.get("id")
    ok, err = delete_machine(machine_id)
    if not ok:
        return jsonify({"ok": False, "error": err}), 400
    # Si la maquina borrada era la activa, se limpia la seleccion.
    if state.snapshot()["active_machine_id"] == machine_id:
        state.clear_machine()
    return jsonify({"ok": True})


@app.route("/api/machine/select", methods=["POST"])
def api_machine_select():
    data = request.get_json(force=True, silent=True) or {}
    machine_id = data.get("id")
    if not machine_id or not get_machine(machine_id):
        return jsonify({"ok": False, "error": "Maquina invalida"}), 400
    state.select_machine(machine_id)
    return jsonify({"ok": True})


@app.route("/api/machine/clear", methods=["POST"])
def api_machine_clear():
    state.clear_machine()
    return jsonify({"ok": True})


@app.route("/api/send", methods=["POST"])
def api_send():
    snap = state.snapshot()
    if not snap["usb_device"]:
        return jsonify({"ok": False, "error": "Cable RS232 no conectado"}), 409
    if not snap["active_machine_id"]:
        return jsonify({"ok": False, "error": "Selecciona una maquina antes de enviar"}), 409
    if snap["transfer"]["status"] == "sending":
        return jsonify({"ok": False, "error": "Ya hay una transferencia en curso"}), 409

    data = request.get_json(force=True, silent=True) or {}
    rel_path = data.get("path")
    abs_path = folder_monitor.resolve_path(rel_path) if rel_path else None
    if not abs_path or not os.path.isfile(abs_path):
        return jsonify({"ok": False, "error": "Archivo invalido"}), 400

    profile = get_machine(snap["active_machine_id"])
    if not profile:
        return jsonify({"ok": False, "error": "Perfil de maquina no encontrado"}), 500

    state.reset_transfer()
    ok, err = serial_transfer.start_transfer(
        snap["usb_device"], profile, abs_path, os.path.basename(abs_path)
    )
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
