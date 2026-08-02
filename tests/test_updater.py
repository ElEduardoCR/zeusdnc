from __future__ import annotations

import hashlib
import io
import json
import tarfile
import tempfile
import unittest
from pathlib import Path

from zeuz_core.updater import (
    _validated_members,
    apply_downloaded_update,
    check_for_update,
)


class UpdaterTests(unittest.TestCase):
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
