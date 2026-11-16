from __future__ import annotations

import hashlib
import io
import json
import stat
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from zeuz_core.updater import (
    _extract_archive,
    _validated_members,
    apply_downloaded_update,
    check_for_update,
)


class UpdaterTests(unittest.TestCase):
    def make_archive(self, entries: list[tuple[str, bytes, bytes]]) -> io.BytesIO:
        payload = io.BytesIO()
        with tarfile.open(fileobj=payload, mode="w:gz") as archive:
            for name, kind, content in entries:
                info = tarfile.TarInfo(name)
                info.type = kind
                info.size = len(content)
                info.linkname = "../outside"
                archive.addfile(info, io.BytesIO(content))
        payload.seek(0)
        return payload

    def test_extract_rejects_unsafe_paths_before_writing(self) -> None:
        for name in ("../escape", "/absolute", "repo/../../escape", "repo/../escape", "."):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                destination = Path(temporary)
                payload = self.make_archive([
                    ("repo/good", tarfile.REGTYPE, b"good"),
                    (name, tarfile.REGTYPE, b"bad"),
                ])
                with tarfile.open(fileobj=payload, mode="r:gz") as archive:
                    with self.assertRaisesRegex(RuntimeError, "ruta insegura"):
                        _extract_archive(archive, destination)
                self.assertEqual(list(destination.iterdir()), [])

    def test_extract_rejects_links_devices_fifo_and_unsupported_types(self) -> None:
        for kind in (tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.CHRTYPE,
                     tarfile.BLKTYPE, tarfile.FIFOTYPE, tarfile.CONTTYPE, b"Z"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temporary:
                destination = Path(temporary)
                payload = self.make_archive([
                    ("repo/good", tarfile.REGTYPE, b"good"),
                    ("repo/bad", kind, b""),
                ])
                with tarfile.open(fileobj=payload, mode="r:gz") as archive:
                    with self.assertRaisesRegex(RuntimeError, "tipo de archivo no permitido"):
                        _extract_archive(archive, destination)
                self.assertEqual(list(destination.iterdir()), [])

    def test_extract_rejects_duplicates_and_file_directory_conflicts(self) -> None:
        cases = [
            [("repo/a", tarfile.REGTYPE, b"a"), ("repo/a", tarfile.REGTYPE, b"b")],
            [("repo/a", tarfile.REGTYPE, b"a"), ("repo/./a", tarfile.REGTYPE, b"b")],
            [("repo/a", tarfile.REGTYPE, b"a"), ("repo/a", tarfile.DIRTYPE, b"")],
            [("repo/a", tarfile.DIRTYPE, b""), ("repo/a", tarfile.REGTYPE, b"a")],
            [("repo/a", tarfile.REGTYPE, b"a"), ("repo/a/b", tarfile.REGTYPE, b"b")],
            [("repo/a/b", tarfile.REGTYPE, b"b"), ("repo/a", tarfile.REGTYPE, b"a")],
        ]
        for entries in cases:
            with self.subTest(entries=entries), tempfile.TemporaryDirectory() as temporary:
                destination = Path(temporary)
                payload = self.make_archive(entries)
                with tarfile.open(fileobj=payload, mode="r:gz") as archive:
                    with self.assertRaisesRegex(RuntimeError, "duplicadas o en conflicto"):
                        _extract_archive(archive, destination)
                self.assertEqual(list(destination.iterdir()), [])

    def test_extract_rejects_invalid_sizes_sparse_and_multiple_roots(self) -> None:
        for size, kind, sparse, expected in (
            (-1, tarfile.REGTYPE, None, "tamaño"),
            (1, tarfile.DIRTYPE, None, "tamaño"),
            (250 * 1024 * 1024 + 1, tarfile.REGTYPE, None, "tamaño permitido"),
            (0, tarfile.REGTYPE, [], "tipo de archivo"),
        ):
            with self.subTest(size=size, kind=kind, sparse=sparse):
                info = tarfile.TarInfo("repo/a")
                info.type, info.size, info.sparse = kind, size, sparse
                with self.assertRaisesRegex(RuntimeError, expected):
                    _validated_members(mock.Mock(getmembers=lambda: [info]))
        payload = self.make_archive([
            ("one/a", tarfile.REGTYPE, b"a"), ("two/b", tarfile.REGTYPE, b"b")])
        with tarfile.open(fileobj=payload, mode="r:gz") as archive:
            with self.assertRaisesRegex(RuntimeError, "raíz única"):
                _validated_members(archive)

    def test_extract_preserves_content_and_safe_executable_modes_without_extractall(self) -> None:
        payload = io.BytesIO()
        with tarfile.open(fileobj=payload, mode="w:gz") as archive:
            for name, mode, content, kind in (
                ("repo/bin/run", 0o7777, b"#!/bin/sh\nexit 0\n", tarfile.REGTYPE),
                ("repo/", 0o7000, b"", tarfile.DIRTYPE),
                ("repo/data", 0o6666, b"\x00contents\xff", tarfile.AREGTYPE),
            ):
                info = tarfile.TarInfo(name)
                info.type, info.mode, info.size = kind, mode, len(content)
                info.uid, info.gid, info.mtime = 12345, 54321, 1
                archive.addfile(info, io.BytesIO(content))
        payload.seek(0)
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary)
            with tarfile.open(fileobj=payload, mode="r:gz") as archive:
                with mock.patch.object(archive, "extractall", side_effect=AssertionError("must not use extractall")):
                    self.assertEqual(_extract_archive(archive, destination), "repo")
            self.assertEqual((destination / "repo/bin/run").read_bytes(), b"#!/bin/sh\nexit 0\n")
            self.assertEqual((destination / "repo/data").read_bytes(), b"\x00contents\xff")
            for name, mode in (("repo", 0o755), ("repo/bin", 0o755),
                               ("repo/bin/run", 0o755), ("repo/data", 0o644)):
                info = (destination / name).stat()
                self.assertEqual(stat.S_IMODE(info.st_mode), mode)
                self.assertEqual(info.st_uid, destination.stat().st_uid)
                self.assertEqual(info.st_gid, destination.stat().st_gid)
                self.assertNotEqual(info.st_mtime, 1)

    def test_extract_rejects_nonempty_destination_without_following_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            destination = root / "destination"
            destination.mkdir()
            outside = root / "outside"
            outside.mkdir()
            (destination / "repo").symlink_to(outside, target_is_directory=True)
            payload = self.make_archive([("repo/file", tarfile.REGTYPE, b"bad")])
            with tarfile.open(fileobj=payload, mode="r:gz") as archive:
                with self.assertRaisesRegex(RuntimeError, "no está vacío"):
                    _extract_archive(archive, destination)
            self.assertEqual(list(outside.iterdir()), [])

    def test_invalid_archive_leaves_installation_state_and_systemd_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            install = root / "opt/zeusdnc"
            install.mkdir(parents=True)
            (install / "old.txt").write_bytes(b"original")
            systemd = root / "systemd"
            systemd.mkdir()
            (systemd / "zeuz-dnc-api.service").write_bytes(b"original unit")
            version, revision = root / "version", root / "revision"
            version.write_bytes(b"0.7.2\n")
            revision.write_bytes(b"a" * 40 + b"\n")
            archive_path = root / "update.tar.gz"
            archive_path.write_bytes(self.make_archive([
                ("repo/VERSION", tarfile.REGTYPE, b"0.7.3\n"),
                ("repo/bad", tarfile.SYMTYPE, b""),
            ]).getvalue())
            state = root / "state.json"
            state.write_text(json.dumps({
                "available": True, "downloaded": True, "latest_version": "0.7.3",
                "latest_revision": "b" * 40,
                "archive_sha256": hashlib.sha256(archive_path.read_bytes()).hexdigest(),
            }))
            original_state = state.read_bytes()
            with self.assertRaisesRegex(RuntimeError, "tipo de archivo no permitido"):
                apply_downloaded_update(state_path=state, archive_path=archive_path,
                                        install_dir=install, version_path=version,
                                        revision_path=revision, systemd_dir=systemd)
            self.assertEqual((install / "old.txt").read_bytes(), b"original")
            self.assertEqual((systemd / "zeuz-dnc-api.service").read_bytes(), b"original unit")
            self.assertEqual(version.read_bytes(), b"0.7.2\n")
            self.assertEqual(revision.read_bytes(), b"a" * 40 + b"\n")
            self.assertEqual(state.read_bytes(), original_state)
            self.assertEqual(list(install.parent.iterdir()), [install])
            self.assertTrue(archive_path.exists())

    def test_newer_local_repair_is_current_without_false_error_or_downgrade(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            version, revision, state = root / "version", root / "revision", root / "state.json"
            version.write_text("0.7.2\n")
            revision.write_text("a" * 40 + "\n")
            state.write_text(json.dumps({"phase": "failed", "error": "certificate is not yet valid"}))
            result = check_for_update(
                state_path=state, version_path=version, revision_path=revision,
                fetch_json=lambda _url: {"sha": "b" * 40},
                fetch_text=lambda _url: "0.7.0\n",
            )
            self.assertFalse(result["available"])
            self.assertEqual(result["phase"], "idle")
            self.assertEqual(result["error"], "")
            self.assertEqual(result["current_version"], "0.7.2")
            self.assertEqual(result["latest_version"], "0.7.0")
            self.assertEqual(version.read_text(), "0.7.2\n")
            self.assertEqual(json.loads(state.read_text())["error"], "")

    def test_check_detects_new_commit_at_same_version(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            version = root / "version"
            revision = root / "revision"
            state = root / "state.json"
            version.write_text("0.4.0\n", encoding="utf-8")
            revision.write_text("a" * 40 + "\n", encoding="ascii")
            result = check_for_update(
                state_path=state,
                version_path=version,
                revision_path=revision,
                fetch_json=lambda _url: {"sha": "b" * 40},
                fetch_text=lambda _url: "0.4.0\n",
            )
            self.assertTrue(result["available"])
            self.assertEqual(json.loads(state.read_text())["latest_revision"], "b" * 40)

    def test_archive_rejects_path_traversal(self) -> None:
        payload = io.BytesIO()
        with tarfile.open(fileobj=payload, mode="w:gz") as archive:
            info = tarfile.TarInfo("../escape")
            info.size = 1
            archive.addfile(info, io.BytesIO(b"x"))
        payload.seek(0)
        with tarfile.open(fileobj=payload, mode="r:gz") as archive:
            with self.assertRaisesRegex(RuntimeError, "ruta insegura"):
                _validated_members(archive)

    def test_apply_replaces_code_and_records_revision(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            install = root / "opt" / "zeusdnc"
            install.mkdir(parents=True)
            (install / "old.txt").write_text("anterior")
            archive_path = root / "update.tar.gz"
            revision = "c" * 40
            with tarfile.open(archive_path, "w:gz") as archive:
                for name, content in {
                    "repo/VERSION": b"0.4.1\n",
                    "repo/machines.py": b"# machines\n",
                    "repo/qt_app/__init__.py": b"",
                    "repo/zeuz_core/__init__.py": b"",
                    "repo/systemd/zeuz-dnc-qt.service": b"[Service]\n",
                    "repo/systemd/zeuz-dnc-api.service": b"[Service]\n",
                    "repo/systemd/zeuz-update-check.service": b"[Service]\n",
                    "repo/systemd/zeuz-update-apply.service": b"[Service]\n",
                    "repo/systemd/zeuz-update-recover.service": b"[Service]\n",
                }.items():
                    info = tarfile.TarInfo(name)
                    info.size = len(content)
                    archive.addfile(info, io.BytesIO(content))
            digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()
            state_path = root / "state.json"
            state_path.write_text(
                json.dumps(
                    {
                        "available": True,
                        "downloaded": True,
                        "latest_version": "0.4.1",
                        "latest_revision": revision,
                        "archive_sha256": digest,
                    }
                ),
                encoding="utf-8",
            )
            result = apply_downloaded_update(
                state_path=state_path,
                archive_path=archive_path,
                install_dir=install,
                version_path=root / "etc" / "version",
                revision_path=root / "etc" / "revision",
                systemd_dir=root / "systemd",
            )
            self.assertEqual((install / "VERSION").read_text().strip(), "0.4.1")
            self.assertEqual((root / "etc" / "revision").read_text().strip(), revision)
            self.assertFalse(result["available"])


if __name__ == "__main__":
    unittest.main()
