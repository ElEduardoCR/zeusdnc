"""Monitoreo en tiempo real de la carpeta compartida por Samba
(/home/eduardo/cnc-programs) con watchdog, para que la lista de archivos en
la interfaz se actualice sola cuando alguien copia/borra/modifica algo
desde Windows/Mac.
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


def _is_ignored(name):
    return name.startswith(".") or name in _IGNORED_NAMES


def _list_files():
    files = []
    try:
        with os.scandir(WATCH_DIR) as it:
            for entry in it:
                if entry.is_file() and not _is_ignored(entry.name):
                    st = entry.stat()
                    files.append({
                        "name": entry.name,
                        "size": st.st_size,
                        "mtime": st.st_mtime,
                    })
    except FileNotFoundError:
        pass
    files.sort(key=lambda f: f["name"].lower())
    return files


class _Handler(FileSystemEventHandler):
    def on_any_event(self, event):
        state.set_files(_list_files())


def start_folder_monitor():
    os.makedirs(WATCH_DIR, exist_ok=True)
    state.set_files(_list_files())

    observer = Observer()
    observer.schedule(_Handler(), WATCH_DIR, recursive=False)
    observer.daemon = True
    observer.start()
    return observer
