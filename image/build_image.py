from __future__ import annotations

import argparse
import hashlib
import json
import lzma
import os
import re
import shutil
import struct
import tarfile
import tempfile
import time
import urllib.request
from collections import deque
from dataclasses import dataclass
from pathlib import Path

from pyfatfs.PyFatFS import PyFatFS


ROOT = Path(__file__).resolve().parent.parent
IMAGE_DIR = ROOT / "image"
CACHE_DIR = IMAGE_DIR / "cache"
BUILD_DIR = IMAGE_DIR / "build"
DIST_DIR = IMAGE_DIR / "dist"

VERSION = "0.2.0"
BASE_NAME = "2026-06-18-raspios-trixie-arm64-lite.img.xz"
BASE_URL = (
    "https://downloads.raspberrypi.com/raspios_lite_arm64/images/"
    "raspios_lite_arm64-2026-06-19/" + BASE_NAME
)
BASE_SHA256 = "acff736ca7945e3b305f07cda4abdb870910e12634991da69783611756e381b3"
BASE_INFO_URL = BASE_URL.removesuffix(".img.xz") + ".info"
DEBIAN_INDEX_URL = (
    "https://deb.debian.org/debian/dists/trixie/main/binary-arm64/Packages.xz"
)
DEBIAN_POOL_URL = "https://deb.debian.org/debian/"

SYSTEMD_RUN_ARGS = (
    "systemd.run=/boot/firstrun.sh "
    "systemd.run_success_action=reboot "
    "systemd.unit=kernel-command-line.target"
)

PAYLOAD_FILES = (
    "machines.py",
    "serial_transfer.py",
    "state.py",
    "system_info.py",
    "usb_monitor.py",
)
PAYLOAD_DIRS = ("config", "qt_app", "zeuz_core")


@dataclass(frozen=True)
class Package:
    name: str
    version: str
    filename: str
    sha256: str
    depends: str
    pre_depends: str
    provides: tuple[str, ...]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def download(url: str, destination: Path, expected_sha256: str | None = None) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and (not expected_sha256 or sha256(destination) == expected_sha256):
        return destination
    temp = destination.with_suffix(destination.suffix + ".part")
    request = urllib.request.Request(url, headers={"User-Agent": "ZeuzImageBuilder/0.1"})
    with urllib.request.urlopen(request) as response, temp.open("wb") as output:
        total = int(response.headers.get("Content-Length", "0"))
        done = 0
        while True:
            block = response.read(1024 * 1024)
            if not block:
                break
            output.write(block)
            done += len(block)
            if total:
                print(f"\r  {destination.name}: {done * 100 // total:3d}%", end="", flush=True)
    if total:
        print()
    if expected_sha256 and sha256(temp) != expected_sha256:
        temp.unlink(missing_ok=True)
        raise RuntimeError(f"SHA-256 inválido para {destination.name}")
    os.replace(temp, destination)
    return destination


def parse_deb822(text: str) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    for paragraph in re.split(r"\n\s*\n", text):
        if not paragraph.strip():
            continue
        record: dict[str, str] = {}
        current = ""
        for line in paragraph.splitlines():
            if line.startswith((" ", "\t")) and current:
                record[current] += " " + line.strip()
                continue
            if ":" not in line:
                continue
            current, value = line.split(":", 1)
            record[current] = value.strip()
        records.append(record)
    return records


def installed_packages(info_text: str) -> set[str]:
    result = set()
    for match in re.finditer(r"^ii\s+(\S+)", info_text, flags=re.MULTILINE):
        result.add(match.group(1).split(":", 1)[0])
    return result


def normalize_package_name(value: str) -> str:
    value = re.sub(r"\[[^\]]*\]", "", value)
    value = re.sub(r"<[^>]*>", "", value)
    value = re.sub(r"\([^)]*\)", "", value)
    return value.strip().split(":", 1)[0]


def dependency_groups(value: str) -> list[list[str]]:
    groups: list[list[str]] = []
    for group in value.split(","):
        alternatives = [
            normalize_package_name(item)
            for item in group.split("|")
            if normalize_package_name(item)
        ]
        if alternatives:
            groups.append(alternatives)
    return groups


def load_package_index(index_path: Path) -> tuple[dict[str, Package], dict[str, list[str]]]:
    with lzma.open(index_path, "rt", encoding="utf-8", errors="replace") as handle:
        records = parse_deb822(handle.read())
    packages: dict[str, Package] = {}
    providers: dict[str, list[str]] = {}
    for record in records:
        name = record.get("Package")
        filename = record.get("Filename")
        checksum = record.get("SHA256")
        architecture = record.get("Architecture", "")
        if not name or not filename or not checksum or architecture not in {"arm64", "all"}:
            continue
        provides = tuple(
            normalize_package_name(item)
            for item in record.get("Provides", "").split(",")
            if normalize_package_name(item)
        )
        package = Package(
            name=name,
            version=record.get("Version", ""),
            filename=filename,
            sha256=checksum,
            depends=record.get("Depends", ""),
            pre_depends=record.get("Pre-Depends", ""),
            provides=provides,
        )
        packages[name] = package
        for provided in provides:
            providers.setdefault(provided, []).append(name)
    return packages, providers


def resolve_packages(
    requested: list[str],
    installed: set[str],
    packages: dict[str, Package],
    providers: dict[str, list[str]],
) -> list[Package]:
    selected: dict[str, Package] = {}
    queue = deque(requested)
    while queue:
        wanted = normalize_package_name(queue.popleft())
        if not wanted or wanted in installed or wanted in selected:
            continue
        actual = wanted
        if actual not in packages:
            installed_provider = next(
                (name for name in providers.get(actual, []) if name in installed),
                None,
            )
            if installed_provider:
                continue
            candidates = providers.get(actual, [])
            if not candidates:
                raise RuntimeError(f"No se encontró el paquete o proveedor: {wanted}")
            actual = candidates[0]
            if actual in installed or actual in selected:
                continue
        package = packages[actual]
        selected[actual] = package
        for alternatives in dependency_groups(
            ",".join(filter(None, (package.pre_depends, package.depends)))
        ):
            choice = next((name for name in alternatives if name in installed), None)
            if not choice:
                choice = next((name for name in alternatives if name in packages), None)
            if not choice:
                choice = next(
                    (
                        provider
                        for name in alternatives
                        for provider in providers.get(name, [])
                        if provider in installed or provider in packages
                    ),
                    None,
                )
            if not choice:
                raise RuntimeError(
                    f"No se pudo resolver dependencia de {actual}: {' | '.join(alternatives)}"
                )
            queue.append(choice)
    return sorted(selected.values(), key=lambda item: item.name)


def read_requested_packages() -> list[str]:
    result = []
    for line in (IMAGE_DIR / "packages.txt").read_text(encoding="utf-8").splitlines():
        clean = line.split("#", 1)[0].strip()
        if clean:
            result.append(clean)
    return result


def prepare_debs() -> tuple[list[Package], str]:
    info_path = download(BASE_INFO_URL, CACHE_DIR / "base.info")
    index_path = download(DEBIAN_INDEX_URL, CACHE_DIR / "Packages-arm64.xz")
    info_text = info_path.read_text(encoding="utf-8", errors="replace")
    installed = installed_packages(info_text)
    packages, providers = load_package_index(index_path)
    selected = resolve_packages(read_requested_packages(), installed, packages, providers)

    deb_dir = CACHE_DIR / "debs"
    deb_dir.mkdir(parents=True, exist_ok=True)
    for position, package in enumerate(selected, start=1):
        destination = deb_dir / Path(package.filename).name
        print(f"[{position:02d}/{len(selected):02d}] {package.name} {package.version}")
        download(DEBIAN_POOL_URL + package.filename, destination, package.sha256)
    return selected, hashlib.sha256(info_text.encode()).hexdigest()


def create_payload(destination: Path) -> None:
    with tarfile.open(destination, "w:gz", compresslevel=9) as archive:
        for name in PAYLOAD_FILES:
            archive.add(ROOT / name, arcname=f"zeusdnc/{name}")
        for name in PAYLOAD_DIRS:
            base = ROOT / name
            for path in sorted(base.rglob("*")):
                if path.is_dir() or "__pycache__" in path.parts or path.suffix in {".pyc", ".pyo"}:
                    continue
                if path.name == "runtime.json":
                    continue
                archive.add(path, arcname=f"zeusdnc/{path.relative_to(ROOT).as_posix()}")


def decompress_image(source: Path, destination: Path) -> None:
    if destination.exists():
        return
    temp = destination.with_suffix(".img.part")
    print(f"Descomprimiendo {source.name}…")
    with lzma.open(source, "rb") as compressed, temp.open("wb") as raw:
        shutil.copyfileobj(compressed, raw, length=8 * 1024 * 1024)
    os.replace(temp, destination)


def boot_partition_offset(image: Path) -> tuple[int, int]:
    with image.open("rb") as handle:
        mbr = handle.read(512)
    if len(mbr) != 512 or mbr[510:512] != b"\x55\xaa":
        raise RuntimeError("La imagen no contiene una tabla MBR válida")
    entry = mbr[446:462]
    start_lba, sectors = struct.unpack_from("<II", entry, 8)
    if not start_lba or not sectors:
        raise RuntimeError("No se encontró la partición de arranque")
    return start_lba * 512, sectors * 512


def write_fs_bytes(fs: PyFatFS, path: str, data: bytes) -> None:
    parent = str(Path(path).parent).replace("\\", "/")
    if parent not in {"", "."}:
        fs.makedirs(parent, recreate=True)
    if fs.exists(path):
        fs.remove(path)
    with fs.openbin(path, "w") as handle:
        handle.write(data)


def inject_image(
    image: Path,
    payload: Path,
    packages: list[Package],
    base_info_hash: str,
) -> dict:
    offset, partition_size = boot_partition_offset(image)
    manifest = {
        "product": "Zeuz DNC",
        "version": VERSION,
        "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "base_image": BASE_NAME,
        "base_sha256": BASE_SHA256,
        "base_info_sha256": base_info_hash,
        "architecture": "arm64",
        "compatible_models": ["Raspberry Pi 3", "Raspberry Pi 4", "Raspberry Pi 5", "Zero 2 W"],
        "packages": [
            {"name": package.name, "version": package.version, "sha256": package.sha256}
            for package in packages
        ],
    }

    fs = PyFatFS(str(image), offset=offset, preserve_case=True, read_only=False)
    try:
        cmdline = fs.readtext("cmdline.txt").strip()
        cmdline = re.sub(r"\s+systemd\.run=\S+.*$", "", cmdline)
        additions = (
            f" {SYSTEMD_RUN_ARGS} quiet loglevel=3 logo.nologo "
            "vt.global_cursor_default=0 consoleblank=0"
        )
        write_fs_bytes(fs, "cmdline.txt", (cmdline + additions + "\n").encode())

        config = fs.readtext("config.txt")
        if "# Zeuz DNC" not in config:
            config += (
                "\n# Zeuz DNC\n"
                "disable_splash=1\n"
                "dtparam=audio=off\n"
            )
        write_fs_bytes(fs, "config.txt", config.encode())
        write_fs_bytes(fs, "firstrun.sh", (IMAGE_DIR / "firstboot.sh").read_bytes())
        write_fs_bytes(fs, "zeuz/zeusdnc.tar.gz", payload.read_bytes())
        write_fs_bytes(
            fs,
            "zeuz/zeuz-dnc-qt.service",
            (ROOT / "systemd" / "zeuz-dnc-qt.service").read_bytes(),
        )
        write_fs_bytes(
            fs,
            "zeuz/manifest.json",
            (json.dumps(manifest, indent=2, ensure_ascii=False) + "\n").encode(),
        )
        for package in packages:
            source = CACHE_DIR / "debs" / Path(package.filename).name
            write_fs_bytes(fs, f"zeuz/debs/{source.name}", source.read_bytes())
    finally:
        fs.close()

    return {
        "partition_offset": offset,
        "partition_size": partition_size,
        "manifest": manifest,
    }


def validate_image(image: Path) -> dict:
    offset, partition_size = boot_partition_offset(image)
    fs = PyFatFS(str(image), offset=offset, preserve_case=True, read_only=True)
    try:
        required = (
            "cmdline.txt",
            "config.txt",
            "firstrun.sh",
            "zeuz/manifest.json",
            "zeuz/zeusdnc.tar.gz",
            "zeuz/zeuz-dnc-qt.service",
        )
        missing = [path for path in required if not fs.exists(path)]
        if missing:
            raise RuntimeError(f"Faltan archivos en bootfs: {', '.join(missing)}")
        cmdline = fs.readtext("cmdline.txt")
        if SYSTEMD_RUN_ARGS not in cmdline:
            raise RuntimeError("cmdline.txt no activa el aprovisionamiento")
        manifest = json.loads(fs.readtext("zeuz/manifest.json"))
        debs = [path for path in fs.walk.files(filter=["*.deb"])]
        if not debs:
            raise RuntimeError("La imagen no contiene paquetes ARM64")
        expected_hashes = {package["sha256"] for package in manifest["packages"]}
        actual_hashes = set()
        for path in debs:
            digest = hashlib.sha256()
            with fs.openbin(path, "r") as handle:
                for block in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(block)
            actual_hashes.add(digest.hexdigest())
        if actual_hashes != expected_hashes:
            raise RuntimeError("Los checksums de los paquetes ARM64 no coinciden")
        package_names = {package["name"] for package in manifest["packages"]}
        required_qt_packages = {"libqt6opengl6", "qt6-qpa-plugins"}
        if not required_qt_packages.issubset(package_names):
            raise RuntimeError("La imagen no contiene los plugins gráficos EGLFS/QPA")
        return {
            "partition_offset": offset,
            "partition_size": partition_size,
            "manifest": manifest,
            "deb_count": len(debs),
        }
    finally:
        fs.close()


def compress_image(source: Path, destination: Path) -> None:
    temp = destination.with_suffix(destination.suffix + ".part")
    print(f"Comprimiendo {source.name}…")
    with source.open("rb") as raw, lzma.open(temp, "wb", preset=6) as compressed:
        shutil.copyfileobj(raw, compressed, length=8 * 1024 * 1024)
    os.replace(temp, destination)


def main() -> int:
    parser = argparse.ArgumentParser(description="Construir imagen Zeuz DNC para Raspberry Pi")
    parser.add_argument("--no-compress", action="store_true")
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument(
        "--compress-only",
        action="store_true",
        help="comprimir una imagen ya construida sin volver a inyectarla",
    )
    args = parser.parse_args()

    for directory in (CACHE_DIR, BUILD_DIR, DIST_DIR):
        directory.mkdir(parents=True, exist_ok=True)

    image = BUILD_DIR / f"zeuz-dnc-{VERSION}-arm64.img"
    if args.compress_only:
        if not image.exists():
            raise RuntimeError(f"No existe la imagen construida: {image}")
        compressed = DIST_DIR / f"{image.name}.xz"
        compress_image(image, compressed)
        compressed_hash = sha256(compressed)
        checksum = DIST_DIR / f"{compressed.name}.sha256"
        checksum.write_text(
            f"{compressed_hash}  {compressed.name}\n",
            encoding="ascii",
        )
        print(
            json.dumps(
                {
                    "image": str(compressed),
                    "image_size": compressed.stat().st_size,
                    "image_sha256": compressed_hash,
                    "checksum": str(checksum),
                },
                indent=2,
            )
        )
        return 0

    base = download(BASE_URL, CACHE_DIR / BASE_NAME, BASE_SHA256)
    packages, base_info_hash = prepare_debs()
    payload = BUILD_DIR / "zeusdnc.tar.gz"
    create_payload(payload)

    if args.rebuild:
        image.unlink(missing_ok=True)
    decompress_image(base, image)
    result = inject_image(image, payload, packages, base_info_hash)
    validation = validate_image(image)
    if result["partition_offset"] != validation["partition_offset"]:
        raise RuntimeError("La validación de particiones no coincide")

    image_hash = sha256(image)
    (DIST_DIR / f"{image.name}.sha256").write_text(
        f"{image_hash}  {image.name}\n",
        encoding="ascii",
    )

    if not args.no_compress:
        compressed = DIST_DIR / f"{image.name}.xz"
        compress_image(image, compressed)
        compressed_hash = sha256(compressed)
        (DIST_DIR / f"{compressed.name}.sha256").write_text(
            f"{compressed_hash}  {compressed.name}\n",
            encoding="ascii",
        )

    report = {
        **validation,
        "image": str(image),
        "image_size": image.stat().st_size,
        "image_sha256": image_hash,
    }
    (DIST_DIR / "build-report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
