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


def _list_files():
    files = []
    try:
        with os.scandir(WATCH_DIR) as it:
            for entry in it:
                if entry.is_file():
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
