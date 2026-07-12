"""Monitoreo en tiempo real de la carpeta compartida por Samba
(/home/eduardo/cnc-programs) con watchdog, y navegacion segura de sus
subcarpetas/archivos para la interfaz.

- El watchdog es recursivo: cualquier cambio (incluido en subcarpetas)
  incrementa un contador de version; el frontend lo consulta y, cuando
  cambia, vuelve a pedir el listado de la carpeta que esta viendo.
- list_dir / read_file / resolve_path validan siempre que la ruta pedida
  quede DENTRO de la carpeta compartida (evitan path traversal con "..").
"""
import os

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from state import state

WATCH_DIR = "/home/eduardo/cnc-programs"

# Basura que macOS/Windows dejan al copiar por Samba y que no son programas:
# archivos ocultos (empiezan con "."), los sidecar AppleDouble ("._*"),
# .DS_Store, y los indices de miniaturas de Windows.
_IGNORED_NAMES = {"Thumbs.db", "desktop.ini"}

MAX_PREVIEW_BYTES = 2 * 1024 * 1024  # tope para la vista de contenido


def _is_ignored(name):
    return name.startswith(".") or name in _IGNORED_NAMES


def resolve_path(rel_path):
    """Convierte una ruta relativa (enviada por el cliente) a absoluta,
    garantizando que quede dentro de WATCH_DIR. Devuelve None si se sale.
    """
    base = os.path.realpath(WATCH_DIR)
    rel_path = (rel_path or "").strip().lstrip("/")
    target = os.path.realpath(os.path.join(base, rel_path))
    if target == base or target.startswith(base + os.sep):
        return target
    return None


def _rel(base, target):
    return os.path.relpath(target, base) if target != base else ""


def list_dir(rel_path):
    base = os.path.realpath(WATCH_DIR)
    target = resolve_path(rel_path)
    if target is None or not os.path.isdir(target):
        target = base
    rel = _rel(base, target)

    dirs, files = [], []
    try:
        with os.scandir(target) as it:
            for entry in it:
                if _is_ignored(entry.name):
                    continue
                entry_rel = os.path.join(rel, entry.name) if rel else entry.name
                if entry.is_dir():
                    dirs.append({"name": entry.name, "path": entry_rel})
                elif entry.is_file():
                    st = entry.stat()
                    files.append({
                        "name": entry.name,
                        "path": entry_rel,
                        "size": st.st_size,
                        "mtime": st.st_mtime,
                    })
    except FileNotFoundError:
        pass

    dirs.sort(key=lambda d: d["name"].lower())
    files.sort(key=lambda f: f["name"].lower())

    breadcrumb = [{"name": "Programas", "path": ""}]
    if rel:
        acc = ""
        for part in rel.split(os.sep):
            acc = os.path.join(acc, part) if acc else part
            breadcrumb.append({"name": part, "path": acc})

    parent = os.path.dirname(rel) if rel else None

    return {
        "ok": True,
        "path": rel,
        "parent": parent,
        "breadcrumb": breadcrumb,
        "dirs": dirs,
        "files": files,
    }


def read_file(rel_path):
    base = os.path.realpath(WATCH_DIR)
    target = resolve_path(rel_path)
    if target is None or not os.path.isfile(target):
        return None
    with open(target, "rb") as f:
        raw = f.read(MAX_PREVIEW_BYTES + 1)
    truncated = len(raw) > MAX_PREVIEW_BYTES
    if truncated:
        raw = raw[:MAX_PREVIEW_BYTES]
    # latin-1 mapea 1 a 1 cada byte: no falla con G-code/ISO ni binario.
    content = raw.decode("latin-1")
    return {
        "ok": True,
        "path": _rel(base, target),
        "name": os.path.basename(target),
        "content": content,
        "truncated": truncated,
    }


class _Handler(FileSystemEventHandler):
    def on_any_event(self, event):
        state.bump_files_version()


def start_folder_monitor():
    os.makedirs(WATCH_DIR, exist_ok=True)
    state.bump_files_version()

    observer = Observer()
    observer.schedule(_Handler(), WATCH_DIR, recursive=True)
    observer.daemon = True
    observer.start()
    return observer
