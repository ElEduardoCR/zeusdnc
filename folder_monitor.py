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


def _looks_binary(data):
    """Heuristica barata para saber si el archivo es binario. Se miran los
    primeros 4 KB por:

    1. Byte NUL. latin-1 / utf-8 / cp1252 nunca lo tienen en texto.
    2. BOM de UTF-16/UTF-32. Es texto, pero el editor (1 columna por
       'carácter') y el resaltado se confunden, asi que tambien lo
       bloqueamos.
    3. Firmas magicas de formatos que NO tienen NUL en los primeros bytes
       pero claramente no son texto plano: PDF, ZIP/JAR/DOCX/XLSX, RAR,
       7z, JPEG, GIF.
    """
    if not data:
        return False
    sample = data[:4096]
    if b"\x00" in sample:
        return True
    if len(sample) >= 4:
        head2 = sample[:2]
        if head2 in (b"\xff\xfe", b"\xfe\xff"):
            return True
        if sample[:4] in (b"\xff\xfe\x00\x00", b"\x00\x00\xfe\xff"):
            return True
    head4 = sample[:4]
    head6 = sample[:6]
    # PDF: empieza con "%PDF-"
    if sample[:5] == b"%PDF-":
        return True
    # ZIP / JAR / DOCX / XLSX / PPTX / ODT: "PK\x03\x04"
    if head4[:4] == b"PK\x03\x04":
        return True
    # RAR: "Rar!\x1a\x07"
    if head6 == b"Rar!\x1a\x07":
        return True
    # 7-Zip: 0x37 0x7A 0xBC 0xAF 0x27 0x1C
    if head6 == b"\x37\x7a\xbc\xaf\x27\x1c":
        return True
    # JPEG: FF D8 FF
    if head4[:3] == b"\xff\xd8\xff":
        return True
    # GIF87a / GIF89a
    if sample[:6] in (b"GIF87a", b"GIF89a"):
        return True
    return False


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


def search_files(query, limit=500):
    """Busca archivos por nombre de forma recursiva dentro de la carpeta.
    Pensado para miles de archivos: es case-insensitive por subcadena y se
    corta al llegar a 'limit' resultados.
    """
    query = (query or "").strip().lower()
    if not query:
        return []
    base = os.path.realpath(WATCH_DIR)
    results = []
    for root, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for fn in sorted(files, key=str.lower):
            if _is_ignored(fn) or query not in fn.lower():
                continue
            full = os.path.join(root, fn)
            rel = os.path.relpath(full, base)
            reldir = os.path.relpath(root, base)
            if reldir == ".":
                reldir = ""
            try:
                st = os.stat(full)
                size, mtime = st.st_size, st.st_mtime
            except OSError:
                size, mtime = 0, 0
            results.append({"name": fn, "path": rel, "dir": reldir, "size": size, "mtime": mtime})
            if len(results) >= limit:
                return results
    return results


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
    if _looks_binary(raw):
        # No intentamos mostrar el contenido: un binario "pasa" por latin-1
        # pero rompe el editor (caracteres de control, el resaltado entra en
        # bucles, etc.). Devolvemos un error tipado para que el frontend
        # muestre 'Archivo incompatible'.
        return {
            "ok": False,
            "error": "Archivo incompatible (no es texto)",
            "binary": True,
            "name": os.path.basename(target),
            "path": _rel(base, target),
        }
    # latin-1 mapea 1 a 1 cada byte: no falla con G-code/ISO ni binario.
    content = raw.decode("latin-1")
    return {
        "ok": True,
        "path": _rel(base, target),
        "name": os.path.basename(target),
        "content": content,
        "truncated": truncated,
    }


def _valid_filename(name):
    name = (name or "").strip()
    if not name or name in (".", ".."):
        return False
    if name.startswith("."):
        return False
    if "/" in name or "\\" in name:
        return False
    return True


def save_file(rel_path, content):
    """Guarda contenido (str) en un archivo existente o nuevo dentro de la
    carpeta. Devuelve (True, None) o (False, error)."""
    target = resolve_path(rel_path)
    if target is None or os.path.isdir(target):
        return False, "Ruta invalida"
    try:
        # latin-1 mapea 1 a 1 cada byte; 'replace' evita fallar si el editor
        # trajo algun caracter fuera de ese rango.
        with open(target, "wb") as f:
            f.write(content.encode("latin-1", errors="replace"))
    except OSError as e:
        return False, str(e)
    return True, None


def create_file(dir_rel, name):
    """Crea un archivo vacio 'name' dentro de la subcarpeta 'dir_rel'.
    Devuelve (ruta_relativa, None) o (None, error)."""
    if not _valid_filename(name):
        return None, "Nombre de archivo invalido"
    dir_abs = resolve_path(dir_rel)
    if dir_abs is None or not os.path.isdir(dir_abs):
        return None, "Carpeta invalida"
    target = os.path.join(dir_abs, name.strip())
    if os.path.exists(target):
        return None, "Ya existe un archivo con ese nombre"
    try:
        with open(target, "wb") as f:
            f.write(b"")
    except OSError as e:
        return None, str(e)
    base = os.path.realpath(WATCH_DIR)
    return _rel(base, target), None


def delete_file(rel_path):
    target = resolve_path(rel_path)
    if target is None or not os.path.isfile(target):
        return False, "Archivo no encontrado"
    try:
        os.remove(target)
    except OSError as e:
        return False, str(e)
    return True, None


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
