"""Carga de perfiles de maquina desde config/machines.json.

El archivo se relee del disco en cada llamada a proposito: asi un usuario
puede editar machines.json (agregar/quitar/ajustar una maquina) y los
cambios se reflejan sin reiniciar el servicio.
"""
import json
import os

MACHINES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config", "machines.json")


def load_machines():
    try:
        with open(MACHINES_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []
    return data.get("machines", [])


def get_machine(machine_id):
    for m in load_machines():
        if m.get("id") == machine_id:
            return m
    return None
